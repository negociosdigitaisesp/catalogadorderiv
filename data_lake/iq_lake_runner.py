"""
iq_lake_runner.py — Pipeline Completo de Descoberta IQ Option
==============================================================
Fábrica Gêmea: replica a arquitetura do lake_runner.py (Deriv) para IQ Option.

FLUXO:
  1. DOWNLOAD   → Baixa 30 dias de M1 via iqoptionapi → catalog_iq.db
  2. MINERAÇÃO  → Agrega métricas Gale 2 por (ativo, hh_mm, direcao)
  3. UPLOAD     → Envia para iq_lake.iq_raw_metrics no Supabase
  4. EXPORTAÇÃO → Gera config_iq_lake.json (Filtro Elite: WR G2 >= 92%)

REGRA @IQ_WATCHDOG:
  - Rate limit 2s entre requests (escala para 5s se "Too many requests")
  - Modo PRÁTICA obrigatório
  - Reconexão automática em caso de erro

REGRA @LGN_AUDITOR:
  - Filtro de Elite IQ: WR G2 >= 92% (payout IQ oscila mais)
"""

import os
import sys
import json
import time
import sqlite3
import logging
from pathlib import Path
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

# Carrega .env da raiz do projeto
load_dotenv(Path(__file__).parent.parent / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)-8s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("iq_lake_runner")

# ─── Configuração ────────────────────────────────────────────────────────────

DB_URL = os.getenv(
    "DB_URL",
    "postgresql://postgres:1CIwYGQv09MUQA@db.ypqekkkrfklaqlzhkbwg.supabase.co:5432/postgres"
)
IQ_EMAIL    = os.getenv("IQ_EMAIL")
IQ_PASSWORD = os.getenv("IQ_PASSWORD")

CATALOG_DB = Path(__file__).parent.parent / "catalog" / "catalog_iq.db"
CONFIG_OUTPUT = Path(__file__).parent / "config_iq_lake.json"

# Ativos: standard + OTC
ATIVOS_IQ = [
    "EURUSD",     "GBPUSD",     "EURJPY",     "AUDUSD",
    "EURUSD-OTC", "GBPUSD-OTC", "EURJPY-OTC", "AUDUSD-OTC",
]

# @IQ_WATCHDOG: Rate limits
RATE_LIMIT_NORMAL = 2.0   # segundos
RATE_LIMIT_BACKED = 5.0   # segundos se "Too many requests"

# @LGN_AUDITOR: Filtro de Elite IQ
ELITE_WR_G2_MIN = 0.92    # 92% mínimo (mais rigoroso que Deriv)
ELITE_N_MIN     = 10       # mínimo de amostras para aprovar

# Janelas
JANELA_30D = 30
JANELA_7D  = 7
JANELA_3D  = 3

