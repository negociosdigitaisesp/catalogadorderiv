-- Migração 005: Reestrutura hft_oracle_results — Transparência por Ativo
-- Adiciona colunas explícitas de auditoria de Gale e categorização de variação.
-- Antes: contagens reais ficavam escondidas dentro do JSONB config_otimizada.
-- Depois: colunas planas consultáveis direto por ativo.

-- 1. Adiciona colunas de auditoria
ALTER TABLE public.hft_oracle_results
  ADD COLUMN IF NOT EXISTS variacao_estrategia TEXT,     -- V1, V2, V3, V4...
  ADD COLUMN IF NOT EXISTS n_win_1a  INTEGER DEFAULT 0,  -- Wins de 1ª entrada
  ADD COLUMN IF NOT EXISTS n_win_g1  INTEGER DEFAULT 0,  -- Wins no Gale 1
  ADD COLUMN IF NOT EXISTS n_win_g2  INTEGER DEFAULT 0,  -- Wins no Gale 2
  ADD COLUMN IF NOT EXISTS n_hit     INTEGER DEFAULT 0,  -- Perdas totais (Hit)
  ADD COLUMN IF NOT EXISTS n_total   INTEGER DEFAULT 0;  -- Total de amostras

-- 2. Índice para organizar por ativo → win_rate decrescente
CREATE INDEX IF NOT EXISTS idx_oracle_results_ativo
  ON public.hft_oracle_results (ativo, win_rate DESC);

-- 3. Limpa dados antigos (schema Z-Score) para o Oráculo preencher limpo
TRUNCATE TABLE public.hft_oracle_results;
