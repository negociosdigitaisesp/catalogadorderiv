-- =============================================================================
-- 10_view_grade_suprema.sql
-- =============================================================================
-- ISOLADO: Este arquivo NÃO modifica nada existente.
-- Lê apenas: hft_lake.vw_fv1 a vw_fv5 (já existentes) + vw_fv6 (nova)
--            hft_lake.hft_raw_metrics (tabela mãe)
-- Cria apenas: hft_lake.vw_grade_suprema (view nova, paralela à vw_grade_unificada)
--
-- DIFERENÇA vs vw_grade_unificada (existente, não tocada):
--   + Inclui FV6 (Minuto Supremo)
--   + Novo status "SUPREMO" (acima de APROVADO)
--   + Campo modo_operacao ("SEM_GALE" ou "GALE_2")
--   + Campo max_gale (0 para SUPREMO, 2 para os demais)
--   + Campo ev_1a_puro (EV do flat bet)
--   + Campo stake_leverage (multiplicador de stake para SUPREMO)
--
-- HIERARQUIA DE STATUS:
--   SUPREMO      → tem_fv6 = TRUE  (sem gale, stake elevado)
--   APROVADO     → n_filtros >= 4  (gale 2, stake 1.0x)
--   CONDICIONAL  → n_filtros >= 2  (gale 2, stake 0.5x)
--   MONITORAMENTO→ n_filtros = 1   (não operar)
-- =============================================================================

CREATE OR REPLACE VIEW hft_lake.vw_grade_suprema AS

-- NOTA: FV1-FV5 originais usam n_30d >= 20/15, bloqueando dados com <20 dias.
-- O histórico atual tem média de ~13 dias (n_30d médio = 12.6).
-- Esta view usa versões calibradas inline (n_min = 8) sem alterar os arquivos originais.

WITH

fv1_cal AS (
  SELECT ativo, hh_mm, direcao
  FROM hft_lake.hft_raw_metrics
  WHERE n_30d >= 8
    AND ((win_1a_30d + win_g1_30d + win_g2_30d)::numeric / NULLIF(n_30d,0)) >= 0.88
    AND (
      (((win_1a_30d + win_g1_30d + win_g2_30d)::numeric / NULLIF(n_30d,0)) * 0.85) -
      ((hit_30d::numeric / NULLIF(n_30d,0)) * 8.2)
    ) > 0.0
),

fv2_cal AS (
  SELECT ativo, hh_mm, direcao
  FROM hft_lake.hft_raw_metrics
  WHERE n_30d >= 8
    AND (win_1a_30d::numeric / NULLIF(n_30d,0)) >= 0.55
    AND ((win_1a_30d + win_g1_30d + win_g2_30d)::numeric / NULLIF(n_30d,0)) >= 0.88
),

fv3_cal AS (
  SELECT ativo, hh_mm, direcao
  FROM hft_lake.hft_raw_metrics
  WHERE n_30d >= 8
    AND n_3d >= 2
    AND ((win_1a_3d + win_g1_3d + win_g2_3d)::numeric / NULLIF(n_3d,0)) >= 0.85
    AND hit_3d = 0
),

fv4_cal AS (
  SELECT ativo, hh_mm, direcao
  FROM hft_lake.hft_raw_metrics
  WHERE n_30d >= 8
    AND ((win_1a_30d + win_g1_30d + win_g2_30d)::numeric / NULLIF(n_30d,0)) >= 0.88
    AND (hit_30d::numeric / 4.0) <= 1.0
    AND hit_3d = 0
),

fv5_cal AS (
  SELECT a.ativo, a.hh_mm, a.direcao
  FROM hft_lake.hft_raw_metrics a
  LEFT JOIN hft_lake.hft_raw_metrics b
    ON a.ativo = b.ativo AND a.hh_mm = b.hh_mm AND a.direcao != b.direcao
  WHERE a.n_30d >= 8
    AND ((a.win_1a_30d + a.win_g1_30d + a.win_g2_30d)::numeric / NULLIF(a.n_30d,0)) >= 0.88
    AND (
      ((a.win_1a_30d + a.win_g1_30d + a.win_g2_30d)::numeric / NULLIF(a.n_30d,0)) -
      COALESCE(((b.win_1a_30d + b.win_g1_30d + b.win_g2_30d)::numeric / NULLIF(b.n_30d,0)), 0)
    ) >= 0.15
),

