-- 05_view_fv3_minuto_quente.sql
-- FV3 — Minuto Quente (Momentum 3 Dias)
-- Horários em ciclo ativo agora. Captura o padrão algorítmico corrente.

CREATE OR REPLACE VIEW hft_lake.vw_fv3_minuto_quente AS
SELECT
  ativo,
  hh_mm,
  direcao,
  n_30d                                                                              AS n_total,
  n_3d                                                                               AS n_recente,
  ROUND(((win_1a_3d + win_g1_3d + win_g2_3d)::numeric / NULLIF(n_3d,0)), 4)       AS wr_g2_3d,
  ROUND(((win_1a_30d + win_g1_30d + win_g2_30d)::numeric / NULLIF(n_30d,0)), 4)   AS wr_g2_30d,
  hit_3d                                                                             AS n_hit_recente,
  'FV3'                                                                              AS filtro

FROM hft_lake.hft_raw_metrics
WHERE
  -- N mínimo no histórico (base estatística)
  CASE
    WHEN ativo IN ('R_10','R_25') THEN n_30d >= 20
    ELSE n_30d >= 15
  END
  -- N mínimo nos últimos 3 dias (precisa ter ocorrido)
  AND n_3d >= 2
  -- Quente agora: WR G2 dos últimos 3 dias acima de 85%
  AND ((win_1a_3d + win_g1_3d + win_g2_3d)::numeric / NULLIF(n_3d,0)) >= 0.85
  -- Sem hit nos últimos 3 dias (ciclo limpo)
  AND hit_3d = 0

ORDER BY wr_g2_3d DESC, wr_g2_30d DESC;