# SQLite Schema (idêntico ao Deriv para compatibilidade)
CREATE_CANDLES_SQL = """
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


# ═══════════════════════════════════════════════════════════════════════════════
# PASSO 1: DOWNLOAD DE CANDLES (IQ Option API)
# ═══════════════════════════════════════════════════════════════════════════════

def download_candles_iq(ativos: list[str], days: int = 30) -> int:
    """
    Baixa candles M1 da IQ Option e salva em catalog_iq.db.
    @IQ_WATCHDOG: rate limit 2s (escala para 5s se rate-limited).
    """
    try:
        from iqoptionapi.stable_api import IQ_Option
    except ImportError:
        logger.error("iqoptionapi não encontrado. pip install iqoptionapi")
        sys.exit(1)

    if not IQ_EMAIL or not IQ_PASSWORD:
        logger.error("IQ_EMAIL e IQ_PASSWORD não definidos no .env!")
        sys.exit(1)

    # Conectar
    logger.info("[IQ_DOWNLOAD] Conectando à IQ Option (%s)...", IQ_EMAIL)
    api = IQ_Option(IQ_EMAIL, IQ_PASSWORD)
    check, reason = api.connect()
    if not check:
        logger.error("[IQ_DOWNLOAD] Falha: %s", reason)
        sys.exit(1)
    logger.info("[IQ_DOWNLOAD] ✅ Conectado! Modo PRÁTICA.")
    api.change_balance("PRACTICE")

    # Preparar SQLite
    CATALOG_DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(CATALOG_DB))
    conn.execute("DROP TABLE IF EXISTS candles;")
    conn.execute(CREATE_CANDLES_SQL)
    conn.commit()

    total_candles = 0
    current_rate_limit = RATE_LIMIT_NORMAL

    for idx, ativo in enumerate(ativos, 1):
        logger.info("\n[IQ_DOWNLOAD] ═══ Ativo %d/%d: %s ═══", idx, len(ativos), ativo)

        candles_ativo = []
        end_ts = int(time.time())
        cutoff = int(time.time()) - (days * 86400)
        page = 0

        err_consecutivos = 0

        while True:
            page += 1
            time.sleep(current_rate_limit)  # @IQ_WATCHDOG rate limit

            try:
                raw = api.get_candles(ativo, 60, 1000, end_ts)
                
                # Se a API desconectar no meio, tenta reconectar
                if not api.check_connect():
                    logger.warning("[IQ_WATCHDOG] Conexão caiu! Tentando reconectar...")
                    api.connect()
                    api.change_balance("PRACTICE")
                    time.sleep(2)
                    raw = api.get_candles(ativo, 60, 1000, end_ts)

                err_consecutivos = 0  # reset erro
            except Exception as exc:
                err_str = str(exc).lower()
                if "too many" in err_str or "rate" in err_str:
                    current_rate_limit = RATE_LIMIT_BACKED
                    logger.warning(
                        "[IQ_WATCHDOG] Rate limited! Aumentando sleep para %.0fs...",
                        current_rate_limit,
                    )
                    time.sleep(current_rate_limit)
                    continue
                else:
                    logger.error("[IQ_DOWNLOAD] Erro: %s", exc)
                    err_consecutivos += 1
                    if err_consecutivos >= 3:
                        logger.error("[IQ_DOWNLOAD] Muitas falhas seguidas no %s. Pulando ativo.", ativo)
                        break
                    time.sleep(2)
                    continue

            # A API python as vezes printa "**error** get_candles need reconnect" e retorna []
            if not raw:
                if not api.check_connect():
                    err_consecutivos += 1
                    if err_consecutivos >= 3:
                        logger.error("[IQ_DOWNLOAD] Ativo %s parece offline ou sem dados. Pulando.", ativo)
                        break
                    logger.warning("[IQ_WATCHDOG] get_candles retornou vazio e offline. Reconectando...")
                    api.connect()
                    api.change_balance("PRACTICE")
                    page -= 1 # tenta a pagina de novo
                    continue
                else:
                    logger.info("[IQ_DOWNLOAD] %s: sem mais dados na pagina %d.", ativo, page)
                    break

            for c in raw:
                epoch = int(c.get("from", c.get("at", 0)))
                # IQ pode retornar ms
                if epoch >= 10_000_000_000:
                    epoch = epoch // 1000

                o = float(c.get("open", 0))
                h = float(c.get("max", c.get("high", 0)))
                l = float(c.get("min", c.get("low", 0)))
                cl = float(c.get("close", 0))

                hh = (epoch % 86400) // 3600
                mm = (epoch % 3600) // 60
                hh_mm = f"{hh:02d}:{mm:02d}"
                hora_utc = hh
                dia_semana = ((epoch // 86400) + 3) % 7  # 0=Mon, 6=Sun

                cor = "VERDE" if cl > o else "VERMELHA"

                candles_ativo.append({
                    "timestamp": epoch,
                    "ativo": ativo,
                    "hh_mm": hh_mm,
                    "hora_utc": hora_utc,
                    "dia_semana": dia_semana,
                    "cor_atual": cor,
                    "open": o,
                    "high": h,
                    "low": l,
                    "close": cl,
                })

            earliest = candles_ativo[-1]["timestamp"] if candles_ativo else 0
            if page > 1:
                earliest = min(c["timestamp"] for c in candles_ativo[-len(raw):])

            pct = min(100, int(len(candles_ativo) / 43200 * 100))
            logger.info(
                "[IQ_DOWNLOAD] %s: pagina %d | %d candles (%d%%)",
                ativo, page, len(candles_ativo), pct,
            )

            if earliest <= cutoff:
                break
            if len(raw) < 1000:
                break

            end_ts = earliest - 60

        # Ordenar e calcular proxima_1/2/3 e mhi_seq
        candles_ativo.sort(key=lambda x: x["timestamp"])
        n = len(candles_ativo)

        for i in range(n):
            # mhi_seq (3 velas anteriores)
            if i < 2:
                candles_ativo[i]["mhi_seq"] = "?-?-?"
            else:
                c0 = "V" if candles_ativo[i-2]["cor_atual"] == "VERDE" else "R"
                c1 = "V" if candles_ativo[i-1]["cor_atual"] == "VERDE" else "R"
                c2 = "V" if candles_ativo[i]["cor_atual"] == "VERDE" else "R"
                candles_ativo[i]["mhi_seq"] = f"{c0}-{c1}-{c2}"

            # proxima_1/2/3
            candles_ativo[i]["proxima_1"] = candles_ativo[i+1]["cor_atual"] if i+1 < n else "?"
            candles_ativo[i]["proxima_2"] = candles_ativo[i+2]["cor_atual"] if i+2 < n else "?"
            candles_ativo[i]["proxima_3"] = candles_ativo[i+3]["cor_atual"] if i+3 < n else "?"

            # tendencia (simplificada)
            candles_ativo[i]["tendencia_m5"] = "NEUTRO"
            candles_ativo[i]["tendencia_m15"] = "NEUTRO"

        # Salvar no SQLite
        if candles_ativo:
            conn.executemany(
                """INSERT OR IGNORE INTO candles
                   (timestamp, ativo, hh_mm, hora_utc, dia_semana,
                    cor_atual, mhi_seq, proxima_1, proxima_2, proxima_3,
                    tendencia_m5, tendencia_m15, open, high, low, close)
                   VALUES
                   (:timestamp, :ativo, :hh_mm, :hora_utc, :dia_semana,
                    :cor_atual, :mhi_seq, :proxima_1, :proxima_2, :proxima_3,
                    :tendencia_m5, :tendencia_m15, :open, :high, :low, :close)""",
                candles_ativo,
            )
            conn.commit()
            total_candles += len(candles_ativo)
            logger.info("[IQ_DOWNLOAD] ✅ %s: %d candles salvos", ativo, len(candles_ativo))
        else:
            logger.warning("[IQ_DOWNLOAD] ⚠️  %s: 0 candles obtidos", ativo)

    conn.close()

    try:
        api.disconnect()
    except Exception:
        pass

    logger.info("\n[IQ_DOWNLOAD] ✅ Total: %d candles em %d ativos", total_candles, len(ativos))
    return total_candles


# ═══════════════════════════════════════════════════════════════════════════════
# PASSO 2: MINERAÇÃO DE GRADE (Gale 2)
# ═══════════════════════════════════════════════════════════════════════════════

def get_epoch_corte(dias: int) -> int:
    corte = datetime.utcnow() - timedelta(days=dias)
    return int(corte.timestamp())


def calcular_metricas_janela(df: pd.DataFrame, epoch_corte: int, direcao: str) -> dict:
    """Calcula win_1a, win_g1, win_g2 e n_hit (idêntico ao lake_loader.py)."""
    cor_alvo = "VERDE" if direcao == "CALL" else "VERMELHA"
    df_janela = df[df["timestamp"] >= epoch_corte].copy()

    if df_janela.empty:
        return {"n": 0, "win_1a": 0, "win_g1": 0, "win_g2": 0, "hit": 0}

    df_c = df_janela[df_janela["proxima_3"] != "?"]
    n = len(df_c)
    if n == 0:
        return {"n": 0, "win_1a": 0, "win_g1": 0, "win_g2": 0, "hit": 0}

    win_1a = int((df_c["proxima_1"] == cor_alvo).sum())
    win_g1 = int(((df_c["proxima_1"] != cor_alvo) & (df_c["proxima_2"] == cor_alvo)).sum())
    win_g2 = int(((df_c["proxima_1"] != cor_alvo) & (df_c["proxima_2"] != cor_alvo) & (df_c["proxima_3"] == cor_alvo)).sum())
    hit    = int(((df_c["proxima_1"] != cor_alvo) & (df_c["proxima_2"] != cor_alvo) & (df_c["proxima_3"] != cor_alvo)).sum())

    assert win_1a + win_g1 + win_g2 + hit == n, f"INVARIANTE: {win_1a}+{win_g1}+{win_g2}+{hit} != {n}"

    return {"n": n, "win_1a": win_1a, "win_g1": win_g1, "win_g2": win_g2, "hit": hit}


def minerar_grade() -> pd.DataFrame:
    """Minera padrões Gale 2 do catalog_iq.db e retorna DataFrame."""
    logger.info("\n[IQ_MINER] Iniciando mineração de grade IQ...")

    conn = sqlite3.connect(str(CATALOG_DB))
    ativos = pd.read_sql("SELECT DISTINCT ativo FROM candles", conn)["ativo"].tolist()
    logger.info("[IQ_MINER] Ativos no catalog_iq.db: %s", ativos)

    epoch_30d = get_epoch_corte(JANELA_30D)
    epoch_7d  = get_epoch_corte(JANELA_7D)
    epoch_3d  = get_epoch_corte(JANELA_3D)

    todos = []
    for ativo in ativos:
        logger.info("[IQ_MINER] Processando %s...", ativo)
        df = pd.read_sql(
            "SELECT timestamp, hh_mm, proxima_1, proxima_2, proxima_3 FROM candles WHERE ativo = ? ORDER BY timestamp",
            conn, params=(ativo,),
        )
        if df.empty:
            continue

        hh_mms = sorted(df["hh_mm"].unique())
        for hh_mm in hh_mms:
            df_min = df[df["hh_mm"] == hh_mm]
            for direcao in ["CALL", "PUT"]:
                m30 = calcular_metricas_janela(df_min, epoch_30d, direcao)
                m7  = calcular_metricas_janela(df_min, epoch_7d, direcao)
                m3  = calcular_metricas_janela(df_min, epoch_3d, direcao)

                todos.append({
                    "ativo": ativo, "hh_mm": hh_mm, "direcao": direcao,
                    "n_30d": m30["n"], "win_1a_30d": m30["win_1a"], "win_g1_30d": m30["win_g1"],
                    "win_g2_30d": m30["win_g2"], "hit_30d": m30["hit"],
                    "n_7d": m7["n"], "win_1a_7d": m7["win_1a"], "win_g1_7d": m7["win_g1"],
                    "win_g2_7d": m7["win_g2"], "hit_7d": m7["hit"],
                    "n_3d": m3["n"], "win_1a_3d": m3["win_1a"], "win_g1_3d": m3["win_g1"],
                    "win_g2_3d": m3["win_g2"], "hit_3d": m3["hit"],
                })

        logger.info("[IQ_MINER] ✅ %s: %d hh_mm minerados", ativo, len(hh_mms))

    conn.close()
    df_final = pd.DataFrame(todos)
    logger.info("[IQ_MINER] ✅ Total: %d registros minerados", len(df_final))
    return df_final


# ═══════════════════════════════════════════════════════════════════════════════
# PASSO 3: UPLOAD PARA iq_lake.iq_raw_metrics
# ═══════════════════════════════════════════════════════════════════════════════

def upload_to_supabase(df: pd.DataFrame) -> int:
    """Faz UPSERT dos dados minerados na tabela iq_lake.iq_raw_metrics (otimizado)."""
    logger.info("\n[IQ_UPLOAD] Enviando %d registros para iq_lake.iq_raw_metrics (execute_values)...", len(df))

    conn = psycopg2.connect(DB_URL)
    conn.autocommit = False  # Para transação explícita
    cur = conn.cursor()

    upsert_sql = """
        INSERT INTO iq_lake.iq_raw_metrics
            (ativo, hh_mm, direcao,
             n_30d, win_1a_30d, win_g1_30d, win_g2_30d, hit_30d,
             n_7d, win_1a_7d, win_g1_7d, win_g2_7d, hit_7d,
             n_3d, win_1a_3d, win_g1_3d, win_g2_3d, hit_3d)
        VALUES %s
        ON CONFLICT (ativo, hh_mm, direcao)
        DO UPDATE SET
            n_30d = EXCLUDED.n_30d, win_1a_30d = EXCLUDED.win_1a_30d,
            win_g1_30d = EXCLUDED.win_g1_30d, win_g2_30d = EXCLUDED.win_g2_30d,
            hit_30d = EXCLUDED.hit_30d,
            n_7d = EXCLUDED.n_7d, win_1a_7d = EXCLUDED.win_1a_7d,
            win_g1_7d = EXCLUDED.win_g1_7d, win_g2_7d = EXCLUDED.win_g2_7d,
            hit_7d = EXCLUDED.hit_7d,
            n_3d = EXCLUDED.n_3d, win_1a_3d = EXCLUDED.win_1a_3d,
            win_g1_3d = EXCLUDED.win_g1_3d, win_g2_3d = EXCLUDED.win_g2_3d,
            hit_3d = EXCLUDED.hit_3d,
            updated_at = NOW();
    """

    cols = [
        "ativo", "hh_mm", "direcao",
        "n_30d", "win_1a_30d", "win_g1_30d", "win_g2_30d", "hit_30d",
        "n_7d", "win_1a_7d", "win_g1_7d", "win_g2_7d", "hit_7d",
        "n_3d", "win_1a_3d", "win_g1_3d", "win_g2_3d", "hit_3d"
    ]
    
    # Converte colunas Numpy int64 para int normal do Python para o psycopg2 entender
    df_copy = df[cols].copy()
    for c in cols:
        if c not in ["ativo", "hh_mm", "direcao"]:
            df_copy[c] = df_copy[c].astype(int)

    data = list(df_copy.itertuples(index=False, name=None))
    
    try:
        cur.execute("BEGIN;")
        psycopg2.extras.execute_values(
            cur, upsert_sql, data, page_size=2000
        )
        cur.execute("COMMIT;")
        logger.info("[IQ_UPLOAD] ✅ Upload completo: %d registros", len(data))
    except Exception as e:
        cur.execute("ROLLBACK;")
        logger.error("[IQ_UPLOAD] Erro no upload: %s", e)
        return 0
    finally:
        cur.close()
        conn.close()

    return len(data)


# ═══════════════════════════════════════════════════════════════════════════════
# PASSO 4: EXPORTAÇÃO — Agenda Elite IQ (config_iq_lake.json)
# ═══════════════════════════════════════════════════════════════════════════════

def exportar_config_elite(df: pd.DataFrame) -> dict:
    """
    Filtra horários Elite e gera config_iq_lake.json.
    @LGN_AUDITOR: WR G2 >= 92% obrigatório para IQ Option.
    """
    logger.info("\n[IQ_EXPORT] Gerando agenda Elite IQ (WR G2 >= %.0f%%)...", ELITE_WR_G2_MIN * 100)

    config = {}
    elite_count = 0
    total_checked = 0

    for _, row in df.iterrows():
        n = row["n_30d"]
        if n < ELITE_N_MIN:
            continue

        total_checked += 1
        wins_g2 = row["win_1a_30d"] + row["win_g1_30d"] + row["win_g2_30d"]
        wr_g2 = wins_g2 / n if n > 0 else 0
        wr_1a = row["win_1a_30d"] / n if n > 0 else 0

        # EV G2 (payout IQ ~85%, custo hit = 8.2)
        hit_rate = row["hit_30d"] / n if n > 0 else 0
        ev_g2 = (wr_g2 * 0.85) - (hit_rate * 8.2)

        # @LGN_AUDITOR: Filtro Elite
        if wr_g2 < ELITE_WR_G2_MIN:
            continue
        if ev_g2 <= 0:
            continue

        elite_count += 1
        ativo = row["ativo"]
        hh_mm = row["hh_mm"]
        direcao = row["direcao"]

        strategy_id = f"T{hh_mm.replace(':','')}_IQLAKE_{ativo.replace('-','').replace('_','')}_{direcao}"

        config[strategy_id] = {
            "ativo":           ativo,
            "hh_mm":           hh_mm,
            "direcao":         direcao,
            "p_win_g2":        round(wr_g2, 4),
            "p_win_1a":        round(wr_1a, 4),
            "ev_g2":           round(ev_g2, 4),
            "n_total":         int(n),
            "n_hit":           int(row["hit_30d"]),
            "status":          "APROVADO" if wr_g2 >= 0.95 else "CONDICIONAL",
            "sizing_override": 1.0 if wr_g2 >= 0.95 else 0.5,
            "fonte":           "IQ_LAKE_V1",
            "broker":          "IQ_OPTION",
        }

    # Salvar JSON
    CONFIG_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_OUTPUT, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)

    logger.info("[IQ_EXPORT] ✅ config_iq_lake.json: %d estratégias Elite de %d analisadas",
               elite_count, total_checked)

    # Mostrar Top Horários Elite
    if config:
        print("\n" + "=" * 70)
        print("  ⭐ HORÁRIOS ELITE IQ OPTION (WR G2 >= 92% | EV > 0)")
        print("=" * 70)

        # Ordenar por EV desc
        sorted_strats = sorted(config.values(), key=lambda x: x["ev_g2"], reverse=True)

        aprovados = [s for s in sorted_strats if s["status"] == "APROVADO"]
        condicionais = [s for s in sorted_strats if s["status"] == "CONDICIONAL"]

        print(f"\n  📊 Resumo: {len(aprovados)} APROVADOS | {len(condicionais)} CONDICIONAIS")

        print(f"\n  {'─'*66}")
        print(f"  {'RANK':>4} │ {'ATIVO':<14} │ {'HORA':>5} │ {'DIR':<4} │ {'WR G2':>6} │ {'EV':>7} │ STATUS")
        print(f"  {'─'*66}")

        for rank, s in enumerate(sorted_strats[:30], 1):
            print(
                f"  {rank:4d} │ {s['ativo']:<14} │ {s['hh_mm']:>5} │ {s['direcao']:<4} │ "
                f"{s['p_win_g2']*100:5.1f}% │ {s['ev_g2']:+7.4f} │ {s['status']}"
            )

        print(f"  {'─'*66}")
        if len(sorted_strats) > 30:
            print(f"  ... e mais {len(sorted_strats) - 30} estratégias")
        print("=" * 70)

    return config


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN — Orquestrador
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    inicio = time.time()

    print("\n" + "=" * 70)
    print("  🏭 IQ LAKE RUNNER — Primeiro Ciclo de Descoberta IQ Option")
    print("  @IQ_WATCHDOG | @LGN_AUDITOR | Fábrica Gêmea")
    print("=" * 70)

    # ── Passo 1: Download ────────────────────────────────────────────────────
    print("\n[RUNNER] ═══ PASSO 1/4: DOWNLOAD DE CANDLES ═══")
    t1 = time.time()
    n_candles = download_candles_iq(ATIVOS_IQ, days=30)
    logger.info("[RUNNER] Download: %.1fs | %d candles", time.time()-t1, n_candles)

    if n_candles == 0:
        logger.error("[RUNNER] ❌ Nenhum candle baixado. Abortando.")
        sys.exit(1)

    # ── Passo 2: Mineração ───────────────────────────────────────────────────
    print("\n[RUNNER] ═══ PASSO 2/4: MINERAÇÃO GALE 2 ═══")
    t2 = time.time()
    df_minerado = minerar_grade()
    logger.info("[RUNNER] Mineração: %.1fs | %d registros", time.time()-t2, len(df_minerado))

    if df_minerado.empty:
        logger.error("[RUNNER] ❌ Nenhum dado minerado. Abortando.")
        sys.exit(1)

    # ── Passo 3: Upload ──────────────────────────────────────────────────────
    print("\n[RUNNER] ═══ PASSO 3/4: UPLOAD SUPABASE ═══")
    t3 = time.time()
    n_uploaded = upload_to_supabase(df_minerado)
    logger.info("[RUNNER] Upload: %.1fs | %d registros", time.time()-t3, n_uploaded)

    # ── Passo 4: Exportação ──────────────────────────────────────────────────
    print("\n[RUNNER] ═══ PASSO 4/4: EXPORTAÇÃO ELITE ═══")
    t4 = time.time()
    config = exportar_config_elite(df_minerado)
    logger.info("[RUNNER] Export: %.1fs", time.time()-t4)

    # ── Resumo Final ─────────────────────────────────────────────────────────
    total = time.time() - inicio
    print(f"\n{'='*70}")
    print(f"  ✅ IQ LAKE RUNNER COMPLETO em {total:.1f}s")
    print(f"  Candles baixados:    {n_candles:,}")
    print(f"  Registros minerados: {len(df_minerado):,}")
    print(f"  Upload Supabase:     {n_uploaded:,}")
    print(f"  Estratégias Elite:   {len(config)}")
    print(f"  Config salvo em:     {CONFIG_OUTPUT}")
    print(f"{'='*70}\n")


if __name__ == "__main__":
    main()
