-- Migração para o schema public (Supabase Default)
-- Prefixo 'hft_' para evitar conflitos

CREATE TABLE IF NOT EXISTS public.hft_oracle_results (
    id BIGSERIAL PRIMARY KEY,
    ativo TEXT NOT NULL,
    estrategia TEXT NOT NULL,
    win_rate DECIMAL NOT NULL,
    n_amostral INTEGER NOT NULL,
    ev_real DECIMAL NOT NULL,
    edge_vs_be DECIMAL NOT NULL,
    status TEXT NOT NULL, -- 'APROVADO', 'CONDICIONAL', 'REPROVADO'
    config_otimizada JSONB, -- { "z_score": 2.8, "expiracao": 300 }
    last_update TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(ativo, estrategia)
);

-- Tabela de Sinais (VPS Sniper)
CREATE TABLE IF NOT EXISTS public.hft_catalogo_estrategias (
    id BIGSERIAL PRIMARY KEY,
    ativo TEXT NOT NULL,
    estrategia TEXT NOT NULL,
    direcao TEXT NOT NULL,
    p_win_historica DECIMAL NOT NULL,
    status TEXT NOT NULL, -- 'PRE_SIGNAL', 'CONFIRMED', 'CANCELED', 'WIN', 'LOSS'
    timestamp_sinal BIGINT NOT NULL,
    contexto JSONB, -- { "z_score_atual": 3.2, "n_amostral": 450 }
    created_at TIMESTAMPTZ DEFAULT NOW()
);
