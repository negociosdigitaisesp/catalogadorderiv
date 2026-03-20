"""
supremo_exporter.py — Lê vw_grade_suprema e gera config_supremo.json

ISOLADO: NÃO toca em nenhum arquivo existente.
Lê:  hft_lake.vw_grade_suprema (view nova)
Gera: data_lake/config_supremo.json (arquivo novo)

O sistema antigo (lake_exporter.py → config_lake.json) continua intacto.
O Sniper antigo (run_sniper.py → config.json) continua intacto.

FORMATO DO config_supremo.json:
  Compatível com o Sniper, mas com campos extras:
    - modo_operacao: "SEM_GALE" ou "GALE_2"
    - max_gale: 0 (SUPREMO) ou 2 (demais)
    - stake_leverage: multiplicador de stake para SUPREMO
    - ev_1a_puro: EV do flat bet sem gale
"""

import os
import json
import psycopg2
import psycopg2.extras
from pathlib import Path
from dotenv import load_dotenv

# Carrega .env do diretório do script (data_lake/.env)
load_dotenv(Path(__file__).parent / ".env")

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://postgres:1CIwYGQv09MUQA@db.ypqekkkrfklaqlzhkbwg.supabase.co:5432/postgres"
)

OUTPUT_PATH = Path(__file__).parent / "config_supremo.json"

QUERY = """
SELECT
    ativo,
    hh_mm,
    direcao,
    n_filtros,
    filtros_aprovados,
    tem_fv6,
    wr_g2,
    wr_1a,
    ev_gale2,
    ev_1a_puro,
    score_30_7,
    n_total,
    n_hit,
    stake_leverage,
    ev_fv6,
    wr_1a_fv6,
    assimetria_1a,
    status,
    modo_operacao,
    stake_multiplier,
    max_gale
FROM hft_lake.vw_grade_suprema
WHERE status IN ('SUPREMO', 'APROVADO', 'CONDICIONAL')
ORDER BY
    CASE status
        WHEN 'SUPREMO'     THEN 0
        WHEN 'APROVADO'    THEN 1
        WHEN 'CONDICIONAL' THEN 2
        ELSE 3
    END,
    ev_gale2 DESC NULLS LAST;
"""


def exportar_grade_suprema() -> dict:
    """Lê vw_grade_suprema e monta dicionário para config_supremo.json."""
    print("\n[SUPREMO EXPORTER] Consultando vw_grade_suprema...")

    conn = psycopg2.connect(DATABASE_URL)
    cur  = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    try:
        cur.execute(QUERY)
        registros = cur.fetchall()
    finally:
        cur.close()
        conn.close()

    print(f"[SUPREMO EXPORTER] {len(registros)} estrategias encontradas")

    config = {}
    for r in registros:
        strategy_id = (
            f"T{r['hh_mm'].replace(':','')}"
            f"_SUPREMO_{r['ativo'].replace('_','')}"
            f"_{r['direcao']}"
        )

        config[strategy_id] = {
            # Identificação
            "ativo":           r["ativo"],
            "hh_mm":           r["hh_mm"],
            "direcao":         r["direcao"],

            # Métricas de performance
            "p_win_g2":        float(r["wr_g2"]        or 0),
            "p_win_1a":        float(r["wr_1a"]        or 0),
            "ev_gale2":        float(r["ev_gale2"]     or 0),
            "ev_1a_puro":      float(r["ev_1a_puro"]   or 0),
            "score_30_7":      float(r["score_30_7"]   or 0),

            # Amostragem
            "n_total":         r["n_total"],
            "n_hit":           r["n_hit"],
            "n_filtros":       r["n_filtros"],
            "filtros":         r["filtros_aprovados"],

            # Dados exclusivos do modo SUPREMO (None se não for FV6)
            "tem_fv6":         bool(r["tem_fv6"]),
            "ev_fv6":          float(r["ev_fv6"]        or 0) if r["ev_fv6"]        else None,
            "wr_1a_fv6":       float(r["wr_1a_fv6"]     or 0) if r["wr_1a_fv6"]     else None,
            "assimetria_1a":   float(r["assimetria_1a"] or 0) if r["assimetria_1a"] else None,
            "stake_leverage":  float(r["stake_leverage"] or 1.0),

            # Controle de operação
            "modo_operacao":   r["modo_operacao"],   # "SEM_GALE" ou "GALE_2"
            "max_gale":        r["max_gale"],         # 0 ou 2
            "sizing_override": float(r["stake_multiplier"]),
            "status":          r["status"],
            "fonte":           "SUPREMO_V1",
        }

    return config


def salvar_config(config: dict):
    """Salva config_supremo.json."""
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
    print(f"[SUPREMO EXPORTER] config_supremo.json salvo: {len(config)} estrategias")
    print(f"[SUPREMO EXPORTER] Caminho: {OUTPUT_PATH}")


def run_supremo_exporter():
    """Ponto de entrada principal."""
    config = exportar_grade_suprema()
    salvar_config(config)

    # Sumário por status
    supremos    = sum(1 for v in config.values() if v["status"] == "SUPREMO")
    aprovados   = sum(1 for v in config.values() if v["status"] == "APROVADO")
    condicionais= sum(1 for v in config.values() if v["status"] == "CONDICIONAL")

    print(f"\n[SUPREMO EXPORTER] ====== SUMARIO ======")
    print(f"  SUPREMO (sem gale):   {supremos}")
    print(f"  APROVADO (gale 2):    {aprovados}")
    print(f"  CONDICIONAL (gale 2): {condicionais}")
    print(f"  TOTAL:                {len(config)}")

    if supremos > 0:
        print(f"\n[SUPREMO EXPORTER] Top 5 SUPREMO por EV flat:")
        tops = [
            (k, v) for k, v in config.items()
            if v["status"] == "SUPREMO"
        ]
        tops.sort(key=lambda x: x[1]["ev_1a_puro"], reverse=True)
        for k, v in tops[:5]:
            print(
                f"  {v['ativo']} {v['hh_mm']} {v['direcao']}"
                f" | EV_flat={v['ev_1a_puro']:+.4f}"
                f" | WR_1a={v['p_win_1a']:.1%}"
                f" | stake={v['stake_leverage']}x"
            )


if __name__ == "__main__":
    run_supremo_exporter()