convergencia AS (
  SELECT ativo, hh_mm, direcao, 'FV1' AS filtro FROM fv1_cal
  UNION ALL
  SELECT ativo, hh_mm, direcao, 'FV2' AS filtro FROM fv2_cal
  UNION ALL
  SELECT ativo, hh_mm, direcao, 'FV3' AS filtro FROM fv3_cal
  UNION ALL
  SELECT ativo, hh_mm, direcao, 'FV4' AS filtro FROM fv4_cal
  UNION ALL
  SELECT ativo, hh_mm, direcao, 'FV5' AS filtro FROM fv5_cal
  UNION ALL
  SELECT ativo, hh_mm, direcao, 'FV6' AS filtro FROM hft_lake.vw_fv6_minuto_supremo
),

contagem AS (
  SELECT
    ativo,
    hh_mm,
    direcao,
    COUNT(*)                                         AS n_filtros,
    STRING_AGG(filtro, ', ' ORDER BY filtro)         AS filtros_aprovados,
    BOOL_OR(filtro = 'FV6')                          AS tem_fv6
  FROM convergencia
  GROUP BY ativo, hh_mm, direcao
),

metricas AS (
  SELECT
    ativo,
    hh_mm,
    direcao,
    n_30d,
    hit_30d                                          AS n_hit,

    ROUND((win_1a_30d::numeric / NULLIF(n_30d, 0)), 4)
                                                     AS wr_1a,

    ROUND(((win_1a_30d + win_g1_30d + win_g2_30d)::numeric / NULLIF(n_30d, 0)), 4)
                                                     AS wr_g2,

    -- EV Gale 2 (modo padrão)
    ROUND(
      (((win_1a_30d + win_g1_30d + win_g2_30d)::numeric / NULLIF(n_30d, 0)) * 0.85) -
      ((hit_30d::numeric / NULLIF(n_30d, 0)) * 8.2)
    , 4)                                             AS ev_gale2,

    -- EV flat bet (modo supremo)
    ROUND(
      (win_1a_30d::numeric           / NULLIF(n_30d, 0)) * 0.85 -
      ((n_30d - win_1a_30d)::numeric / NULLIF(n_30d, 0)) * 1.0
    , 4)                                             AS ev_1a_puro,

    -- Score 30/7 sobre G2
    ROUND(
      (((win_1a_30d + win_g1_30d + win_g2_30d)::numeric / NULLIF(n_30d, 0)) * 0.6) +
      (((win_1a_7d  + win_g1_7d  + win_g2_7d )::numeric / NULLIF(n_7d,  0)) * 0.4)
    , 4)                                             AS score_30_7

  FROM hft_lake.hft_raw_metrics
),

fv6_info AS (
  SELECT
    ativo,
    hh_mm,
    direcao,
    stake_leverage,
    ev_1a_puro      AS ev_fv6,
    wr_1a_30d       AS wr_1a_fv6,
    assimetria_1a
  FROM hft_lake.vw_fv6_minuto_supremo
)

SELECT
  c.ativo,
  c.hh_mm,
  c.direcao,

  c.n_filtros,
  c.filtros_aprovados,
  c.tem_fv6,

  m.wr_1a,
  m.wr_g2,
  m.ev_gale2,
  m.ev_1a_puro,
  m.score_30_7,
  m.n_30d         AS n_total,
  m.n_hit,

  f.stake_leverage,
  f.ev_fv6,
  f.wr_1a_fv6,
  f.assimetria_1a,

  -- Status hierárquico
  CASE
    WHEN c.tem_fv6           THEN 'SUPREMO'
    WHEN c.n_filtros >= 4    THEN 'APROVADO'
    WHEN c.n_filtros >= 2    THEN 'CONDICIONAL'
    ELSE                          'MONITORAMENTO'
  END                              AS status,

  -- Modo de operação
  CASE
    WHEN c.tem_fv6           THEN 'SEM_GALE'
    ELSE                          'GALE_2'
  END                              AS modo_operacao,

  -- Stake final
  CASE
    WHEN c.tem_fv6           THEN COALESCE(f.stake_leverage, 1.5)
    WHEN c.n_filtros >= 4    THEN 1.0
    WHEN c.n_filtros >= 2    THEN 0.5
    ELSE                          0.0
  END                              AS stake_multiplier,

  -- Max gale permitido
  CASE
    WHEN c.tem_fv6           THEN 0
    ELSE                          2
  END                              AS max_gale

FROM contagem c
JOIN metricas m
  ON  c.ativo   = m.ativo
  AND c.hh_mm   = m.hh_mm
  AND c.direcao = m.direcao
LEFT JOIN fv6_info f
  ON  c.ativo   = f.ativo
  AND c.hh_mm   = f.hh_mm
  AND c.direcao = f.direcao

ORDER BY
  CASE WHEN c.tem_fv6 THEN 0 ELSE 1 END,
  c.n_filtros DESC,
  m.ev_gale2 DESC;
