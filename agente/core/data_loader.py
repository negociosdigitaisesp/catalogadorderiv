"""
agente/core/data_loader.py
=====================================
Auto Quant Discovery — Módulo 0 — Camada A: Dados

Responsabilidade:
  v2 — Schema "Ciclo de Horário":
  Verificar a frescura do catalog.db, buscar candles da Deriv API via
  WebSocket assíncrono, converter para o novo schema de V1-V7 e persistir.

  NOVO SCHEMA (cada vela M1 tem):
    timestamp, ativo, hh_mm, hora_utc, dia_semana,
    cor_atual, mhi_seq,
    proxima_1, proxima_2, proxima_3,
    tendencia_m5, tendencia_m15,
    open, high, low, close

  Pergunta padrão suportada:
    "O que aconteceu na vela das 13:55 em todas as segundas-feiras
     quando as 3 anteriores eram Verdes?"

REGRAS ABSOLUTAS (PRD):
  - Sem datetime.now() para lógica de trading
    → epoch Deriv via time.time() APENAS para metadados
  - Sem salvar ticks no Supabase — apenas sinais e metadados
  - Pandas e NumPy permitidos (Camada A)
  - Sem indicadores técnicos clássicos
"""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
from pathlib import Path
from time import time
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ─── Schema SQLite v2 ────────────────────────────────────────────────────────
_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS candles (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp       INTEGER NOT NULL,
    ativo           TEXT    NOT NULL,
    hh_mm           TEXT,          -- '13:55'
    hora_utc        INTEGER,       -- 0-23 (hora inteira UTC)
    dia_semana      INTEGER,       -- 0=Mon … 6=Sun  (Python weekday)
    cor_atual       TEXT,          -- 'VERDE' | 'VERMELHA'
    mhi_seq         TEXT,          -- 'V-V-R' (3 velas anteriores + atual)
    proxima_1       TEXT,          -- cor da vela +1
    proxima_2       TEXT,          -- cor da vela +2
    proxima_3       TEXT,          -- cor da vela +3
    tendencia_m5    TEXT,          -- 'ALTA' | 'BAIXA' | 'NEUTRO'
    tendencia_m15   TEXT,          -- 'ALTA' | 'BAIXA' | 'NEUTRO'
    open            REAL,
    high            REAL,
    low             REAL,
    close           REAL,
    UNIQUE(timestamp, ativo)
);
"""

_DROP_TABLE_SQL = "DROP TABLE IF EXISTS candles;"


class DataLoader:
    """
    Módulo 0 do Auto Quant Discovery — v2 (Ciclo de Horário).

    Fluxo típico:
        loader = DataLoader()
        df = await loader.load_or_fetch(ativos, db_path, app_id)
    """

    # ─────────────────────────────────────────────────────────────────────────
    # MÉTODO 1: check_catalog_freshness
    # ─────────────────────────────────────────────────────────────────────────

    def check_catalog_freshness(
        self,
        db_path: str,
        max_age_hours: int = 24,
    ) -> bool:
        """
        Verifica se o catalog.db tem dados frescos.
        Usa epoch puro — NUNCA datetime.now().
        """
        path = Path(db_path)
        if not path.exists():
            logger.info("[LOADER] catalog.db não encontrado.")
            return False

        try:
            with sqlite3.connect(str(path)) as conn:
                row = conn.execute("SELECT MAX(timestamp) FROM candles").fetchone()

            if row is None or row[0] is None:
                logger.info("[LOADER] catalog.db vazio.")
                return False

            max_ts      = int(row[0])
            now_epoch   = int(time())
            age_seconds = now_epoch - max_ts
            max_age_sec = max_age_hours * 3600

            fresco = age_seconds < max_age_sec
            logger.info(
                "[LOADER] Catalog age: %dh%dm | max: %dh | fresco=%s",
                age_seconds // 3600,
                (age_seconds % 3600) // 60,
                max_age_hours,
                fresco,
            )
            return fresco

        except sqlite3.Error as exc:
            logger.warning("[LOADER] Erro ao verificar frescura: %s", exc)
            return False

    # ─────────────────────────────────────────────────────────────────────────
    # MÉTODO 2: fetch_candles_deriv
    # ─────────────────────────────────────────────────────────────────────────

    async def fetch_candles_deriv(
        self,
        ativo: str,
        granularity: int,
        count: int,
        app_id: str,
        days: int = 30,
    ) -> list[dict]:
        """
        Busca candles históricos via WebSocket Deriv com paginação backward.
        Continua paginando até atingir `count` candles OU o cutoff de `days`.
        Retorna lista de dicts: [{epoch, open, high, low, close}, ...]
        """
        try:
            import websockets
        except ImportError:
            raise ImportError("Instale websockets: pip install websockets")

        MAX_PER_PAGE  = 4900
        cutoff_epoch  = int(time()) - (days * 24 * 3600)
        url           = f"wss://ws.binaryws.com/websockets/v3?app_id={app_id}"
        all_candles: list[dict] = []
        end_epoch: int | str    = "latest"

        logger.info("[LOADER] %s: conectando Deriv WS (%d dias, alvo=%d candles M1)...", ativo, days, count)

        try:
            async with websockets.connect(url, ping_interval=None, open_timeout=30) as ws:
                while len(all_candles) < count:
                    remaining = count - len(all_candles)
                    page_size = min(remaining, MAX_PER_PAGE)
                    req = {
                        "ticks_history":     ativo,
                        "style":             "candles",
                        "granularity":       granularity,
                        "count":             page_size,
                        "end":               end_epoch,
                        "adjust_start_time": 1,
                    }
                    await ws.send(json.dumps(req))
                    resp_raw = await asyncio.wait_for(ws.recv(), timeout=60)
                    resp     = json.loads(resp_raw)

                    error = resp.get("error")
                    if error:
                        raise RuntimeError(f"Deriv API error: {error.get('message', error)}")

                    candles: list[dict] = resp.get("candles", [])
                    if not candles:
                        break

                    all_candles = candles + all_candles
                    pct = min(100, int(len(all_candles) / count * 100))
                    logger.info("[LOADER] %s: %d/%d candles (%d%%)...", ativo, len(all_candles), count, pct)

                    earliest = int(candles[0]["epoch"])
                    if earliest <= cutoff_epoch:
                        break
                    if len(candles) < page_size:
                        break   # API retornou menos que o pedido = sem mais dados

                    end_epoch = earliest - granularity

        except RuntimeError:
            raise
        except Exception as exc:
            raise RuntimeError(f"[LOADER] {ativo}: erro Deriv WS: {exc}") from exc

        if not all_candles:
            raise RuntimeError(f"[LOADER] {ativo}: API retornou 0 candles.")

        logger.info(
            "[LOADER] %s: %d candles totais (%.1f dias).",
            ativo, len(all_candles), len(all_candles) / (60 * 24),
        )
        return all_candles

    # ─────────────────────────────────────────────────────────────────────────
    # MÉTODO 3: parse_candles_to_catalog
    # ─────────────────────────────────────────────────────────────────────────

    def parse_candles_to_catalog(
        self,
        candles: list[dict],
        ativo: str,
    ) -> list[dict]:
        """
        Converte candles raw → schema v2 "Ciclo de Horário".

        Colunas calculadas (todas vetorizadas via NumPy):
          hh_mm         → 'HH:MM' (UTC)
          hora_utc      → inteiro 0-23
          dia_semana    → 0=Mon ... 6=Sun
          cor_atual     → 'VERDE' (close>open) | 'VERMELHA'
          mhi_seq       → 'V-V-R' (3 anteriores + atual)
          proxima_1/2/3 → cores das próximas 3 velas (para backtest Gale)
          tendencia_m5  → cor média de 5 velas (VERDE=ALTA, VERMELHA=BAIXA)
          tendencia_m15 → cor média de 15 velas

        Para mhi_seq: as primeiras 3 velas recebem '?-?-?' pois não há histórico.
        Para proxima_1/2/3: as últimas 1/2/3 velas recebem '?' pois não há futuro.
        """
        if not candles:
            return []

        n = len(candles)

        # ── Extração vetorizada ──────────────────────────────────────────────
        epochs = np.array([int(c["epoch"]) for c in candles])
        opens  = np.array([float(c["open"])  for c in candles])
        highs  = np.array([float(c["high"])  for c in candles])
        lows   = np.array([float(c["low"])   for c in candles])
        closes = np.array([float(c["close"]) for c in candles])

        # ── Tempo ────────────────────────────────────────────────────────────
        hora_utc_arr   = (epochs % 86400) // 3600
        minuto_arr     = (epochs % 3600) // 60
        # dia_semana PRD-padrão: 0=Mon, 6=Sun
        # epoch 0 = 1970-01-01 = Quinta (Unix weekday=3)
        # python: (days_since_epoch + 3) % 7  — 0=Mon
        days_since_epoch = epochs // 86400
        dia_semana_arr = (days_since_epoch + 3) % 7

        # ── Cor de cada vela (vetorizado) ────────────────────────────────────
        # True  → VERDE (bullish: close > open)
        # False → VERMELHA
        verde_mask = closes > opens  # bool array

        # ── mhi_seq: 3 velas anteriores + atual = "P-P-P-A" → "VVR" → "V-V-R"
        # Regra: sequência das 3 velas anteriores (não inclui a atual)
        # mhi_seq[i] descreve as cores das velas [i-2, i-1, i-0] (janela de tamanho 3 terminando em i)
        def _color_char(mask_val: bool) -> str:
            return "V" if mask_val else "R"

        mhi_seq_arr: list[str] = []
        for i in range(n):
            if i < 2:
                mhi_seq_arr.append("?-?-?")
            else:
                mhi_seq_arr.append(
                    f"{_color_char(verde_mask[i-2])}-"
                    f"{_color_char(verde_mask[i-1])}-"
                    f"{_color_char(verde_mask[i])}"
                )

        # ── Próximas 1/2/3 velas (para backtest Gale sem lookahead bias) ────
        # proxima_1[i] = cor da vela [i+1], '?' se não existe
        cor_strs = np.where(verde_mask, "VERDE", "VERMELHA")

        proxima_1 = np.full(n, "?", dtype=object)
        proxima_2 = np.full(n, "?", dtype=object)
        proxima_3 = np.full(n, "?", dtype=object)

        proxima_1[:-1] = cor_strs[1:]
        proxima_1[-1]  = "?"

        proxima_2[:-2] = cor_strs[2:]
        proxima_2[-2:] = "?"

        proxima_3[:-3] = cor_strs[3:]
        proxima_3[-3:] = "?"

        # ── Tendência M5 e M15 (baseado em janela de 5 e 15 velas M1) ───────
        # Proporção de velas VERDE na janela → > 0.5 = ALTA, < 0.5 = BAIXA, = 0.5 = NEUTRO
        def _tendencia(window: int, idx: int) -> str:
            start = max(0, idx - window + 1)
            prop  = float(verde_mask[start:idx + 1].mean())
            if prop > 0.5:
                return "ALTA"
            elif prop < 0.5:
                return "BAIXA"
            return "NEUTRO"

        # Pré-calcula usando cumsum para eficiência O(n)
        cumsum_verde = np.cumsum(verde_mask.astype(int))

        def _rolling_prop(window: int) -> np.ndarray:
            result = np.empty(n, dtype=float)
            for i in range(n):
                start = max(0, i - window + 1)
                count_true = cumsum_verde[i] - (cumsum_verde[start - 1] if start > 0 else 0)
                denom = i - start + 1
                result[i] = count_true / denom
            return result

        prop_m5  = _rolling_prop(5)
        prop_m15 = _rolling_prop(15)

        tend_m5_arr  = np.where(prop_m5  > 0.5, "ALTA", np.where(prop_m5  < 0.5, "BAIXA", "NEUTRO"))
        tend_m15_arr = np.where(prop_m15 > 0.5, "ALTA", np.where(prop_m15 < 0.5, "BAIXA", "NEUTRO"))

        # ── Monta lista de registros ──────────────────────────────────────────
        registros: list[dict] = []
        for i in range(n):
            h = int(hora_utc_arr[i])
            m = int(minuto_arr[i])
            registros.append({
                "timestamp":    int(epochs[i]),
                "ativo":        ativo,
                "hh_mm":        f"{h:02d}:{m:02d}",
                "hora_utc":     h,
                "dia_semana":   int(dia_semana_arr[i]),
                "cor_atual":    str(cor_strs[i]),
                "mhi_seq":      mhi_seq_arr[i],
                "proxima_1":    str(proxima_1[i]),
                "proxima_2":    str(proxima_2[i]),
                "proxima_3":    str(proxima_3[i]),
                "tendencia_m5": str(tend_m5_arr[i]),
                "tendencia_m15": str(tend_m15_arr[i]),
                "open":         float(opens[i]),
                "high":         float(highs[i]),
                "low":          float(lows[i]),
                "close":        float(closes[i]),
            })

        return registros

    # ─────────────────────────────────────────────────────────────────────────
    # MÉTODO 4: save_to_catalog
    # ─────────────────────────────────────────────────────────────────────────

    def save_to_catalog(
        self,
        records: list[dict],
        db_path: str,
    ) -> int:
        """
        Persiste registros no catalog.db.
        Tabela é recriada automaticamente se necessário.
        """
        if not records:
            return 0

        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

        with sqlite3.connect(db_path) as conn:
            conn.execute(_CREATE_TABLE_SQL)
            cursor = conn.executemany(
                """
                INSERT OR IGNORE INTO candles
                (timestamp, ativo, hh_mm, hora_utc, dia_semana,
                 cor_atual, mhi_seq, proxima_1, proxima_2, proxima_3,
                 tendencia_m5, tendencia_m15, open, high, low, close)
                VALUES
                (:timestamp, :ativo, :hh_mm, :hora_utc, :dia_semana,
                 :cor_atual, :mhi_seq, :proxima_1, :proxima_2, :proxima_3,
                 :tendencia_m5, :tendencia_m15, :open, :high, :low, :close)
                """,
                records,
            )
            n_inseridos = cursor.rowcount

        logger.info(
            "[LOADER] %d/%d registros novos inseridos no catalog.",
            n_inseridos,
            len(records),
        )
        return n_inseridos

    # ─────────────────────────────────────────────────────────────────────────
    # MÉTODO 5: reset_catalog
    # ─────────────────────────────────────────────────────────────────────────

    def reset_catalog(self, db_path: str) -> None:
        """
        DROP TABLE candles + CREATE TABLE com schema v2.
        Remove completamente os dados antigos antes de recriar.
        """
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(db_path) as conn:
            conn.execute(_DROP_TABLE_SQL)
            conn.execute(_CREATE_TABLE_SQL)
        logger.info("[LOADER] catalog.db resetado com schema v2 (Ciclo de Horário).")

    # ─────────────────────────────────────────────────────────────────────────
    # MÉTODO 6: _check_depth — verifica profundidade mínima por ativo
    # ─────────────────────────────────────────────────────────────────────────

    def _check_depth(self, db_path: str, min_per_ativo: int = 40000) -> bool:
        """
        Retorna True se TODOS os ativos no catalog têm >= min_per_ativo registros.
        Retorna False (= redownload) se algum ativo está raso ou vazio.
        """
        path = Path(db_path)
        if not path.exists():
            return False
        try:
            with sqlite3.connect(str(path)) as conn:
                rows = conn.execute(
                    "SELECT ativo, COUNT(*) as n FROM candles GROUP BY ativo"
                ).fetchall()
            if not rows:
                return False
            for ativo, n in rows:
                if n < min_per_ativo:
                    logger.info(
                        "[LOADER] %s tem apenas %d registros (min=%d) — redownload necessario.",
                        ativo, n, min_per_ativo,
                    )
                    return False
            return True
        except sqlite3.Error:
            return False

    # ─────────────────────────────────────────────────────────────────────────
    # MÉTODO 7: load_or_fetch
    # ─────────────────────────────────────────────────────────────────────────

    async def load_or_fetch(
        self,
        ativos: list[str],
        db_path: str,
        app_id: str,
        granularity: int = 60,
        count: int = 43200,
        force_reset: bool = False,
    ) -> pd.DataFrame:
        """
        Fluxo principal: verifica frescura E profundidade, e retorna DataFrame.

        NOVA REGRA: se qualquer ativo tem < 40.000 registros → apaga tudo e
        rebaixa 30 dias completos. Garante base profunda para mineração.
        """
        if force_reset:
            logger.info("[LOADER] force_reset=True — recriando schema v2...")
            self.reset_catalog(db_path)

        fresco = self.check_catalog_freshness(db_path)

        # ── NOVA CHECAGEM: profundidade mínima por ativo ──────────────────────
        if fresco:
            profundo = self._check_depth(db_path, min_per_ativo=40000)
            if not profundo:
                logger.info("[LOADER] Catalog fresco MAS raso (<40k/ativo) — forçando redownload completo.")
                fresco = False

        if not fresco:
            # Reseta para garantir schema v2 limpo + dados profundos
            self.reset_catalog(db_path)
            logger.info("[LOADER] Buscando 30 dias completos da Deriv para %d ativos...", len(ativos))
            for idx, ativo in enumerate(ativos, 1):
                logger.info("[LOADER] --- Ativo %d/%d: %s ---", idx, len(ativos), ativo)
                try:
                    candles   = await self.fetch_candles_deriv(ativo, granularity, count, app_id)
                    registros = self.parse_candles_to_catalog(candles, ativo)
                    n         = self.save_to_catalog(registros, db_path)
                    logger.info("[LOADER] %s: %d registros salvos.", ativo, n)
                except Exception as exc:
                    logger.error("[LOADER] %s: erro: %s", ativo, exc)
                    continue
        else:
            logger.info("[LOADER] Catalog fresco E profundo — usando dados locais.")

        path = Path(db_path)
        if not path.exists():
            logger.warning("[LOADER] catalog.db não existe. Retornando DF vazio.")
            return pd.DataFrame()

        with sqlite3.connect(str(path)) as conn:
            df = pd.read_sql("SELECT * FROM candles ORDER BY timestamp ASC", conn)

        logger.info(
            "[LOADER] DataFrame unificado: %d registros, %d ativos.",
            len(df),
            df["ativo"].nunique() if not df.empty else 0,
        )
        return df
