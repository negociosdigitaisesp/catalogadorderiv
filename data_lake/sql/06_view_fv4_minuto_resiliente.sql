-- 06_view_fv4_minuto_resiliente.sql
-- FV4 — Minuto Resiliente (Proteção de Sequência)
-- Horários que erram isolado — nunca em sequência.
-- Protege a banca de drawdowns concentrados.

CREATE OR REPLACE VIEW hft_lake.vw_fv4_minuto_resiliente AS
SELECT
  ativo,
  hh_mm,
  direcao,
  n_30d                                                                              AS n_total,
  ROUND(((win_1a_30d + win_g1_30d + win_g2_30d)::numeric / NULLIF(n_30d,0)), 4)   AS wr_g2,
  hit_30d                                                                            AS n_hit_total,

  -- Hits por semana (média)
  ROUND(hit_30d::numeric / 4.0, 2)                                                  AS hits_por_semana,

  -- EV Gale 2
  ROUND(
    (((win_1a_30d + win_g1_30d + win_g2_30d)::numeric / NULLIF(n_30d,0)) * 0.85) -
    ((hit_30d::numeric / NULLIF(n_30d,0)) * 8.2)
  , 4)                                                                               AS ev_g2,

  'FV4'                                                                              AS filtro

FROM hft_lake.hft_raw_metrics
WHERE
  CASE
    WHEN ativo IN ('R_10','R_25') THEN n_30d >= 20
    ELSE n_30d >= 15
  END
  AND ((win_1a_30d + win_g1_30d + win_g2_30d)::numeric / NULLIF(n_30d,0)) >= 0.88
  -- Máximo 1 hit por semana em média (resiliente)
  AND (hit_30d::numeric / 4.0) <= 1.0
  -- Sem hit nos últimos 3 dias (não está em sequência ruim agora)
  AND hit_3d = 0

ORDER BY hits_por_semana ASC, wr_g2 DESC;
