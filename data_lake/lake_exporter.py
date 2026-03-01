"""
lake_exporter.py — Lê vw_grade_unificada e gera config_lake.json

LÓGICA:
- Consulta a view vw_grade_unificada no Supabase via psycopg2 (conexão direta)
- Filtra apenas APROVADO e CONDICIONAL
- Gera config_lake.json no formato compatível com o Sniper
- O Sniper antigo continua lendo config.json (intocável)
- Este arquivo é o futuro config_lake.json (paralelo, não substitui ainda)

NÃO modifica config.json nem qualquer arquivo existente.
"""

import os
import json
import psycopg2
import psycopg2.extras
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://postgres:1CIwYGQv09MUQA@db.ypqekkkrfklaqlzhkbwg.supabase.co:5432/postgres"
)
OUTPUT_PATH = Path(__file__).parent / "config_lake.json"

QUERY = """
SELECT
    ativo, hh_mm, direcao,
    n_filtros, filtros_aprovados,
    wr_g2, wr_1a, ev_g2,
    n_total, n_hit,
    status, stake_multiplier
FROM hft_lake.vw_grade_unificada
WHERE status IN ('APROVADO', 'CONDICIONAL')
ORDER BY n_filtros DESC, ev_g2 DESC;
"""


def exportar_grade() -> dict:
    """
    Lê a grade unificada do Supabase via psycopg2 e converte para config_lake.json.
    """
    print("\n[EXPORTER] Consultando vw_grade_unificada...")

    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    try:
        cur.execute(QUERY)
        registros = cur.fetchall()
    finally:
        cur.close()
        conn.close()

    print(f"[EXPORTER] {len(registros)} estrategias encontradas")

    config = {}
    for r in registros:
        strategy_id = f"T{r['hh_mm'].replace(':','')}_LAKE_{r['ativo'].replace('_','')}_{r['direcao']}"

        config[strategy_id] = {
            "ativo":           r["ativo"],
            "hh_mm":           r["hh_mm"],
            "direcao":         r["direcao"],
            "p_win_g2":        float(r["wr_g2"]) if r["wr_g2"] is not None else 0.0,
            "p_win_1a":        float(r["wr_1a"]) if r["wr_1a"] is not None else 0.0,
            "ev_g2":           float(r["ev_g2"]) if r["ev_g2"] is not None else 0.0,
            "n_total":         r["n_total"],
            "n_hit":           r["n_hit"],
            "n_filtros":       r["n_filtros"],
            "filtros":         r["filtros_aprovados"],
            "sizing_override": float(r["stake_multiplier"]),
            "status":          r["status"],
            "fonte":           "DATA_LAKE_V1",
        }

    return config


def salvar_config(config: dict):
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
    print(f"[EXPORTER] config_lake.json salvo: {len(config)} estrategias -> {OUTPUT_PATH}")


def run_exporter():
    config = exportar_grade()
    salvar_config(config)

    aprovadas    = sum(1 for v in config.values() if v["status"] == "APROVADO")
    condicionais = sum(1 for v in config.values() if v["status"] == "CONDICIONAL")
    print(f"\n[EXPORTER] Sumario:")
    print(f"  APROVADO:    {aprovadas}")
    print(f"  CONDICIONAL: {condicionais}")
    print(f"  TOTAL:       {len(config)}")


if __name__ == "__main__":
    run_exporter()
