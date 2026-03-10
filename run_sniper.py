"""
run_sniper.py — Ponto de entrada do Sniper VPS (Camada B)

Uso:
    python run_sniper.py

Variáveis de ambiente requeridas (.env):
    SUPABASE_URL      → URL do projeto Supabase
    SUPABASE_KEY      → Chave service_role do Supabase
    DERIV_APP_ID      → ID do App Deriv (obter em developers.deriv.com)
    DERIV_TOKEN       → Token Deriv com permissão de leitura (opcional)

REGRA DO MINUTO SOBERANO:
    A VPS consulta a View vw_grade_unificada do Supabase para obter a grade
    já filtrada (1 ativo por minuto — o "Campeão do Minuto").
    O config.json local é usado apenas como fallback caso a View esteja
    indisponível.
    Independente da fonte, _aplicar_minuto_soberano() garante que nunca
    cheguem múltiplos ativos para o mesmo HH:MM ao DerivSniper.
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

# View do Supabase que representa o "Rei de cada Minuto"
_VIEW_SOBERANA = "vw_grade_unificada"


def _aplicar_minuto_soberano(grade: list[dict]) -> list[dict]:
    """
    Garante a regra: UN minuto, UM ativo, UMA bala.

    Para cada HH:MM, mantém apenas o slot com maior ev_gale2
    (critério de desempate: maior win_rate_g2). Todos os demais
    são silenciados com log de aviso.

    Retorna a grade filtrada (máx. 1 slot por HH:MM).
    """
    index: dict[str, dict] = {}
    for slot in grade:
        hh_mm = slot.get("hh_mm", "??:??")
        if hh_mm not in index:
            index[hh_mm] = slot
        else:
            atual = index[hh_mm]
            ev_novo   = float(slot.get("ev_gale2",    slot.get("ev_g2",    0.0)))
            ev_atual  = float(atual.get("ev_gale2",   atual.get("ev_g2",   0.0)))
            wr_novo   = float(slot.get("win_rate_g2", slot.get("p_win_g2", 0.0)))
            wr_atual  = float(atual.get("win_rate_g2",atual.get("p_win_g2",0.0)))
            if ev_novo > ev_atual or (ev_novo == ev_atual and wr_novo > wr_atual):
                bloqueado = atual.get("strategy_id", atual.get("ativo", "?"))
                vencedor  = slot.get("strategy_id",  slot.get("ativo", "?"))
                logger.info(
                    "[SOVEREIGN] %s → bloqueado para %s | Campeão: %s (EV=%.4f)",
                    hh_mm, bloqueado, vencedor, ev_novo,
                )
                index[hh_mm] = slot
            else:
                bloqueado = slot.get("strategy_id", slot.get("ativo", "?"))
                logger.info(
                    "[SOVEREIGN] %s → bloqueado: %s (EV=%.4f < campeão EV=%.4f)",
                    hh_mm, bloqueado, ev_novo, ev_atual,
                )

    soberana = list(index.values())
    if len(soberana) < len(grade):
        logger.info(
            "[SOVEREIGN] Grade filtrada: %d → %d slots (Minuto Soberano ativo)",
            len(grade), len(soberana),
        )
    return soberana


async def _load_grade_supabase(db_client) -> list[dict] | None:
    """
    Consulta a View Soberana no Supabase: SELECT * FROM vw_grade_unificada.

    Retorna a grade no formato padrão DerivSniper, ou None em caso de falha.
    A View já retorna apenas estratégias APROVADAS/CONDICIONAIS e já aplicou
    a regra do Minuto Soberano no banco — esta função é a fonte primária.
    """
    try:
        result = await asyncio.to_thread(
            lambda: db_client.table(_VIEW_SOBERANA).select("*").execute()
        )
        rows = result.data or []
        if not rows:
            logger.warning("[SOVEREIGN] View %s retornou 0 linhas.", _VIEW_SOBERANA)
            return None

        grade = []
        for e in rows:
            hh_mm = e.get("hh_mm") or e.get("horario_alvo")
            if not hh_mm:
                continue
            grade.append({
                "strategy_id":     e.get("strategy_id", f"T{hh_mm.replace(':','')}_{e.get('ativo','?')}"),
                "hh_mm":           hh_mm,
                "ativo":           e.get("ativo", "?"),
                "direcao":         e.get("direcao", "CALL"),
                "status":          e.get("status", "APROVADO"),
                "sizing_override": float(e.get("sizing_override", 1.0)),
                "win_rate_g2":     float(e.get("win_rate_g2") or e.get("p_win_g2") or 0.0),
                "ev_gale2":        float(e.get("ev_gale2")    or e.get("ev_g2")    or 0.0),
                "win_1a_rate":     float(e.get("win_1a_rate") or e.get("p_win_1a") or 0.0),
                "n_total":         int(e.get("n_total", 0)),
                "n_hit":           int(e.get("n_hit",   0)),
                "n_win_1a":        int(e.get("n_win_1a", 0)),
                "n_win_g1":        int(e.get("n_win_g1", 0)),
                "n_win_g2":        int(e.get("n_win_g2", 0)),
                "variacao":        e.get("variacao", "LAKE_V1"),
                "fonte":           e.get("fonte",    "VW_GRADE_UNIFICADA"),
            })

        n_aprov = sum(1 for e in grade if e["status"] == "APROVADO")
        n_cond  = sum(1 for e in grade if e["status"] == "CONDICIONAL")
        logger.info(
            "[SOVEREIGN] View %s carregada: %d slots | %d APROVADOS | %d CONDICIONAIS",
            _VIEW_SOBERANA, len(grade), n_aprov, n_cond,
        )
        return grade

    except Exception as exc:
        logger.warning(
            "[SOVEREIGN] Falha ao consultar View %s: %s — usando config.json como fallback.",
            _VIEW_SOBERANA, exc,
        )
        return None


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
    # ── 1. Credenciais (necessárias antes da consulta ao Supabase) ─────────────
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

    # ── 2. Inicializar Supabase ────────────────────────────────────────────────
    db = SupabaseManager(url=supabase_url, key=supabase_key)

    # ── 3. Carregar Grade — Fonte Primária: View Soberana do Supabase ──────────
    logger.info("[SOVEREIGN] Consultando View %s no Supabase...", _VIEW_SOBERANA)
    grade = await _load_grade_supabase(db.client)

    if grade is None:
        logger.warning("[SOVEREIGN] Fallback: carregando grade do config.json local.")
        grade = load_grade_horaria()

    # ── 4. Aplicar Regra do Minuto Soberano (UN minuto = UM ativo) ─────────────
    grade = _aplicar_minuto_soberano(grade)

    if not grade:
        logger.error("[SOVEREIGN] Grade vazia após filtro soberano. Abortando.")
        sys.exit(1)

    # ── 5. Inicializar e disparar o Sniper ─────────────────────────────────────
    import tempfile
    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    )
    json.dump({"grade_horaria": grade}, tmp)
    tmp.close()

    logger.info("[SNIPER] Inicializando (config_temp=%s)...", tmp.name)
    sniper = DerivSniper(
        config=tmp.name,
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
