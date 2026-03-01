-- 03_view_fv1_minuto_solido.sql
-- FV1 — Minuto Sólido (Substituto da V4)
-- Horários que ganham consistentemente nos 30 dias E confirmam nos últimos 7.
-- Score ponderado 60/40. EV positivo obrigatório.

CREATE OR REPLACE VIEW hft_lake.vw_fv1_minuto_solido AS
SELECT
  ativo,
  hh_mm,
  direcao,
  n_30d                                                                              AS n_total,

  -- Win Rates calculadas
  ROUND((win_1a_30d::numeric / NULLIF(n_30d,0)), 4)                                AS wr_1a_30d,
  ROUND(((win_1a_30d + win_g1_30d + win_g2_30d)::numeric / NULLIF(n_30d,0)), 4)   AS wr_g2_30d,
  ROUND(((win_1a_7d  + win_g1_7d  + win_g2_7d )::numeric / NULLIF(n_7d, 0)), 4)   AS wr_g2_7d,

  -- Score ponderado 60/40
  ROUND(
    (((win_1a_30d + win_g1_30d + win_g2_30d)::numeric / NULLIF(n_30d,0)) * 0.6) +
    (((win_1a_7d  + win_g1_7d  + win_g2_7d )::numeric / NULLIF(n_7d, 0)) * 0.4)
  , 4)                                                                               AS score_30_7,

  -- EV Gale 2 (payout 85%, custo hit = 8.2 unidades)
  ROUND(
    (((win_1a_30d + win_g1_30d + win_g2_30d)::numeric / NULLIF(n_30d,0)) * 0.85) -
    ((hit_30d::numeric / NULLIF(n_30d,0)) * 8.2)
  , 4)                                                                               AS ev_g2,

  hit_30d                                                                            AS n_hit,
  'FV1'                                                                              AS filtro

FROM hft_lake.hft_raw_metrics
WHERE
  -- N mínimo por grupo de volatilidade
  CASE
    WHEN ativo IN ('R_10','R_25') THEN n_30d >= 20
    ELSE n_30d >= 15
  END
  -- WR G2 mínima (break-even de segurança)
  AND ((win_1a_30d + win_g1_30d + win_g2_30d)::numeric / NULLIF(n_30d,0)) >= 0.88
  -- EV positivo obrigatório
  AND (
    (((win_1a_30d + win_g1_30d + win_g2_30d)::numeric / NULLIF(n_30d,0)) * 0.85) -
    ((hit_30d::numeric / NULLIF(n_30d,0)) * 8.2)
  ) > 0.0

ORDER BY score_30_7 DESC;
