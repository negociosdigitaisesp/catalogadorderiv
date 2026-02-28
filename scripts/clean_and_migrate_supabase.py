"""
scripts/clean_and_migrate_supabase.py
======================================
Auditoria de Integridade Estatistica — Limpeza e Migracao do Supabase

OPERACOES:
  1. Self-diagnosis: imprime contagem/distribuicao dos dados atuais
  2. Adiciona colunas novas (n_win_1a, n_win_g1, n_win_g2, n_hit) via ALTER TABLE
  3. Limpa registros Z-Score antigos (sem strategy_id valido de Grade)
  4. Confirma schema final

EXECUCAO:
  python scripts/clean_and_migrate_supabase.py --diagnose        # so relatorio
  python scripts/clean_and_migrate_supabase.py --migrate         # aplica DDL
  python scripts/clean_and_migrate_supabase.py --clean-zscores   # remove Z-Score
  python scripts/clean_and_migrate_supabase.py --full            # tudo

AVISO: --clean-zscores e --full sao destrutivos. Confirme antes de executar.
"""

import argparse
import os
import sys

from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")
DATABASE_URL = os.getenv("DATABASE_URL", "")


# ── DDL para novas colunas ────────────────────────────────────────────────────
DDL_ADD_COLUMNS = """
-- Adiciona colunas de contagem real (transparencia estatistica)
-- Seguro de executar multiplas vezes (IF NOT EXISTS)
ALTER TABLE hft_oracle_results
  ADD COLUMN IF NOT EXISTS n_win_1a  INTEGER DEFAULT 0,
  ADD COLUMN IF NOT EXISTS n_win_g1  INTEGER DEFAULT 0,
  ADD COLUMN IF NOT EXISTS n_win_g2  INTEGER DEFAULT 0,
  ADD COLUMN IF NOT EXISTS n_hit     INTEGER DEFAULT 0;

-- Corrige n_amostral = 0 hardcoded: torna-o NOT NULL com default 0
-- (os registros novos ja terao o valor real)
ALTER TABLE hft_oracle_results
  ALTER COLUMN n_amostral SET DEFAULT 0;

COMMENT ON COLUMN hft_oracle_results.n_amostral IS
  'Numero total de ciclos Gale2 completos analisados (antes era 0 hardcoded)';
COMMENT ON COLUMN hft_oracle_results.n_win_1a IS
  'Quantas vezes ganhou na 1a entrada (sem precisar de gale)';
COMMENT ON COLUMN hft_oracle_results.n_win_g1 IS
  'Quantas vezes ganhou no Gale 1 (perdeu 1a, ganhou G1)';
COMMENT ON COLUMN hft_oracle_results.n_win_g2 IS
  'Quantas vezes ganhou no Gale 2 (perdeu 1a+G1, ganhou G2)';
COMMENT ON COLUMN hft_oracle_results.n_hit IS
  'Quantas vezes perdeu o ciclo completo (loss total)';
"""

# ── Identifica registros Z-Score (sem strategy_id tipo Grade Horaria) ─────────
SQL_DIAGNOSE = """
SELECT
  COUNT(*)                                             AS total,
  COUNT(CASE WHEN strategy_id LIKE 'T%_G2'    THEN 1 END) AS grade_horaria,
  COUNT(CASE WHEN strategy_id NOT LIKE 'T%_G2'
              OR strategy_id IS NULL           THEN 1 END) AS z_score_legacy,
  COUNT(CASE WHEN n_amostral = 0              THEN 1 END) AS n_amostral_zero,
  ROUND(AVG(win_rate)::NUMERIC, 4)                     AS avg_win_rate,
  ROUND(MIN(win_rate)::NUMERIC, 4)                     AS min_win_rate,
  ROUND(MAX(win_rate)::NUMERIC, 4)                     AS max_win_rate,
  COUNT(DISTINCT ativo)                                AS ativos_distintos,
  COUNT(DISTINCT status)                               AS status_distintos
FROM hft_oracle_results;
"""

SQL_STATUS_DIST = """
SELECT status, COUNT(*) as n
FROM hft_oracle_results
GROUP BY status ORDER BY n DESC;
"""

SQL_WIN_RATE_HIST = """
SELECT
  CASE
    WHEN win_rate >= 0.95 THEN '95-100%'
    WHEN win_rate >= 0.90 THEN '90-95%'
    WHEN win_rate >= 0.85 THEN '85-90%'
    WHEN win_rate >= 0.50 THEN '50-85%'
    ELSE '<50%'
  END AS faixa,
  COUNT(*) AS n
FROM hft_oracle_results
GROUP BY 1 ORDER BY 1 DESC;
"""

# ── Deleta apenas registros Z-Score (strategy_id nao comeca com T ou nulo) ───
SQL_DELETE_ZSCORES = """
DELETE FROM hft_oracle_results
WHERE strategy_id IS NULL
   OR strategy_id NOT LIKE 'T%_G2';
"""

# ── Reset completo (use com cautela) ─────────────────────────────────────────
SQL_TRUNCATE = "TRUNCATE TABLE hft_oracle_results;"


def _get_psycopg2_conn():
    """Conecta via psycopg2 (DATABASE_URL)."""
    try:
        import psycopg2
    except ImportError:
        print("[ERRO] psycopg2 nao instalado: pip install psycopg2-binary")
        sys.exit(1)

    if not DATABASE_URL:
        print("[ERRO] DATABASE_URL nao configurado no .env")
        sys.exit(1)

    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = False
    return conn


