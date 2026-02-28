-- Migração 004: Corrige colunas faltantes em hft_oracle_results e cria agent_cycles

-- 1. Adiciona colunas faltantes em hft_oracle_results (somente se não existirem)
ALTER TABLE public.hft_oracle_results
    ADD COLUMN IF NOT EXISTS strategy_id     TEXT,
    ADD COLUMN IF NOT EXISTS sharpe          DECIMAL,
    ADD COLUMN IF NOT EXISTS p_value         DECIMAL,
    ADD COLUMN IF NOT EXISTS sizing_override DECIMAL,
    ADD COLUMN IF NOT EXISTS valid_until     BIGINT;

-- 2. Altera a constraint UNIQUE para incluir strategy_id (necessário para o upsert funcionar)
-- Primeiro remove a constraint antiga se existir
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'hft_oracle_results_ativo_estrategia_key'
    ) THEN
        ALTER TABLE public.hft_oracle_results
            DROP CONSTRAINT hft_oracle_results_ativo_estrategia_key;
    END IF;
END
$$;

ALTER TABLE public.hft_oracle_results
    ADD CONSTRAINT hft_oracle_results_upsert_key
    UNIQUE (ativo, estrategia, strategy_id);

-- 3. Cria a tabela agent_cycles (histórico dos ciclos do agente)
CREATE TABLE IF NOT EXISTS public.agent_cycles (
    id                    BIGSERIAL PRIMARY KEY,
    started_at            BIGINT NOT NULL,
    duration_seconds      DECIMAL,
    registros_carregados  INTEGER DEFAULT 0,
    hipoteses_geradas     INTEGER DEFAULT 0,
    padroes_minerados     INTEGER DEFAULT 0,
    aprovadas             INTEGER DEFAULT 0,
    condicionais          INTEGER DEFAULT 0,
    reprovadas            INTEGER DEFAULT 0,
    estrategias_escritas  INTEGER DEFAULT 0,
    created_at            TIMESTAMPTZ DEFAULT NOW()
);
