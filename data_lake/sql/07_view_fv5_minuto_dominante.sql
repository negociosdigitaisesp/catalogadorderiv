-- 07_view_fv5_minuto_dominante.sql
-- FV5 — Minuto Dominante (Assimetria Direcional)
-- Horários onde CALL domina PUT de forma inequívoca.
-- Vantagem estrutural algorítmica.

CREATE OR REPLACE VIEW hft_lake.vw_fv5_minuto_dominante AS
WITH base AS (
  SELECT
    ativo,
    hh_mm,
    direcao,
    n_30d,
    ROUND(((win_1a_30d + win_g1_30d + win_g2_30d)::numeric / NULLIF(n_30d,0)), 4) AS wr_g2,
    hit_30d
  FROM hft_lake.hft_raw_metrics
  WHERE
    CASE
      WHEN ativo IN ('R_10','R_25') THEN n_30d >= 20
      ELSE n_30d >= 15
    END
    AND ((win_1a_30d + win_g1_30d + win_g2_30d)::numeric / NULLIF(n_30d,0)) >= 0.88
),
comparado AS (
  SELECT
    a.ativo,
    a.hh_mm,
    a.direcao,
    a.n_30d,
    a.wr_g2,
    a.hit_30d,
    b.wr_g2 AS wr_g2_oposto,
    ROUND(a.wr_g2 - COALESCE(b.wr_g2, 0), 4) AS assimetria
  FROM base a
  LEFT JOIN base b
    ON a.ativo = b.ativo
    AND a.hh_mm = b.hh_mm
    AND a.direcao != b.direcao
)
SELECT
  ativo,
  hh_mm,
  direcao,
  n_30d    AS n_total,
  wr_g2,
  wr_g2_oposto,
  assimetria,
  hit_30d  AS n_hit,
  'FV5'    AS filtro
FROM comparado
WHERE
  -- Diferença de pelo menos 15pp entre CALL e PUT no mesmo horário
  assimetria >= 0.15

ORDER BY assimetria DESC, wr_g2 DESC;