def cmd_diagnose():
    """Imprime diagnostico do estado atual da tabela."""
    print("=" * 60)
    print("DIAGNOSTICO: hft_oracle_results")
    print("=" * 60)

    conn = _get_psycopg2_conn()
    cur  = conn.cursor()

    print("\n[1] Resumo geral:")
    cur.execute(SQL_DIAGNOSE)
    row = cur.fetchone()
    cols = [d[0] for d in cur.description]
    for col, val in zip(cols, row):
        print(f"    {col:25s} = {val}")

    print("\n[2] Distribuicao por status:")
    cur.execute(SQL_STATUS_DIST)
    for status, n in cur.fetchall():
        print(f"    {status:15s}: {n}")

    print("\n[3] Distribuicao de win_rate:")
    cur.execute(SQL_WIN_RATE_HIST)
    for faixa, n in cur.fetchall():
        print(f"    {faixa:12s}: {n}")

    print()
    print("INTERPRETACAO:")
    print("  - 'grade_horaria' = registros novos (strategy_id tipo T0000_SEG_BOOM_G2)")
    print("  - 'z_score_legacy' = registros antigos (win_rate ~0.50, N pequeno)")
    print("  - 'n_amostral_zero' = bug corrigido — eram todos os novos registros")
    print()

    cur.close()
    conn.close()


def cmd_migrate():
    """Aplica DDL para adicionar colunas de contagem."""
    print("=" * 60)
    print("MIGRACAO: Adicionando colunas n_win_1a/g1/g2/hit")
    print("=" * 60)

    conn = _get_psycopg2_conn()
    cur  = conn.cursor()

    try:
        cur.execute(DDL_ADD_COLUMNS)
        conn.commit()
        print("[OK] Colunas adicionadas com sucesso.")
        print("     n_win_1a, n_win_g1, n_win_g2, n_hit — DEFAULT 0")
        print("     Registros futuros terao os valores reais preenchidos.")
    except Exception as exc:
        conn.rollback()
        print(f"[ERRO] Falha na migracao: {exc}")
    finally:
        cur.close()
        conn.close()


def cmd_clean_zscores():
    """Remove registros Z-Score antigos (sem strategy_id de Grade Horaria)."""
    conn = _get_psycopg2_conn()
    cur  = conn.cursor()

    # Conta antes
    cur.execute("SELECT COUNT(*) FROM hft_oracle_results WHERE strategy_id NOT LIKE 'T%%_G2' OR strategy_id IS NULL;")
    n_before = cur.fetchone()[0]

    print("=" * 60)
    print(f"LIMPEZA: {n_before} registros Z-Score serao removidos")
    print("=" * 60)

    if n_before == 0:
        print("[OK] Nenhum registro Z-Score encontrado. Nada a fazer.")
        cur.close()
        conn.close()
        return

    resposta = input(f"Confirmar remocao de {n_before} registros? [sim/nao]: ").strip().lower()
    if resposta not in ("sim", "s"):
        print("[CANCELADO] Operacao abortada pelo usuario.")
        cur.close()
        conn.close()
        return

    try:
        cur.execute(SQL_DELETE_ZSCORES)
        n_deleted = cur.rowcount
        conn.commit()
        print(f"[OK] {n_deleted} registros Z-Score removidos.")
        print("     A tabela agora contem apenas estrategias de Grade Horaria.")
    except Exception as exc:
        conn.rollback()
        print(f"[ERRO] Falha na limpeza: {exc}")
    finally:
        cur.close()
        conn.close()


def cmd_truncate():
    """Trunca TODA a tabela (reset limpo para novo ciclo)."""
    conn = _get_psycopg2_conn()
    cur  = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM hft_oracle_results;")
    n_total = cur.fetchone()[0]

    print("=" * 60)
    print(f"TRUNCATE: {n_total} registros TODOS serao removidos")
    print("=" * 60)

    resposta = input("ATENCAO: isso apaga TUDO. Confirmar? [sim/nao]: ").strip().lower()
    if resposta not in ("sim", "s"):
        print("[CANCELADO]")
        cur.close()
        conn.close()
        return

    try:
        cur.execute(SQL_TRUNCATE)
        conn.commit()
        print(f"[OK] Tabela truncada. {n_total} registros removidos.")
        print("     Execute o agent_discovery.py para repopular com dados corretos.")
    except Exception as exc:
        conn.rollback()
        print(f"[ERRO] {exc}")
    finally:
        cur.close()
        conn.close()


def main():
    parser = argparse.ArgumentParser(
        description="Auditoria e migracao do hft_oracle_results"
    )
    parser.add_argument("--diagnose",     action="store_true", help="Imprime diagnostico")
    parser.add_argument("--migrate",      action="store_true", help="Aplica DDL (ADD COLUMN)")
    parser.add_argument("--clean-zscores", action="store_true", help="Remove registros Z-Score antigos")
    parser.add_argument("--truncate",     action="store_true", help="Trunca a tabela inteira (reset)")
    parser.add_argument("--full",         action="store_true", help="diagnose + migrate + clean-zscores")

    args = parser.parse_args()

    if args.full:
        cmd_diagnose()
        cmd_migrate()
        cmd_clean_zscores()
        return

    if args.diagnose:
        cmd_diagnose()

    if args.migrate:
        cmd_migrate()

    if args.clean_zscores:
        cmd_clean_zscores()

    if args.truncate:
        cmd_truncate()

    if not any(vars(args).values()):
        parser.print_help()


if __name__ == "__main__":
    main()
