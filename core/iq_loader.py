"""
core/iq_loader.py — Adaptador de Broker para IQ Option
===========================================================
Fábrica Gêmea: herda a inteligência de processamento de velas do DataLoader
(Deriv), mas busca dados da IQ Option via iqoptionapi.

REGRA @IQ_WATCHDOG:
  - Rate limit ESTRITO de 2 segundos entre cada requisição de histórico.
  - Timestamps da IQ Option são convertidos para Epoch UTC padrão (segundos),
    idêntico ao que usamos na Deriv.

NÃO modifica nenhum arquivo existente.
NÃO toca no data_loader.py, lake_loader.py, nem no config.json.
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
import time as _time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ─── Tentar importar DataLoader do agente (herança) ──────────────────────────
try:
    from agente.core.data_loader import DataLoader
except ImportError:
    # Fallback: se o agente não estiver no sys.path, define stub mínimo
    logger.warning("[IQ_LOADER] agente.core.data_loader não encontrado — usando stub.")
    DataLoader = object  # type: ignore[misc,assignment]

# ─── Constantes ───────────────────────────────────────────────────────────────
_IQ_RATE_LIMIT_SEC = 2.0       # @IQ_WATCHDOG: 2s entre cada request
_IQ_DEFAULT_ASSETS = [
    "EURUSD-OTC", "GBPUSD-OTC", "USDJPY-OTC",
    "EURJPY-OTC", "AUDCAD-OTC",
]
_IQ_CATALOG_DB = "catalog/catalog_iq.db"  # banco separado do Deriv

# ─── Schema SQLite (idêntico ao Deriv para compatibilidade) ──────────────────
_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS candles (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp       INTEGER NOT NULL,
    ativo           TEXT    NOT NULL,
    hh_mm           TEXT,
    hora_utc        INTEGER,
    dia_semana      INTEGER,
    cor_atual       TEXT,
    mhi_seq         TEXT,
    proxima_1       TEXT,
    proxima_2       TEXT,
    proxima_3       TEXT,
    tendencia_m5    TEXT,
    tendencia_m15   TEXT,
    open            REAL,
    high            REAL,
    low             REAL,
    close           REAL,
    UNIQUE(timestamp, ativo)
);
"""


