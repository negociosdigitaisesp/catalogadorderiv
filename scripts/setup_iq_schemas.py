"""
setup_iq_schemas.py — Creates iq_lake and iq_quant schemas in Supabase

Executes via psycopg2 (direct SQL). Run once.
"""

import psycopg2

DB_URL = "postgresql://postgres:1CIwYGQv09MUQA@db.ypqekkkrfklaqlzhkbwg.supabase.co:5432/postgres"

SQL = """
-- ══════════════════════════════════════════════════════════
-- SCHEMA 1: iq_lake (espelho do hft_lake para IQ Option)
-- ══════════════════════════════════════════════════════════
CREATE SCHEMA IF NOT EXISTS iq_lake;

CREATE TABLE IF NOT EXISTS iq_lake.iq_raw_metrics (
  id              BIGSERIAL PRIMARY KEY,

  -- Identificadores
  ativo           TEXT NOT NULL,
  hh_mm           TEXT NOT NULL,
  direcao         TEXT NOT NULL,

  -- Janela 30 dias
  n_30d           INT NOT NULL DEFAULT 0,
  win_1a_30d      INT NOT NULL DEFAULT 0,
  win_g1_30d      INT NOT NULL DEFAULT 0,
  win_g2_30d      INT NOT NULL DEFAULT 0,
  hit_30d         INT NOT NULL DEFAULT 0,

  -- Janela 7 dias
  n_7d            INT NOT NULL DEFAULT 0,
  win_1a_7d       INT NOT NULL DEFAULT 0,
  win_g1_7d       INT NOT NULL DEFAULT 0,
  win_g2_7d       INT NOT NULL DEFAULT 0,
  hit_7d          INT NOT NULL DEFAULT 0,

  -- Janela 3 dias
  n_3d            INT NOT NULL DEFAULT 0,
  win_1a_3d       INT NOT NULL DEFAULT 0,
  win_g1_3d       INT NOT NULL DEFAULT 0,
  win_g2_3d       INT NOT NULL DEFAULT 0,
  hit_3d          INT NOT NULL DEFAULT 0,

  -- Controle
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

  CONSTRAINT iq_raw_metrics_upsert UNIQUE (ativo, hh_mm, direcao)
);

CREATE INDEX IF NOT EXISTS idx_iq_raw_ativo   ON iq_lake.iq_raw_metrics(ativo);
CREATE INDEX IF NOT EXISTS idx_iq_raw_hh_mm   ON iq_lake.iq_raw_metrics(hh_mm);
CREATE INDEX IF NOT EXISTS idx_iq_raw_direcao  ON iq_lake.iq_raw_metrics(direcao);


-- ══════════════════════════════════════════════════════════
-- SCHEMA 2: iq_quant (espelho do hft_quant + public.hft_*)
-- ══════════════════════════════════════════════════════════
CREATE SCHEMA IF NOT EXISTS iq_quant;

-- Oracle Results (espelho de hft_oracle_results)
CREATE TABLE IF NOT EXISTS iq_quant.oracle_results (
    id              BIGSERIAL PRIMARY KEY,
    ativo           TEXT NOT NULL,
    estrategia      TEXT NOT NULL,
    win_rate        DECIMAL NOT NULL,
    n_amostral      INTEGER NOT NULL,
    ev_real         DECIMAL NOT NULL,
    edge_vs_be      DECIMAL NOT NULL,
    status          TEXT NOT NULL,
    config_otimizada JSONB,
    last_update     TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(ativo, estrategia)
);

-- Signals (espelho de hft_catalogo_estrategias)
CREATE TABLE IF NOT EXISTS iq_quant.signals (
    id              BIGSERIAL PRIMARY KEY,
    ativo           TEXT NOT NULL,
    estrategia      TEXT NOT NULL,
    direcao         TEXT NOT NULL,
    p_win_historica DECIMAL NOT NULL,
    status          TEXT NOT NULL,
    timestamp_sinal BIGINT NOT NULL,
    contexto        JSONB,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);


-- ══════════════════════════════════════════════════════════
-- REPLICA IDENTITY FULL (iq_quant tables)
-- ══════════════════════════════════════════════════════════
ALTER TABLE iq_quant.oracle_results REPLICA IDENTITY FULL;
ALTER TABLE iq_quant.signals        REPLICA IDENTITY FULL;


-- ══════════════════════════════════════════════════════════
-- REALTIME (iq_quant tables)
-- ══════════════════════════════════════════════════════════
ALTER PUBLICATION supabase_realtime ADD TABLE iq_quant.oracle_results;
ALTER PUBLICATION supabase_realtime ADD TABLE iq_quant.signals;
"""

def main():
    print("Connecting to Supabase...")
    conn = psycopg2.connect(DB_URL)
    conn.autocommit = True
    cur = conn.cursor()

    print("Executing SQL...")
    try:
        cur.execute(SQL)
        print("✅ Schemas iq_lake and iq_quant created successfully!")
    except Exception as e:
        print(f"Error: {e}")
        # Try individual statements if batch fails
        conn.rollback()
        statements = [s.strip() for s in SQL.split(';') if s.strip() and not s.strip().startswith('--')]
        for i, stmt in enumerate(statements, 1):
            try:
                cur.execute(stmt + ';')
                print(f"  [{i}/{len(statements)}] OK")
            except Exception as e2:
                print(f"  [{i}/{len(statements)}] WARN: {e2}")
    finally:
        cur.close()
        conn.close()

    # Verify
    print("\nVerifying schemas...")
    conn = psycopg2.connect(DB_URL)
    conn.autocommit = True
    cur = conn.cursor()

    cur.execute("""
        SELECT schemaname, tablename
        FROM pg_tables
        WHERE schemaname IN ('iq_lake', 'iq_quant')
        ORDER BY schemaname, tablename;
    """)
    rows = cur.fetchall()
    for schema, table in rows:
        print(f"  ✅ {schema}.{table}")

    if not rows:
        print("  ❌ No tables found!")

    cur.close()
    conn.close()

if __name__ == "__main__":
    main()
