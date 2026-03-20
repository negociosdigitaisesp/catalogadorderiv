"""
supremo_runner.py — Orquestrador isolado do Modo Supremo (Sem Gale)

ISOLADO: NÃO toca em nenhum processo ou arquivo existente.

O que faz:
  1. Verifica pré-condições (views FV6 e Grade Suprema existem no Supabase)
  2. Roda supremo_exporter → gera config_supremo.json

O que NÃO faz:
  - Não roda lake_loader   (dados já estão em hft_raw_metrics pelo pipeline normal)
  - Não roda lake_uploader (idem)
  - Não toca em config_lake.json
  - Não toca em config.json
  - Não toca em run_sniper.py

USO:
  # Passo 1: Criar as views no Supabase (apenas uma vez)
  # Copiar e rodar no SQL Editor do Supabase:
  #   data_lake/sql/09_view_fv6_minuto_supremo.sql
  #   data_lake/sql/10_view_grade_suprema.sql
  #
  # Passo 2: Rodar o exporter (sempre que quiser atualizar config_supremo.json)
  python data_lake/supremo_runner.py
"""

import time
import sys
import psycopg2
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://postgres:1CIwYGQv09MUQA@db.ypqekkkrfklaqlzhkbwg.supabase.co:5432/postgres"
)


def verificar_views() -> bool:
    """
    Verifica se as views FV6 e Grade Suprema existem no Supabase.
    Retorna True se tudo OK, False se precisa criar as views primeiro.
    """
    views_necessarias = [
        "vw_fv6_minuto_supremo",
        "vw_grade_suprema",
    ]

    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur  = conn.cursor()
        cur.execute("""
            SELECT table_name
            FROM information_schema.views
            WHERE table_schema = 'hft_lake'
              AND table_name = ANY(%s)
        """, (views_necessarias,))
        encontradas = [r[0] for r in cur.fetchall()]
        cur.close()
        conn.close()
    except Exception as e:
        print(f"[SUPREMO RUNNER] ERRO ao verificar views: {e}")
        return False

    faltando = [v for v in views_necessarias if v not in encontradas]
    if faltando:
        print(f"\n[SUPREMO RUNNER] ATENCAO: Views nao encontradas no Supabase:")
        for v in faltando:
            print(f"  - hft_lake.{v}")
        print(f"\n[SUPREMO RUNNER] Execute no SQL Editor do Supabase:")
        if "vw_fv6_minuto_supremo" in faltando:
            print(f"  data_lake/sql/09_view_fv6_minuto_supremo.sql")
        if "vw_grade_suprema" in faltando:
            print(f"  data_lake/sql/10_view_grade_suprema.sql")
        return False

    print(f"[SUPREMO RUNNER] Views OK: {', '.join(encontradas)}")
    return True


def verificar_dados() -> int:
    """
    Verifica quantos registros existem em hft_raw_metrics.
    O pipeline normal (lake_runner.py) precisa ter rodado antes.
    """
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur  = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM hft_lake.hft_raw_metrics")
        n = cur.fetchone()[0]
        cur.close()
        conn.close()
        return n
    except Exception as e:
        print(f"[SUPREMO RUNNER] ERRO ao verificar dados: {e}")
        return 0


def main():
    inicio = time.time()
    print("\n" + "=" * 60)
    print("  ORACLE QUANT — SUPREMO RUNNER (Modo Sem Gale)")
    print("=" * 60)
    print("  Sistema antigo: INTOCADO")
    print("  config.json:    INTOCADO")
    print("  config_lake.json: INTOCADO")
    print("=" * 60)

    # --- PRE-CHECK 1: Dados existem? ---
    print("\n[SUPREMO RUNNER] Verificando dados em hft_raw_metrics...")
    n_registros = verificar_dados()
    if n_registros == 0:
        print("[SUPREMO RUNNER] ERRO: hft_raw_metrics esta vazia.")
        print("[SUPREMO RUNNER] Rode primeiro: python data_lake/lake_runner.py")
        sys.exit(1)
    print(f"[SUPREMO RUNNER] OK: {n_registros} registros encontrados")

    # --- PRE-CHECK 2: Views existem? ---
    print("\n[SUPREMO RUNNER] Verificando views no Supabase...")
    if not verificar_views():
        print("\n[SUPREMO RUNNER] ABORTADO. Crie as views primeiro (veja instrucoes acima).")
        sys.exit(1)

    # --- EXPORTER ---
    print("\n[SUPREMO RUNNER] === Rodando Supremo Exporter ===")
    from supremo_exporter import run_supremo_exporter
    run_supremo_exporter()

    total = round(time.time() - inicio, 1)
    print(f"\n{'=' * 60}")
    print(f"  SUPREMO RUNNER COMPLETO em {total}s")
    print(f"  Saida: data_lake/config_supremo.json")
    print(f"  Sistema antigo: INTOCADO")
    print(f"{'=' * 60}\n")


if __name__ == "__main__":
    main()