class IQLoader(DataLoader if isinstance(DataLoader, type) else object):
    """
    Adaptador IQ Option — Fábrica Gêmea.

    Herda toda a lógica de processamento de velas do DataLoader (Deriv):
      - parse_candles_to_catalog()  → conversão candle → schema v2
      - save_to_catalog()           → persistência em SQLite
      - check_catalog_freshness()   → verificação de frescura
      - _check_depth()              → profundidade mínima

    Substitui apenas a fonte de dados:
      - fetch_candles_iq()          → busca via iqoptionapi (em vez de Deriv WS)

    @IQ_WATCHDOG: rate limit de 2s entre cada request.
    """

    def __init__(self, db_path: str = _IQ_CATALOG_DB):
        if isinstance(DataLoader, type):
            super().__init__()
        self.db_path = db_path
        self._last_request_ts: float = 0.0  # controle de rate limit

    # ─────────────────────────────────────────────────────────────────────────
    # RATE LIMITER — @IQ_WATCHDOG
    # ─────────────────────────────────────────────────────────────────────────

    def _enforce_rate_limit(self) -> None:
        """
        @IQ_WATCHDOG: Força espera de 2s entre cada requisição.
        Previne banimento de IP pela IQ Option.
        """
        elapsed = _time.time() - self._last_request_ts
        if elapsed < _IQ_RATE_LIMIT_SEC:
            wait = _IQ_RATE_LIMIT_SEC - elapsed
            logger.debug("[IQ_WATCHDOG] Rate limit: aguardando %.2fs...", wait)
            _time.sleep(wait)
        self._last_request_ts = _time.time()

    # ─────────────────────────────────────────────────────────────────────────
    # CONVERSÃO DE TIMESTAMP — IQ Option → Epoch UTC
    # ─────────────────────────────────────────────────────────────────────────

    @staticmethod
    def iq_timestamp_to_epoch(ts: int | float) -> int:
        """
        Converte timestamp da IQ Option para Epoch UTC (segundos).

        A IQ Option pode retornar timestamps em:
          - Segundos (epoch UNIX padrão) - valor < 10^10
          - Milissegundos (epoch × 1000) - valor >= 10^10

        Retorna: int epoch UTC em SEGUNDOS (padrão Deriv).

        >>> IQLoader.iq_timestamp_to_epoch(1772304300)      # já em segundos
        1772304300
        >>> IQLoader.iq_timestamp_to_epoch(1772304300000)   # milissegundos
        1772304300
        """
        ts_int = int(ts)
        # Se tem 13+ dígitos → milissegundos → divide por 1000
        if ts_int >= 10_000_000_000:
            return ts_int // 1000
        return ts_int

    # ─────────────────────────────────────────────────────────────────────────
    # FETCH DE CANDLES — IQ Option API
    # ─────────────────────────────────────────────────────────────────────────

    def fetch_candles_iq(
        self,
        ativo: str,
        granularity: int = 60,
        count: int = 43200,
        days: int = 30,
        email: str | None = None,
        password: str | None = None,
    ) -> list[dict]:
        """
        Busca candles históricos da IQ Option via iqoptionapi.

        Rate limit: 2s entre cada página de candles (@IQ_WATCHDOG).

        Retorna lista de dicts no formato unificado:
          [{epoch: int, open: float, high: float, low: float, close: float}, ...]

        Timestamps são convertidos para Epoch UTC segundos.
        """
        try:
            from iqoptionapi.stable_api import IQ_Option
        except ImportError:
            raise ImportError(
                "iqoptionapi não encontrado. Instale com:\n"
                "  pip install iqoptionapi\n"
                "  ou: pip install -U git+https://github.com/iqoptionapi/iqoptionapi.git"
            )

        import os
        email    = email    or os.getenv("IQ_EMAIL")
        password = password or os.getenv("IQ_PASSWORD")

        if not email or not password:
            raise ValueError(
                "Credenciais IQ Option não encontradas. "
                "Defina IQ_EMAIL e IQ_PASSWORD no .env"
            )

        # ── Conectar ─────────────────────────────────────────────────────────
        logger.info("[IQ_LOADER] Conectando à IQ Option como %s...", email)
        api = IQ_Option(email, password)
        check, reason = api.connect()
        if not check:
            raise ConnectionError(f"[IQ_LOADER] Falha ao conectar: {reason}")
        logger.info("[IQ_LOADER] ✅ Conectado à IQ Option!")

        # Modo prática para evitar riscos
        api.change_balance("PRACTICE")

        # ── Paginação backward ───────────────────────────────────────────────
        all_candles: list[dict] = []
        cutoff_epoch = int(_time.time()) - (days * 24 * 3600)
        end_ts = int(_time.time())
        page_size = min(1000, count)  # IQ API max per request

        logger.info(
            "[IQ_LOADER] %s: buscando %d dias de candles M%d...",
            ativo, days, granularity // 60,
        )

        while len(all_candles) < count:
            self._enforce_rate_limit()  # @IQ_WATCHDOG: 2s entre requests

            try:
                candles_raw = api.get_candles(ativo, granularity, page_size, end_ts)
            except Exception as exc:
                logger.error("[IQ_LOADER] Erro ao buscar candles: %s", exc)
                break

            if not candles_raw:
                logger.warning("[IQ_LOADER] %s: API retornou 0 candles na página.", ativo)
                break

            # Converter formato IQ → formato unificado (idêntico ao Deriv)
            page_candles = []
            for c in candles_raw:
                epoch = self.iq_timestamp_to_epoch(c.get("from", c.get("at", 0)))
                page_candles.append({
                    "epoch": epoch,
                    "open":  float(c.get("open", 0)),
                    "high":  float(c.get("max", c.get("high", 0))),
                    "low":   float(c.get("min", c.get("low", 0))),
                    "close": float(c.get("close", 0)),
                })

            all_candles = page_candles + all_candles

            pct = min(100, int(len(all_candles) / count * 100))
            logger.info(
                "[IQ_LOADER] %s: %d/%d candles (%d%%)...",
                ativo, len(all_candles), count, pct,
            )

            # Check cutoff
            earliest = page_candles[0]["epoch"]
            if earliest <= cutoff_epoch:
                break
            if len(candles_raw) < page_size:
                break

            end_ts = earliest - granularity

        api.disconnect()
        logger.info(
            "[IQ_LOADER] %s: %d candles totais (%.1f dias).",
            ativo, len(all_candles), len(all_candles) / (60 * 24),
        )
        return all_candles

    # ─────────────────────────────────────────────────────────────────────────
    # LOAD OR FETCH — Override do fluxo principal para IQ Option
    # ─────────────────────────────────────────────────────────────────────────

    async def load_or_fetch_iq(
        self,
        ativos: list[str] | None = None,
        granularity: int = 60,
        count: int = 43200,
        force_reset: bool = False,
    ) -> pd.DataFrame:
        """
        Fluxo principal para IQ Option: verifica frescura, busca e retorna DF.

        Usa o mesmo banco separado (catalog_iq.db) para não contaminar
        os dados da Deriv.
        """
        ativos = ativos or _IQ_DEFAULT_ASSETS

        if force_reset:
            logger.info("[IQ_LOADER] force_reset=True — recriando catalog_iq.db...")
            self.reset_catalog(self.db_path)

        fresco = self.check_catalog_freshness(self.db_path)
        if fresco:
            profundo = self._check_depth(self.db_path, min_per_ativo=40000)
            if not profundo:
                fresco = False

        if not fresco:
            self.reset_catalog(self.db_path)
            logger.info("[IQ_LOADER] Buscando %d dias da IQ Option para %d ativos...", 30, len(ativos))
            for idx, ativo in enumerate(ativos, 1):
                logger.info("[IQ_LOADER] --- Ativo %d/%d: %s ---", idx, len(ativos), ativo)
                try:
                    candles   = self.fetch_candles_iq(ativo, granularity, count)
                    registros = self.parse_candles_to_catalog(candles, ativo)
                    n         = self.save_to_catalog(registros, self.db_path)
                    logger.info("[IQ_LOADER] %s: %d registros salvos.", ativo, n)
                except Exception as exc:
                    logger.error("[IQ_LOADER] %s: erro: %s", ativo, exc)
                    continue
        else:
            logger.info("[IQ_LOADER] Catalog IQ fresco e profundo — usando dados locais.")

        path = Path(self.db_path)
        if not path.exists():
            return pd.DataFrame()

        with sqlite3.connect(str(path)) as conn:
            df = pd.read_sql("SELECT * FROM candles ORDER BY timestamp ASC", conn)

        logger.info(
            "[IQ_LOADER] DataFrame: %d registros, %d ativos.",
            len(df), df["ativo"].nunique() if not df.empty else 0,
        )
        return df


