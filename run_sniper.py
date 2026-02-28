"""
run_sniper.py — Ponto de entrada do Sniper VPS (Camada B)

Uso:
    python run_sniper.py

Variáveis de ambiente requeridas (.env):
    SUPABASE_URL      → URL do projeto Supabase
    SUPABASE_KEY      → Chave service_role do Supabase
    DERIV_APP_ID      → ID do App Deriv (obter em developers.deriv.com)
    DERIV_TOKEN       → Token Deriv com permissão de leitura (opcional)
"""

import asyncio
import json
import logging
import os
import sys

from dotenv import load_dotenv

# Carrega .env da raiz do projeto
load_dotenv()

# ── Logging configurado ANTES de qualquer import do core ──────────────────────
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)-8s] %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
    ],
)
# Silencia ruído dos libs HTTP
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("websockets").setLevel(logging.INFO)
logging.getLogger("hpack").setLevel(logging.WARNING)
logging.getLogger("h2").setLevel(logging.WARNING)

logger = logging.getLogger("sniper.main")

from core.vps_sniper import DerivSniper, SupabaseManager

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")


def load_grade_horaria() -> list[dict]:
    """
    Carrega APENAS a seção grade_horaria do config.json.

    O config.json pode conter chaves legadas (CRASH1000, BOOM500 etc.).
    O Sniper só precisa da grade_horaria (lista de slots HH:MM).
    """
    if not os.path.exists(CONFIG_PATH):
        logger.error("[CONFIG] config.json não encontrado em: %s", CONFIG_PATH)
        logger.error("         Execute catalogar_completo.py primeiro.")
        sys.exit(1)

    logger.info("[CONFIG] Carregando config.json (%s)...", CONFIG_PATH)
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        config = json.load(f)

    # Suporta os dois formatos:
    # 1. {"grade_horaria": [...]}   (novo Oráculo v2)
    # 2. Legado {"CRASH1000": {...}, ..., "grade_horaria": [...]}
    if "grade_horaria" in config:
        grade = config["grade_horaria"]
    elif isinstance(config, list):
        grade = config
    else:
        logger.error("[CONFIG] Nenhuma chave 'grade_horaria' encontrada no config.json.")
        logger.error("         Execute catalogar_completo.py para gerar a grade.")
        sys.exit(1)

    if not grade:
        logger.error("[CONFIG] grade_horaria está vazia. Execute o Oráculo primeiro.")
        sys.exit(1)

    n_aprovadas    = sum(1 for e in grade if e.get("status") == "APROVADO")
    n_condicionais = sum(1 for e in grade if e.get("status") == "CONDICIONAL")

    logger.info(
        "[CONFIG] Grade carregada: %d slots | %d APROVADOS | %d CONDICIONAIS",
        len(grade), n_aprovadas, n_condicionais,
    )
    return grade


async def main() -> None:
    # ── 1. Carregar Grade Horária ──────────────────────────────────────────────
    grade = load_grade_horaria()

    # ── 2. Credenciais ─────────────────────────────────────────────────────────
    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_KEY")
    deriv_app_id = os.getenv("DERIV_APP_ID", "85515")
    deriv_token  = os.getenv("DERIV_TOKEN")

    if not supabase_url or not supabase_key:
        logger.error("[CONFIG] SUPABASE_URL e SUPABASE_KEY devem estar no .env")
        sys.exit(1)

    logger.info("[CONFIG] SUPABASE_URL: %s", supabase_url[:40])
    logger.info("[CONFIG] APP_ID:       %s", deriv_app_id)
    logger.info("[CONFIG] TOKEN:        %s", "✅ configurado" if deriv_token else "⚠️  ausente (modo anônimo)")

    # ── 3. Inicializar Supabase ────────────────────────────────────────────────
    db = SupabaseManager(url=supabase_url, key=supabase_key)

    # ── 4. Inicializar e disparar o Sniper ─────────────────────────────────────
    # Passa a grade como string JSON para reutilizar _parse_agenda internamente
    import tempfile
    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    )
    json.dump({"grade_horaria": grade}, tmp)
    tmp.close()

    logger.info("[SNIPER] Inicializando (config_temp=%s)...", tmp.name)
    sniper = DerivSniper(
        config=tmp.name,     # passa o PATH (str) → não precisa reserializar
        app_id=deriv_app_id,
        token=deriv_token,
        db=db,
    )

    logger.info("[SNIPER] Sniper pronto. Iniciando loop 24/7...")

    try:
        await sniper.run()
    except Exception as exc:
        logger.critical("[SNIPER] Erro fatal não esperado: %s", exc, exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("\n[SNIPER] Encerrado manualmente pelo operador (Ctrl+C).")
    except Exception as exc:
        logger.critical("[SNIPER] Crash fatal: %s", exc, exc_info=True)
        sys.exit(1)
