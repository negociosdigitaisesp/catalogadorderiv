-- =============================================================================
-- 09_view_fv6_minuto_supremo.sql
-- =============================================================================
-- ISOLADO: Este arquivo NÃO modifica nada existente.
-- Lê apenas: hft_lake.hft_raw_metrics (tabela mãe já existente)
-- Cria apenas: hft_lake.vw_fv6_minuto_supremo (view nova)
--
-- OBJETIVO: Modo Alavancagem Sem Gale
--   Isola horários onde a PRIMEIRA ENTRADA já ganha com frequência
--   suficiente para operar SEM martingale e COM stake elevado.
--
-- MATEMÁTICA:
--   EV_flat = WR_1a × 0.85 − (1 − WR_1a) × 1.0
--   Break-even: WR_1a = 54.05%
--   Target mínimo aqui: WR_1a >= 68% → EV = +25.8% por trade
--
-- CRITÉRIOS (todos obrigatórios):
--   [1] n_30d      >= 8          amostra mínima (calibrado para ~13 dias de histórico)
--   [2] WR_1a_30d  >= 68%        EV flat = +25.8% mínimo
--   [3] hit_30d    <= 2          proxy anti-sequência (máx ~1 hit/quinzena)
--   [4] ev_1a_puro > 0.10        EV positivo robusto no flat bet
--   [5] assimetria_1a >= 0.10    direção escolhida domina a oposta em 10pp+
--
-- NOTA: Janelas 7d e 3d removidas — n_7d = 0 para 14.400/14.443 registros
-- porque o catalog.db foi baixado há mais de 7 dias (janela recente vazia).
-- Quando o pipeline rodar com dados frescos, reativar critérios [4] e [6]
-- do design original (WR_1a_7d >= 65%, hit_7d <= 1).
-- N mínimo = 8 porque histórico atual tem média 12.6 dias.
-- =============================================================================

CREATE OR REPLACE VIEW hft_lake.vw_fv6_minuto_supremo AS

WITH base_fv6 AS (
  SELECT
    ativo,
    hh_mm,
    direcao,
    n_30d,

    -- Win Rate primeira entrada (janela 30d — única confiável com dados atuais)
    ROUND((win_1a_30d::numeric / NULLIF(n_30d, 0)), 4)                               AS wr_1a_30d,

    -- Win Rate G2 (informativo — não é o critério de entrada neste filtro)
    ROUND(((win_1a_30d + win_g1_30d + win_g2_30d)::numeric / NULLIF(n_30d, 0)), 4)  AS wr_g2_30d,

    -- EV do flat bet sem gale
    -- Fórmula: WR_1a × 0.85 − (1 − WR_1a) × 1.0
    ROUND(
      (win_1a_30d::numeric           / NULLIF(n_30d, 0)) * 0.85 -
      ((n_30d - win_1a_30d)::numeric / NULLIF(n_30d, 0)) * 1.0
    , 4)                                                                              AS ev_1a_puro,

    hit_30d,
    ROUND(hit_30d::numeric / 4.0, 2)                                                 AS hits_por_semana

  FROM hft_lake.hft_raw_metrics
  WHERE
    n_30d >= 8                                                                  -- [1]
    AND (win_1a_30d::numeric / NULLIF(n_30d, 0)) >= 0.68                       -- [2]
    AND hit_30d <= 2                                                            -- [3]
    AND (                                                                       -- [4]
      (win_1a_30d::numeric           / NULLIF(n_30d, 0)) * 0.85 -
      ((n_30d - win_1a_30d)::numeric / NULLIF(n_30d, 0)) * 1.0
    ) > 0.10
),

-- Assimetria direcional: compara CALL vs PUT no mesmo horário
com_assimetria AS (
  SELECT
    a.*,
    b.wr_1a_30d                                                AS wr_1a_oposto,
    ROUND(a.wr_1a_30d - COALESCE(b.wr_1a_30d, 0.5), 4)        AS assimetria_1a
  FROM base_fv6 a
  LEFT JOIN base_fv6 b
    ON  a.ativo    = b.ativo
    AND a.hh_mm    = b.hh_mm
    AND a.direcao != b.direcao
)

SELECT
  ativo,
  hh_mm,
  direcao,
  n_30d                                              AS n_total,

  -- Métricas de 1ª entrada (as que importam sem gale)
  wr_1a_30d,
  ev_1a_puro,

  -- G2 informativo
  wr_g2_30d,

  -- Assimetria direcional
  wr_1a_oposto,
  assimetria_1a,

  -- Controle de risco
  hit_30d                                            AS n_hit_total,
  hits_por_semana,

  -- Stake sugerido para modo alavancagem
  -- EV > 0.25 → 2.0x | EV > 0.20 → 1.5x | resto → 1.2x
  CASE
    WHEN ev_1a_puro > 0.25 THEN 2.0
    WHEN ev_1a_puro > 0.20 THEN 1.5
    ELSE                        1.2
  END                                                AS stake_leverage,

  'FV6'                                              AS filtro,
  TRUE                                               AS modo_sem_gale,
  0                                                  AS max_gale_permitido

FROM com_assimetria
WHERE assimetria_1a >= 0.10                                                     -- [9]

ORDER BY ev_1a_puro DESC, wr_1a_30d DESC;