# ─────────────────────────────────────────────────────────────────────────────
# AUTOTESTE — Prova de Vida: Conversão de Timestamp
# ─────────────────────────────────────────────────────────────────────────────

def _run_timestamp_tests():
    """
    Prova de que o iq_loader.py converte timestamps da IQ Option corretamente.
    """
    print("=" * 60)
    print("  IQ LOADER — Teste de Conversão de Timestamp")
    print("=" * 60)

    test_cases = [
        # (input_ts, expected_epoch_utc, description)
        (1772304300,     1772304300,  "Epoch segundos (formato Deriv padrao)"),
        (1772304300000,  1772304300,  "Epoch milissegundos (formato IQ Option)"),
        (1709164800,     1709164800,  "Epoch segundos (2024-02-28 UTC)"),
        (1709164800123,  1709164800,  "Epoch ms (2024-02-28 UTC + 123ms)"),
        (0,              0,           "Zero (edge case)"),
        (9999999999,     9999999999,  "Maximo 10 digitos (2286-11-20, segundos)"),
        (10000000000,    10000000,    "Minimo 11 digitos (milissegundos)"),
    ]

    all_ok = True
    for ts_input, expected, desc in test_cases:
        result = IQLoader.iq_timestamp_to_epoch(ts_input)
        ok = result == expected
        marker = "OK" if ok else "FAIL"
        symbol = "\u2705" if ok else "\u274c"
        print(f"  {symbol} [{marker}] {desc}")
        print(f"        Input:    {ts_input}")
        print(f"        Expected: {expected}")
        print(f"        Got:      {result}")
        if not ok:
            all_ok = False
        print()

    # Prova de vida: converter timestamp IQ real para HH:MM UTC
    ts_iq = 1772304300000  # milissegundos
    epoch_utc = IQLoader.iq_timestamp_to_epoch(ts_iq)
    hh = (epoch_utc % 86400) // 3600
    mm = (epoch_utc % 3600) // 60
    print(f"  Prova de vida: IQ ts {ts_iq} -> Epoch {epoch_utc} -> {hh:02d}:{mm:02d} UTC")

    print()
    if all_ok:
        print("  \u2705 TODOS OS TESTES PASSARAM!")
    else:
        print("  \u274c FALHA em algum teste!")

    print("=" * 60)
    return all_ok


if __name__ == "__main__":
    _run_timestamp_tests()
