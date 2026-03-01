"""
run_iq_sniper.py — Sniper de Sinais da Fábrica Gêmea (IQ Option)

Implementação do Sniper para ler `data_lake/config_iq_lake.json` e 
inserir sinais na tabela `iq_quant.signals` do Supabase.

Lógica de disparo (herdada da Deriv):
- PRE_SIGNAL no segundo :50
- CONFIRMED no segundo :00
"""

import asyncio
import json
import logging
import os
import sys
import tempfile

from dotenv import load_dotenv

load_dotenv()

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)-8s] %(message)s",
    datefmt="%H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("websockets").setLevel(logging.INFO)

logger = logging.getLogger("iq_sniper")

from core.vps_sniper import DerivSniper, SupabaseManager

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "data_lake", "config_iq_lake.json")
TARGET_TABLE = "iq_quant.signals"


def load_grade_iq() -> list[dict]:
    """Lê config_iq_lake.json e converte para grade_horaria padrão DerivSniper."""
    if not os.path.exists(CONFIG_PATH):
        logger.error("[IQ_SNIPER] %s nao encontrado.", CONFIG_PATH)
        sys.exit(1)

    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        raw = json.load(f)

    grade = []
    for strategy_id, e in raw.items():
        grade.append({
            "strategy_id":    strategy_id,
            "hh_mm":          e["hh_mm"],
            "ativo":          e["ativo"],
            "direcao":        e["direcao"],
            "status":         e["status"],
            "sizing_override": float(e.get("sizing_override", 1.0)),
            "win_rate_g2":    float(e.get("p_win_g2", 0.0)),
            "ev_gale2":       float(e.get("ev_g2", 0.0)),
            "win_1a_rate":    float(e.get("p_win_1a", 0.0)),
            "n_total":        int(e.get("n_total", 0)),
            "n_hit":          int(e.get("n_hit", 0)),
            "n_win_1a":       int(e.get("n_total", 0) * e.get("p_win_1a", 0.0)),
            "variacao":       "IQ_LAKE_V1",
            "fonte":          e.get("fonte", "IQ_OPTION"),
        })

    n_aprovadas    = sum(1 for e in grade if e["status"] == "APROVADO")
    n_condicionais = sum(1 for e in grade if e["status"] == "CONDICIONAL")

    logger.info(
        "[IQ_SNIPER] Grade IQ carregada: %d slots | %d APROVADOS | %d CONDICIONAIS",
        len(grade), n_aprovadas, n_condicionais,
    )
    return grade


async def main() -> None:
    grade = load_grade_iq()

    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_KEY")
    deriv_app_id = os.getenv("DERIV_APP_ID", "85515")
    deriv_token  = os.getenv("DERIV_TOKEN")

    if not supabase_url or not supabase_key:
        logger.error("[CONFIG] SUPABASE_URL e SUPABASE_KEY devem estar no .env")
        sys.exit(1)

    db = SupabaseManager(url=supabase_url, key=supabase_key)

    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    )
    json.dump({"grade_horaria": grade}, tmp)
    tmp.close()

    logger.info("[IQ_SNIPER] Destino: tabela %s", TARGET_TABLE)
    logger.info("[IQ_SNIPER] Sincronizador de Epoch ativo. Iniciando...")
    
    sniper = DerivSniper(
        config=tmp.name,
        app_id=deriv_app_id,
        token=deriv_token,
        db=db,
        table_name=TARGET_TABLE,  # <--- INJEÇÃO DE TABELA DA FÁBRICA GÊMEA
    )

    try:
        await sniper.run()
    except Exception as exc:
        logger.critical("[IQ_SNIPER] Erro fatal: %s", exc, exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("\n[IQ_SNIPER] Encerrado manualmente (Ctrl+C).")
    except Exception as exc:
        logger.critical("[IQ_SNIPER] Crash fatal: %s", exc, exc_info=True)
        sys.exit(1)
