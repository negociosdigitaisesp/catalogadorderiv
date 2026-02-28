"""
Script de migração 005: Reestrutura hft_oracle_results
Adiciona colunas de auditoria (variacao, n_win_1a, n_win_g1, n_win_g2, n_hit, n_total)
+ índice por ativo + TRUNCATE de dados antigos.
"""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

SQL = """
-- 1. Colunas de auditoria
ALTER TABLE public.hft_oracle_results
  ADD COLUMN IF NOT EXISTS variacao_estrategia TEXT,
  ADD COLUMN IF NOT EXISTS n_win_1a  INTEGER DEFAULT 0,
  ADD COLUMN IF NOT EXISTS n_win_g1  INTEGER DEFAULT 0,
  ADD COLUMN IF NOT EXISTS n_win_g2  INTEGER DEFAULT 0,
  ADD COLUMN IF NOT EXISTS n_hit     INTEGER DEFAULT 0,
  ADD COLUMN IF NOT EXISTS n_total   INTEGER DEFAULT 0;

-- 2. Índice por ativo
CREATE INDEX IF NOT EXISTS idx_oracle_results_ativo
  ON public.hft_oracle_results (ativo, win_rate DESC);

-- 3. Limpa dados antigos
TRUNCATE TABLE public.hft_oracle_results;
"""


def run_migration():
    try:
        import psycopg2
    except ImportError:
        print("Instalando psycopg2-binary...")
        import subprocess
        subprocess.check_call([sys.executable, "-m", "pip", "install", "psycopg2-binary", "-q"])
        import psycopg2

    conn_str = "postgresql://postgres:1CIwYGQv09MUQA@db.ypqekkkrfklaqlzhkbwg.supabase.co:5432/postgres"
    print("Conectando ao Supabase...")
    try:
        conn = psycopg2.connect(conn_str, sslmode="require")
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute(SQL)
        cur.close()
        conn.close()
        print("✅ Migração 005 aplicada com sucesso!")
        print("   - Colunas adicionadas: variacao_estrategia, n_win_1a, n_win_g1, n_win_g2, n_hit, n_total")
        print("   - Índice criado: idx_oracle_results_ativo (ativo, win_rate DESC)")
        print("   - TRUNCATE: dados antigos limpos")
        return True
    except Exception as e:
        print(f"❌ ERRO: {e}")
        return False


if __name__ == "__main__":
    success = run_migration()
    sys.exit(0 if success else 1)
