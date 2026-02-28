"""
run_discovery.py — Ponto de entrada do Auto Quant Discovery

Executa o ciclo completo:
  DataLoader -> HypothesisGenerator -> PatternMiner -> StrategyValidator -> StrategyWriter

Ao terminar, gera automaticamente um JSON em catalog/cycles/cycle_EPOCH.json
com as metricas do ciclo e todas as estrategias descobertas.

USO:
  python run_discovery.py
  python run_discovery.py --ativos R_10 BOOM500 CRASH500
  python run_discovery.py --output resultados/ --log-level DEBUG

VARIAVEIS DE AMBIENTE (.env):
  DERIV_APP_ID      -> ID do App Deriv (default: 85515)
  SUPABASE_URL      -> URL do projeto Supabase (opcional — skip se ausente)
  SUPABASE_KEY      -> Chave service_role do Supabase (opcional)

SAIDA:
  config.json           -> atualizado com secao grade_horaria
  catalog/cycles/       -> cycle_EPOCH.json com resultado completo
  catalog/reports/      -> relatorio .txt por estrategia
"""

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path
from time import time

from dotenv import load_dotenv

load_dotenv()

# Garante que imports do pacote agente funcionem a partir da raiz
_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from agente.core.agent_discovery import AgentDiscovery

# Ativos padrao do PRD (9 ativos Deriv)
_ATIVOS_PADRAO = [
    "R_10", "R_25", "R_50", "R_75", "R_100",
    "CRASH500", "CRASH1000",
    "BOOM500", "BOOM1000",
]


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Auto Quant Discovery — Grade Horaria de Elite"
    )
    p.add_argument(
        "--ativos", nargs="+", default=None, metavar="ATIVO",
        help="Ativos a processar (default: 9 ativos padrao do PRD)",
    )
    p.add_argument(
        "--output", default="catalog/cycles", metavar="DIR",
        help="Diretorio de saida do JSON (default: catalog/cycles)",
    )
    p.add_argument(
        "--log-level", default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Nivel de log (default: INFO)",
    )
    return p.parse_args()


async def main() -> int:
    args = _parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)s] %(name)s -- %(message)s",
        datefmt="%H:%M:%S",
    )

    ativos = args.ativos or _ATIVOS_PADRAO
    inicio = int(time())

    print()
    print("+" + "=" * 56 + "+")
    print("|     AUTO QUANT DISCOVERY -- GRADE HORARIA DE ELITE      |")
    print("+" + "=" * 56 + "+")
    print(f"|  Ativos  : {', '.join(ativos)}")
    print(f"|  Config  : config.json")
    print(f"|  DB      : catalog/catalog.db")
    print(f"|  Saida   : {args.output}/cycle_{inicio}.json")
    print("+" + "=" * 56 + "+")
    print()

    agent = AgentDiscovery(
        config_path="config.json",
        db_path="catalog/catalog.db",
    )

    # ── Ciclo principal ───────────────────────────────────────────────────────
    cycle_result = await agent.run_cycle(ativos=ativos)
    agent.print_final_report(cycle_result)

    # ── Monta JSON de saida ───────────────────────────────────────────────────
    # Le as estrategias descobertas do config.json (secao grade_horaria)
    config_path = Path("config.json")
    grade_horaria: list = []
    if config_path.exists():
        try:
            with open(config_path, encoding="utf-8") as fp:
                cfg = json.load(fp)
            grade_horaria = list(cfg.get("grade_horaria", {}).values())
        except Exception as exc:
            logging.warning("Nao foi possivel ler grade_horaria do config.json: %s", exc)

    output_json = {
        "ciclo": {
            "started_at":           inicio,
            "ativos":               ativos,
            **cycle_result,
        },
        "estrategias": grade_horaria,
    }

    # ── Persiste JSON ─────────────────────────────────────────────────────────
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / f"cycle_{inicio}.json"

    with open(output_file, "w", encoding="utf-8") as fp:
        json.dump(output_json, fp, ensure_ascii=False, indent=2)

    n_strat = len(grade_horaria)
    print(f"[OK] JSON salvo: {output_file}")
    print(f"     {n_strat} estrategia(s) na secao grade_horaria")
    print()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except KeyboardInterrupt:
        print("\n[AGENT] Interrompido pelo operador.")
        sys.exit(0)
