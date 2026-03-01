"""
run_sniper_lake.py — Sniper paralelo que lê data_lake/config_lake.json

Implementação do PRD_DATA_LAKE.md — Seção 11, Passo 3.

DIFERENÇAS em relação ao run_sniper.py:
- Lê data_lake/config_lake.json (gerado pelo lake_runner.py)
- Remapeia os campos do formato DATA_LAKE para o formato que o DerivSniper espera
- Adiciona variacao="LAKE_V1" para distinguir nos logs e no Supabase

NÃO modifica run_sniper.py nem config.json.
O sistema antigo continua rodando em paralelo intacto.

Uso:
    python run_sniper_lake.py
"""

import asyncio
import json
import logging
import os
import sys
import tempfile

from dotenv import load_dotenv

# Carrega .env da raiz do projeto (mesmo .env do sniper original)
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
logging.getLogger("hpack").setLevel(logging.WARNING)
logging.getLogger("h2").setLevel(logging.WARNING)

logger = logging.getLogger("sniper_lake.main")

from core.vps_sniper import DerivSniper, SupabaseManager

# config_lake.json gerado pelo lake_runner.py
CONFIG_LAKE_PATH = os.path.join(os.path.dirname(__file__), "data_lake", "config_lake.json")


def load_grade_lake() -> list[dict]:
    """
    Lê config_lake.json e converte para a lista grade_horaria
    que o DerivSniper espera.

    Remapeamento de campos (DATA_LAKE → DerivSniper):
        p_win_g2  → win_rate_g2
        ev_g2     → ev_gale2
        p_win_1a  → win_1a_rate
    """
    if not os.path.exists(CONFIG_LAKE_PATH):
        logger.error("[LAKE] config_lake.json nao encontrado: %s", CONFIG_LAKE_PATH)
        logger.error("       Execute: python data_lake/lake_runner.py")
        sys.exit(1)

    logger.info("[LAKE] Carregando config_lake.json (%s)...", CONFIG_LAKE_PATH)
    with open(CONFIG_LAKE_PATH, "r", encoding="utf-8") as f:
        raw = json.load(f)

    # config_lake.json é um dict de strategy_id -> config
    grade = []
    for strategy_id, e in raw.items():
        # Remapeia campos do formato DATA_LAKE para o formato DerivSniper
        entrada = {
            # Campos funcionais (idênticos nos dois formatos)
            "strategy_id":    strategy_id,
            "hh_mm":          e["hh_mm"],
            "ativo":          e["ativo"],
            "direcao":        e["direcao"],
            "status":         e["status"],
            "sizing_override": float(e.get("sizing_override", 1.0)),

            # Métricas remapeadas
            "win_rate_g2":    float(e.get("p_win_g2", 0.0)),
            "ev_gale2":       float(e.get("ev_g2", 0.0)),
            "win_1a_rate":    float(e.get("p_win_1a", 0.0)),

            # Contagens
            "n_total":        int(e.get("n_total", 0)),
            "n_hit":          int(e.get("n_hit", 0)),

            # Marcador de origem para logs e Supabase
            "variacao":       "LAKE_V1",
            "fonte":          e.get("fonte", "DATA_LAKE_V1"),
            "n_filtros":      int(e.get("n_filtros", 0)),
            "filtros":        e.get("filtros", ""),
        }
        grade.append(entrada)

    n_aprovadas    = sum(1 for e in grade if e["status"] == "APROVADO")
    n_condicionais = sum(1 for e in grade if e["status"] == "CONDICIONAL")

    logger.info(
        "[LAKE] Grade carregada: %d slots | %d APROVADOS | %d CONDICIONAIS",
        len(grade), n_aprovadas, n_condicionais,
    )
    return grade


async def main() -> None:
    # ── 1. Carregar Grade do Data Lake ─────────────────────────────────────────
    grade = load_grade_lake()

    # ── 2. Credenciais (mesmo .env do sniper original) ─────────────────────────
    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_KEY")
    deriv_app_id = os.getenv("DERIV_APP_ID", "85515")
    deriv_token  = os.getenv("DERIV_TOKEN")

    if not supabase_url or not supabase_key:
        logger.error("[CONFIG] SUPABASE_URL e SUPABASE_KEY devem estar no .env")
        sys.exit(1)

    logger.info("[CONFIG] SUPABASE_URL: %s", supabase_url[:40])
    logger.info("[CONFIG] APP_ID:       %s", deriv_app_id)
    logger.info("[CONFIG] TOKEN:        %s", "configurado" if deriv_token else "ausente (modo anonimo)")
    logger.info("[CONFIG] Fonte:        DATA_LAKE_V1 (run_sniper_lake.py)")

    # ── 3. Inicializar Supabase ────────────────────────────────────────────────
    db = SupabaseManager(url=supabase_url, key=supabase_key)

    # ── 4. Gera config temp no formato grade_horaria e passa ao DerivSniper ────
    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    )
    json.dump({"grade_horaria": grade}, tmp)
    tmp.close()

    logger.info("[SNIPER_LAKE] Inicializando com grade do Data Lake (config_temp=%s)...", tmp.name)
    sniper = DerivSniper(
        config=tmp.name,
        app_id=deriv_app_id,
        token=deriv_token,
        db=db,
    )

    logger.info("[SNIPER_LAKE] Sniper Lake pronto. Iniciando loop 24/7...")

    try:
        await sniper.run()
    except Exception as exc:
        logger.critical("[SNIPER_LAKE] Erro fatal: %s", exc, exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("\n[SNIPER_LAKE] Encerrado manualmente (Ctrl+C).")
    except Exception as exc:
        logger.critical("[SNIPER_LAKE] Crash fatal: %s", exc, exc_info=True)
        sys.exit(1)
