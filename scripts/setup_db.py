"""
scripts/setup_db.py — Criação de tabelas no Supabase

Executa via psycopg2 com conexão direta ao PostgreSQL.
Cria a tabela catalogo_estrategias conforme o schema exato da Seção 6 do PRD.
Usa IF NOT EXISTS — seguro de rodar múltiplas vezes.

Uso:
    python scripts/setup_db.py
"""

import os
import sys
import psycopg2
from dotenv import load_dotenv

load_dotenv()

# ─── SQL do PRD Seção 6 (schema exato) ────────────────────────────────────────

CREATE_CATALOGO_ESTRATEGIAS = """
CREATE TABLE IF NOT EXISTS catalogo_estrategias (
  id              BIGSERIAL PRIMARY KEY,
  ativo           TEXT NOT NULL,
  estrategia      TEXT NOT NULL,
  direcao         TEXT NOT NULL,
  p_win_historica FLOAT NOT NULL,
  status          TEXT NOT NULL,
  timestamp_sinal BIGINT NOT NULL,
  contexto        JSONB,
  created_at      TIMESTAMPTZ DEFAULT NOW()
);
"""

# Índices para queries rápidas no Frontend e no Sniper
CREATE_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_catalogo_ativo
    ON catalogo_estrategias (ativo);

CREATE INDEX IF NOT EXISTS idx_catalogo_status
    ON catalogo_estrategias (status);

CREATE INDEX IF NOT EXISTS idx_catalogo_timestamp
    ON catalogo_estrategias (timestamp_sinal DESC);

CREATE INDEX IF NOT EXISTS idx_catalogo_ativo_status
    ON catalogo_estrategias (ativo, status);
"""

# Constraint para garantir valores válidos nos campos enumerados
ADD_CONSTRAINTS = """
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'chk_status_values'
    ) THEN
        ALTER TABLE catalogo_estrategias
        ADD CONSTRAINT chk_status_values
        CHECK (status IN ('PRE_SIGNAL', 'CONFIRMED', 'CANCELED', 'WIN', 'LOSS'));
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'chk_direcao_values'
    ) THEN
        ALTER TABLE catalogo_estrategias
        ADD CONSTRAINT chk_direcao_values
        CHECK (direcao IN ('CALL', 'PUT'));
    END IF;
END $$;
"""


def setup_database() -> None:
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        print("[ERROR] DATABASE_URL não encontrada no .env")
        sys.exit(1)

    print(f"[SETUP] Conectando ao PostgreSQL...")
    try:
        conn = psycopg2.connect(db_url, connect_timeout=10)
        conn.autocommit = True
        cur = conn.cursor()

        print("[SETUP] Criando tabela catalogo_estrategias...")
        cur.execute(CREATE_CATALOGO_ESTRATEGIAS)
        print("  [OK] tabela criada (ou ja existia)")

        print("[SETUP] Criando indices...")
        cur.execute(CREATE_INDEXES)
        print("  [OK] indices criados")

        print("[SETUP] Adicionando constraints de validacao...")
        cur.execute(ADD_CONSTRAINTS)
        print("  [OK] constraints aplicadas")

        # Verificar resultado
        cur.execute("""
            SELECT column_name, data_type, is_nullable
            FROM information_schema.columns
            WHERE table_name = 'catalogo_estrategias'
            ORDER BY ordinal_position;
        """)
        cols = cur.fetchall()

        print("\n[SETUP] Schema criado com sucesso:")
        print(f"  {'Coluna':<20} {'Tipo':<20} {'Nullable'}")
        print(f"  {'-'*20} {'-'*20} {'-'*8}")
        for col_name, col_type, nullable in cols:
            print(f"  {col_name:<20} {col_type:<20} {nullable}")

        cur.close()
        conn.close()
        print("\n[SETUP] SUCESSO - Banco de dados configurado!")

    except psycopg2.OperationalError as e:
        print(f"[ERROR] Falha de conexão: {e}")
        sys.exit(1)
    except psycopg2.Error as e:
        print(f"[ERROR] Erro PostgreSQL: {e}")
        sys.exit(1)


if __name__ == "__main__":
    setup_database()
