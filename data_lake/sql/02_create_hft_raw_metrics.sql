-- 02_create_hft_raw_metrics.sql
CREATE TABLE IF NOT EXISTS hft_lake.hft_raw_metrics (
  id              BIGSERIAL PRIMARY KEY,

  -- Identificadores
  ativo           TEXT NOT NULL,    -- "R_10", "R_25", "R_50", "R_75", "R_100"
  hh_mm           TEXT NOT NULL,    -- "00:00" até "23:59"
  direcao         TEXT NOT NULL,    -- "CALL" ou "PUT"

  -- Janela 30 dias (histórico completo)
  n_30d           INT NOT NULL DEFAULT 0,
  win_1a_30d      INT NOT NULL DEFAULT 0,
  win_g1_30d      INT NOT NULL DEFAULT 0,
  win_g2_30d      INT NOT NULL DEFAULT 0,
  hit_30d         INT NOT NULL DEFAULT 0,

  -- Janela 7 dias (recência)
  n_7d            INT NOT NULL DEFAULT 0,
  win_1a_7d       INT NOT NULL DEFAULT 0,
  win_g1_7d       INT NOT NULL DEFAULT 0,
  win_g2_7d       INT NOT NULL DEFAULT 0,
  hit_7d          INT NOT NULL DEFAULT 0,

  -- Janela 3 dias (momentum)
  n_3d            INT NOT NULL DEFAULT 0,
  win_1a_3d       INT NOT NULL DEFAULT 0,
  win_g1_3d       INT NOT NULL DEFAULT 0,
  win_g2_3d       INT NOT NULL DEFAULT 0,
  hit_3d          INT NOT NULL DEFAULT 0,

  -- Controle
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

  -- Chave única: um ativo+horário+direção por upload
  CONSTRAINT hft_raw_metrics_upsert UNIQUE (ativo, hh_mm, direcao)
);

-- Índices para performance das Views
CREATE INDEX IF NOT EXISTS idx_raw_ativo   ON hft_lake.hft_raw_metrics(ativo);
CREATE INDEX IF NOT EXISTS idx_raw_hh_mm  ON hft_lake.hft_raw_metrics(hh_mm);
CREATE INDEX IF NOT EXISTS idx_raw_direcao ON hft_lake.hft_raw_metrics(direcao);
