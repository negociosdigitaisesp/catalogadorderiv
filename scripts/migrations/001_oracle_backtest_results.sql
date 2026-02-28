-- ============================================================
-- Migration: catalog_backtest_results
-- Supabase / PostgreSQL
-- Guarda os resultados de backtest do Oráculo (Camada A)
-- 1 linha por (ativo, estrategia, janela de referência)
-- ============================================================

CREATE TABLE IF NOT EXISTS oracle_backtest_results (
  id              BIGSERIAL PRIMARY KEY,
  ativo           TEXT      NOT NULL,
  estrategia      TEXT      NOT NULL,          -- "Z_SCORE_M1" | "CRASH_DRIFT" | "BOOM_DRIFT" | "GARCH_RANGE"
  z_score_min     FLOAT,                        -- S1 only
  n_amostral      INT       NOT NULL,
  p_win           FLOAT     NOT NULL,
  ev              FLOAT     NOT NULL,
  kelly_quarter   FLOAT     NOT NULL,
  break_even      FLOAT     NOT NULL,
  rating          TEXT      NOT NULL,           -- "APROVADO" | "CONDICIONAL" | "REPROVADO"
  criteria_passed INT       NOT NULL,
  contexto        JSONB,                         -- métricas extras por estratégia
  data_referencia DATE      NOT NULL DEFAULT CURRENT_DATE,
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (ativo, estrategia, data_referencia)   -- permite upsert via ON CONFLICT
);

-- Índice para consultas do Sniper e do Dashboard
CREATE INDEX IF NOT EXISTS idx_oracle_ativo_estrategia
  ON oracle_backtest_results (ativo, estrategia);

-- RLS desabilitado, acesso via service_role no backend
ALTER TABLE oracle_backtest_results DISABLE ROW LEVEL SECURITY;
