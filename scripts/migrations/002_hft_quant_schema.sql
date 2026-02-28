-- Tabela de Inteligência de Curadoria
CREATE SCHEMA IF NOT EXISTS hft_quant;

CREATE TABLE IF NOT EXISTS hft_quant.oracle_results (
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
    UNIQUE(ativo, estrategia) -- Garante apenas 1 registro por par
);
