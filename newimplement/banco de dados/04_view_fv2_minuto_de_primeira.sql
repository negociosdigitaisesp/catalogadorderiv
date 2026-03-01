-- 04_view_fv2_minuto_de_primeira.sql
-- FV2 — Minuto de Primeira
-- Horários onde a primeira entrada já ganha sem depender do Gale.
-- Estratégia mais robusta — baixo drawdown real.

CREATE OR REPLACE VIEW hft_lake.vw_fv2_minuto_de_primeira AS
SELECT
  ativo,
  hh_mm,
  direcao,
  n_30d                                                                              AS n_total,
  ROUND((win_1a_30d::numeric / NULLIF(n_30d,0)), 4)                                AS wr_1a,
  ROUND(((win_1a_30d + win_g1_30d + win_g2_30d)::numeric / NULLIF(n_30d,0)), 4)   AS wr_g2,

  -- EV da primeira entrada pura (payout 85%)
  ROUND(
    ((win_1a_30d::numeric / NULLIF(n_30d,0)) * 0.85) -
    (((n_30d - win_1a_30d)::numeric / NULLIF(n_30d,0)) * 1.0)
  , 4)                                                                               AS ev_1a_puro,

  hit_30d                                                                            AS n_hit,
  'FV2'                                                                              AS filtro

FROM hft_lake.hft_raw_metrics
WHERE
  CASE
    WHEN ativo IN ('R_10','R_25') THEN n_30d >= 20
    ELSE n_30d >= 15
  END
  -- Ganha de primeira na maioria dos ciclos (EV positivo sem Gale)
  AND (win_1a_30d::numeric / NULLIF(n_30d,0)) >= 0.55
  -- WR G2 mínima mantida
  AND ((win_1a_30d + win_g1_30d + win_g2_30d)::numeric / NULLIF(n_30d,0)) >= 0.88

ORDER BY wr_1a DESC;
