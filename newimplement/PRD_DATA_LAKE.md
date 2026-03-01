# 📄 PRD_DATA_LAKE.md — Arquitetura Data Lake (Integração Paralela)

## Projeto: Oracle Quant — Nova Camada de Inteligência Estatística

**Versão:** 1.0  
**Status:** Em Implementação  
**Data:** 2026-02-28  
**Repositório:** `projeto_catalogador/data_lake/`

---

> ⚠️ **INSTRUÇÕES CRÍTICAS PARA A IA (Claude Code)**
>
> Você está implementando uma **NOVA ARQUITETURA PARALELA**.
> O sistema antigo (PRD.md v2.0) continua funcionando intacto.
>
> **REGRA ABSOLUTA N°1:** Nunca modifique, apague ou toque em nenhum arquivo existente.
> **REGRA ABSOLUTA N°2:** Nunca altere tabelas existentes no Supabase (hft_oracle_results, agent_cycles, hft_catalogo_estrategias).
> **REGRA ABSOLUTA N°3:** Toda a nova implementação vive em `data_lake/` e no schema `hft_lake` do Supabase.
> **REGRA ABSOLUTA N°4:** O Sniper (run_sniper.py) e o Front-end não são tocados.
>
> Confirme que entendeu antes de escrever qualquer linha de código.

---

## 1. VISÃO GERAL — O QUE MUDA E O QUE NÃO MUDA

### O que NÃO muda (sistema legado intocável)
- `core/data_loader.py` — continua funcionando
- `core/pattern_miner.py` — continua funcionando
- `core/strategy_validator.py` — continua funcionando
- `core/strategy_writer.py` — continua funcionando
- `core/agent_discovery.py` — continua funcionando
- `config.json` — continua sendo lido pelo Sniper
- `run_sniper.py` — continua rodando na VPS sem alteração
- Tabelas `public.hft_oracle_results`, `public.agent_cycles`, `public.hft_catalogo_estrategias` — intocáveis
- Frontend Million Bots — não muda nada

### O que é NOVO (implementação paralela)
- `data_lake/lake_loader.py` — novo script Python que lê o catalog.db e agrega métricas
- `data_lake/lake_uploader.py` — envia os resultados para o Supabase (schema hft_lake)
- `data_lake/lake_exporter.py` — lê as views do Supabase e gera novo config_lake.json
- Schema `hft_lake` no Supabase com tabela `hft_raw_metrics` e views FV1 a FV5
- `config_lake.json` — gerado pela nova arquitetura (o Sniper ainda lê o antigo config.json)

---

## 2. FILOSOFIA DA NOVA ARQUITETURA

**Separação de responsabilidades:**

```
Python (Caminhão de Entrega)
  → Lê catalog.db local (SQLite)
  → Conta: win_1a, win_g1, win_g2, n_hit por (ativo, hh_mm, direcao)
  → Manda APENAS o resumo estatístico para o Supabase
  → NÃO julga. NÃO aprova. NÃO reprova.

Supabase (Cérebro de Filtros)
  → Recebe os dados brutos em hft_lake.hft_raw_metrics
  → Aplica Views SQL como filtros independentes (FV1 a FV5)
  → Qualquer novo filtro = nova View SQL, zero Python novo
```

**Matemática do volume:**
- Velas no SQLite local: ~43.200 por ativo × 5 ativos = 216.000 linhas
- Resultados enviados ao Supabase: 1.440 minutos × 2 direções × 5 ativos = 14.400 linhas
- O Supabase recebe 14.400 linhas de resumo, não 216.000 velas brutas

---

## 3. ATIVOS SUPORTADOS

```python
ATIVOS = ["R_10", "R_25", "R_50", "R_75", "R_100"]
```

Todos os 5 ativos são catalogados. Os filtros no Supabase aplicam pesos diferentes por grupo de volatilidade automaticamente via SQL CASE WHEN.

**Grupos de volatilidade para os filtros:**
- ESTAVEL: R_10, R_25 → N mínimo = 20
- MODERADO: R_50 → N mínimo = 15
- AGRESSIVO: R_75, R_100 → N mínimo = 15, maior peso no momentum recente

---

## 4. ESTRUTURA DE PASTAS — NOVA IMPLEMENTAÇÃO

```
projeto_catalogador/
│
├── PRD.md                      ← Sistema antigo (NÃO TOCAR)
├── config.json                 ← Sistema antigo (NÃO TOCAR)
├── core/                       ← Sistema antigo (NÃO TOCAR)
│
└── data_lake/                  ← NOVO — tudo aqui dentro é novo
    ├── PRD_DATA_LAKE.md        ← Este documento
    ├── config_lake.json        ← Novo config gerado pela nova arquitetura
    ├── lake_loader.py          ← Agrega métricas do catalog.db
    ├── lake_uploader.py        ← Envia para hft_lake.hft_raw_metrics
    ├── lake_exporter.py        ← Lê views e gera config_lake.json
    ├── lake_runner.py          ← Orquestrador: roda loader → uploader → exporter
    └── sql/
        ├── 01_create_schema.sql
        ├── 02_create_hft_raw_metrics.sql
        ├── 03_view_fv1_minuto_solido.sql
        ├── 04_view_fv2_minuto_de_primeira.sql
        ├── 05_view_fv3_minuto_quente.sql
        ├── 06_view_fv4_minuto_resiliente.sql
        ├── 07_view_fv5_minuto_dominante.sql
        └── 08_view_grade_unificada.sql
```

---

## 5. BANCO DE DADOS — SCHEMA hft_lake

### 5.1 Criar Schema Isolado

```sql
-- 01_create_schema.sql
CREATE SCHEMA IF NOT EXISTS hft_lake;
```

### 5.2 Tabela Principal: hft_raw_metrics

Esta é a "Tabela Mãe". O Python insere aqui. Nunca modifique esta estrutura após criada.

```sql
-- 02_create_hft_raw_metrics.sql
CREATE TABLE IF NOT EXISTS hft_lake.hft_raw_metrics (
  id              BIGSERIAL PRIMARY KEY,

  -- Identificadores
  ativo           TEXT NOT NULL,    -- "R_10", "R_25", "R_50", "R_75", "R_100"
  hh_mm           TEXT NOT NULL,    -- "00:00" até "23:59"
  direcao         TEXT NOT NULL,    -- "CALL" ou "PUT"

  -- Janela 30 dias (histórico completo)
  n_30d           INT NOT NULL DEFAULT 0,
  win_1a_30d      INT NOT NULL DEFAULT 0,
  win_g1_30d      INT NOT NULL DEFAULT 0,
  win_g2_30d      INT NOT NULL DEFAULT 0,
  hit_30d         INT NOT NULL DEFAULT 0,

  -- Janela 7 dias (recência)
  n_7d            INT NOT NULL DEFAULT 0,
  win_1a_7d       INT NOT NULL DEFAULT 0,
  win_g1_7d       INT NOT NULL DEFAULT 0,
  win_g2_7d       INT NOT NULL DEFAULT 0,
  hit_7d          INT NOT NULL DEFAULT 0,

  -- Janela 3 dias (momentum)
  n_3d            INT NOT NULL DEFAULT 0,
  win_1a_3d       INT NOT NULL DEFAULT 0,
  win_g1_3d       INT NOT NULL DEFAULT 0,
  win_g2_3d       INT NOT NULL DEFAULT 0,
  hit_3d          INT NOT NULL DEFAULT 0,

  -- Controle
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

  -- Chave única: um ativo+horário+direção por upload
  CONSTRAINT hft_raw_metrics_upsert UNIQUE (ativo, hh_mm, direcao)
);

-- Índices para performance das Views
CREATE INDEX IF NOT EXISTS idx_raw_ativo ON hft_lake.hft_raw_metrics(ativo);
CREATE INDEX IF NOT EXISTS idx_raw_hh_mm ON hft_lake.hft_raw_metrics(hh_mm);
CREATE INDEX IF NOT EXISTS idx_raw_direcao ON hft_lake.hft_raw_metrics(direcao);
```

---

## 6. VIEWS SQL — OS FILTROS (FV1 a FV5)

Cada View é um filtro independente. Novas estratégias = novas Views. Zero Python novo.

### FV1 — Minuto Sólido (Substituto da V4)

Horários que ganham consistentemente nos 30 dias E confirmam nos últimos 7.
Score ponderado 60/40. EV positivo obrigatório.

```sql
-- 03_view_fv1_minuto_solido.sql
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
```

### FV2 — Minuto de Primeira

Horários onde a primeira entrada já ganha sem depender do Gale.
Estratégia mais robusta — baixo drawdown real.

```sql
-- 04_view_fv2_minuto_de_primeira.sql
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
```

### FV3 — Minuto Quente (Momentum 3 Dias)

Horários em ciclo ativo agora. Captura o padrão algorítmico corrente.

```sql
-- 05_view_fv3_minuto_quente.sql
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
```

### FV4 — Minuto Resiliente (Proteção de Sequência)

Horários que erram isolado — nunca em sequência. Protege a banca de drawdowns concentrados.

```sql
-- 06_view_fv4_minuto_resiliente.sql
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
```

### FV5 — Minuto Dominante (Assimetria Direcional)

Horários onde CALL domina PUT de forma inequívoca. Vantagem estrutural algorítmica.

```sql
-- 07_view_fv5_minuto_dominante.sql
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
```

### Grade Unificada — View Principal do Sistema

Consolida todos os filtros com hierarquia de confiança.
Horários que aparecem em mais filtros têm maior confiança.

```sql
-- 08_view_grade_unificada.sql
CREATE OR REPLACE VIEW hft_lake.vw_grade_unificada AS
WITH convergencia AS (
  SELECT ativo, hh_mm, direcao, 'FV1' AS filtro FROM hft_lake.vw_fv1_minuto_solido
  UNION ALL
  SELECT ativo, hh_mm, direcao, 'FV2' AS filtro FROM hft_lake.vw_fv2_minuto_de_primeira
  UNION ALL
  SELECT ativo, hh_mm, direcao, 'FV3' AS filtro FROM hft_lake.vw_fv3_minuto_quente
  UNION ALL
  SELECT ativo, hh_mm, direcao, 'FV4' AS filtro FROM hft_lake.vw_fv4_minuto_resiliente
  UNION ALL
  SELECT ativo, hh_mm, direcao, 'FV5' AS filtro FROM hft_lake.vw_fv5_minuto_dominante
),
contagem AS (
  SELECT
    ativo,
    hh_mm,
    direcao,
    COUNT(*) AS n_filtros,
    STRING_AGG(filtro, ', ' ORDER BY filtro) AS filtros_aprovados
  FROM convergencia
  GROUP BY ativo, hh_mm, direcao
),
metricas AS (
  SELECT
    ativo,
    hh_mm,
    direcao,
    ROUND(((win_1a_30d + win_g1_30d + win_g2_30d)::numeric / NULLIF(n_30d,0)), 4)  AS wr_g2,
    ROUND((win_1a_30d::numeric / NULLIF(n_30d,0)), 4)                               AS wr_1a,
    ROUND(
      (((win_1a_30d + win_g1_30d + win_g2_30d)::numeric / NULLIF(n_30d,0)) * 0.85) -
      ((hit_30d::numeric / NULLIF(n_30d,0)) * 8.2)
    , 4)                                                                              AS ev_g2,
    n_30d,
    hit_30d AS n_hit
  FROM hft_lake.hft_raw_metrics
)
SELECT
  c.ativo,
  c.hh_mm,
  c.direcao,
  c.n_filtros,
  c.filtros_aprovados,
  m.wr_g2,
  m.wr_1a,
  m.ev_g2,
  m.n_30d AS n_total,
  m.n_hit,

  -- Status baseado em convergência de filtros
  CASE
    WHEN c.n_filtros >= 4 THEN 'APROVADO'
    WHEN c.n_filtros >= 2 THEN 'CONDICIONAL'
    ELSE 'MONITORAMENTO'
  END AS status,

  -- Stake baseado em convergência
  CASE
    WHEN c.n_filtros >= 4 THEN 1.0
    WHEN c.n_filtros >= 2 THEN 0.5
    ELSE 0.0
  END AS stake_multiplier

FROM contagem c
JOIN metricas m ON c.ativo = m.ativo AND c.hh_mm = m.hh_mm AND c.direcao = m.direcao

ORDER BY c.n_filtros DESC, m.ev_g2 DESC;
```

---

## 7. PYTHON — SCRIPTS DA NOVA ARQUITETURA

### 7.1 lake_loader.py — Agrega métricas do catalog.db

```python
"""
lake_loader.py — Lê catalog.db e agrega métricas por (ativo, hh_mm, direcao)

LÓGICA:
- Para cada (ativo, hh_mm, direcao), conta wins e hits nas janelas de 30/7/3 dias
- A direção dominante é determinada por qual direção tem mais wins na primeira entrada
- Retorna DataFrame pronto para o uploader

NÃO modifica nenhum arquivo existente.
Lê apenas: catalog/catalog.db
"""

import sqlite3
import pandas as pd
from pathlib import Path
from datetime import datetime, timedelta
import time

ATIVOS = ["R_10", "R_25", "R_50", "R_75", "R_100"]
DB_PATH = Path("catalog/catalog.db")

# Janelas de tempo em dias
JANELA_30D = 30
JANELA_7D = 7
JANELA_3D = 3


def get_epoch_corte(dias: int) -> int:
    """Retorna epoch UTC do início da janela (dias atrás)."""
    corte = datetime.utcnow() - timedelta(days=dias)
    return int(corte.timestamp())


def load_catalog(ativo: str) -> pd.DataFrame:
    """Carrega velas do catalog.db para um ativo específico."""
    conn = sqlite3.connect(DB_PATH)
    query = """
        SELECT
            timestamp,
            hh_mm,
            resultado_1a,
            resultado_g1,
            resultado_g2
        FROM catalog
        WHERE ativo = ?
        ORDER BY timestamp ASC
    """
    df = pd.read_sql_query(query, conn, params=(ativo,))
    conn.close()
    return df


def calcular_metricas_janela(df: pd.DataFrame, epoch_corte: int, direcao: str) -> dict:
    """
    Calcula win_1a, win_g1, win_g2 e n_hit para uma janela de tempo e direção.

    direcao="CALL" → cor_alvo="VERDE" (resultado_1a == 'A')
    direcao="PUT"  → cor_alvo="VERMELHA" (resultado_1a == 'B')
    """
    cor_alvo = "A" if direcao == "CALL" else "B"
    df_janela = df[df["timestamp"] >= epoch_corte].copy()

    if df_janela.empty:
        return {"n": 0, "win_1a": 0, "win_g1": 0, "win_g2": 0, "hit": 0}

    # Ciclos completos apenas (todos os 3 resultados disponíveis)
    df_completo = df_janela.dropna(subset=["resultado_1a", "resultado_g1", "resultado_g2"])
    n = len(df_completo)

    if n == 0:
        return {"n": 0, "win_1a": 0, "win_g1": 0, "win_g2": 0, "hit": 0}

    win_1a = (df_completo["resultado_1a"] == cor_alvo).sum()
    win_g1 = ((df_completo["resultado_1a"] != cor_alvo) &
               (df_completo["resultado_g1"] == cor_alvo)).sum()
    win_g2 = ((df_completo["resultado_1a"] != cor_alvo) &
               (df_completo["resultado_g1"] != cor_alvo) &
               (df_completo["resultado_g2"] == cor_alvo)).sum()
    hit = ((df_completo["resultado_1a"] != cor_alvo) &
            (df_completo["resultado_g1"] != cor_alvo) &
            (df_completo["resultado_g2"] != cor_alvo)).sum()

    # Invariante: win_1a + win_g1 + win_g2 + hit == n
    assert int(win_1a + win_g1 + win_g2 + hit) == n, \
        f"INVARIANTE QUEBRADA: {win_1a}+{win_g1}+{win_g2}+{hit} != {n}"

    return {
        "n": int(n),
        "win_1a": int(win_1a),
        "win_g1": int(win_g1),
        "win_g2": int(win_g2),
        "hit": int(hit),
    }


def agregar_ativo(ativo: str) -> list[dict]:
    """
    Para um ativo, agrega métricas de todos os 1.440 minutos × 2 direções.
    Retorna lista de dicts prontos para INSERT no Supabase.
    """
    print(f"[LOADER] Processando {ativo}...")
    df = load_catalog(ativo)

    if df.empty:
        print(f"[LOADER] ⚠️  Nenhum dado para {ativo}")
        return []

    epoch_30d = get_epoch_corte(JANELA_30D)
    epoch_7d  = get_epoch_corte(JANELA_7D)
    epoch_3d  = get_epoch_corte(JANELA_3D)

    resultados = []
    hh_mms = df["hh_mm"].unique()
    total = len(hh_mms)

    for i, hh_mm in enumerate(sorted(hh_mms), 1):
        df_minuto = df[df["hh_mm"] == hh_mm]

        for direcao in ["CALL", "PUT"]:
            m30 = calcular_metricas_janela(df_minuto, epoch_30d, direcao)
            m7  = calcular_metricas_janela(df_minuto, epoch_7d, direcao)
            m3  = calcular_metricas_janela(df_minuto, epoch_3d, direcao)

            resultados.append({
                "ativo":       ativo,
                "hh_mm":       hh_mm,
                "direcao":     direcao,
                "n_30d":       m30["n"],
                "win_1a_30d":  m30["win_1a"],
                "win_g1_30d":  m30["win_g1"],
                "win_g2_30d":  m30["win_g2"],
                "hit_30d":     m30["hit"],
                "n_7d":        m7["n"],
                "win_1a_7d":   m7["win_1a"],
                "win_g1_7d":   m7["win_g1"],
                "win_g2_7d":   m7["win_g2"],
                "hit_7d":      m7["hit"],
                "n_3d":        m3["n"],
                "win_1a_3d":   m3["win_1a"],
                "win_g1_3d":   m3["win_g1"],
                "win_g2_3d":   m3["win_g2"],
                "hit_3d":      m3["hit"],
            })

        if i % 100 == 0:
            pct = round(i / total * 100, 1)
            print(f"[LOADER] {ativo}: {i}/{total} minutos processados ({pct}%)")

    print(f"[LOADER] ✅ {ativo}: {len(resultados)} registros gerados")
    return resultados


def run_loader() -> pd.DataFrame:
    """Processa todos os ativos e retorna DataFrame consolidado."""
    print(f"\n{'='*60}")
    print(f"[LOADER] Iniciando agregação — {len(ATIVOS)} ativos")
    print(f"{'='*60}\n")

    todos = []
    for ativo in ATIVOS:
        registros = agregar_ativo(ativo)
        todos.extend(registros)

    df_final = pd.DataFrame(todos)
    print(f"\n[LOADER] ✅ Total: {len(df_final)} registros prontos para upload")
    return df_final


if __name__ == "__main__":
    df = run_loader()
    print(df.head())
```

### 7.2 lake_uploader.py — Envia para o Supabase

```python
"""
lake_uploader.py — Envia DataFrame para hft_lake.hft_raw_metrics no Supabase

LÓGICA:
- Usa UPSERT (ON CONFLICT DO UPDATE) — nunca duplica
- Processa em batches de 500 linhas para não sobrecarregar a API
- Loga progresso em tempo real

Requer: SUPABASE_URL e SUPABASE_KEY no ambiente (.env ou variáveis de sistema)
NÃO modifica nenhum arquivo ou tabela existente além de hft_lake.hft_raw_metrics
"""

import os
import pandas as pd
from supabase import create_client, Client
from dotenv import load_dotenv
import time

load_dotenv()

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_KEY"]
TABELA = "hft_raw_metrics"
SCHEMA = "hft_lake"
BATCH_SIZE = 500


def get_client() -> Client:
    return create_client(SUPABASE_URL, SUPABASE_KEY)


def upload(df: pd.DataFrame) -> dict:
    """
    Faz upsert do DataFrame na tabela hft_lake.hft_raw_metrics.
    Retorna dict com total inserido/atualizado.
    """
    client = get_client()
    registros = df.to_dict(orient="records")
    total = len(registros)
    inseridos = 0

    print(f"\n[UPLOADER] Enviando {total} registros para hft_lake.{TABELA}...")
    print(f"[UPLOADER] Batch size: {BATCH_SIZE} | Batches: {(total // BATCH_SIZE) + 1}\n")

    for i in range(0, total, BATCH_SIZE):
        batch = registros[i:i + BATCH_SIZE]
        n_batch = len(batch)

        try:
            client.schema(SCHEMA).table(TABELA).upsert(
                batch,
                on_conflict="ativo,hh_mm,direcao"
            ).execute()

            inseridos += n_batch
            pct = round(inseridos / total * 100, 1)
            print(f"[UPLOADER] Batch {i//BATCH_SIZE + 1} ✅ | {inseridos}/{total} ({pct}%)")

        except Exception as e:
            print(f"[UPLOADER] ❌ Erro no batch {i//BATCH_SIZE + 1}: {e}")
            raise

        time.sleep(0.3)  # Respiro para não sobrecarregar a API

    print(f"\n[UPLOADER] ✅ Upload completo: {inseridos}/{total} registros")
    return {"total": total, "inseridos": inseridos}


if __name__ == "__main__":
    # Teste com dados mock
    from lake_loader import run_loader
    df = run_loader()
    upload(df)
```

### 7.3 lake_exporter.py — Lê views e gera config_lake.json

```python
"""
lake_exporter.py — Lê vw_grade_unificada e gera config_lake.json

LÓGICA:
- Consulta a view vw_grade_unificada no Supabase
- Filtra apenas APROVADO e CONDICIONAL
- Gera config_lake.json no formato compatível com o Sniper
- O Sniper antigo continua lendo config.json (intocável)
- Este arquivo é o futuro config_lake.json (paralelo, não substitui ainda)

NÃO modifica config.json nem qualquer arquivo existente.
"""

import os
import json
from pathlib import Path
from supabase import create_client, Client
from dotenv import load_dotenv
import time

load_dotenv()

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_KEY"]
OUTPUT_PATH = Path("data_lake/config_lake.json")


def get_client() -> Client:
    return create_client(SUPABASE_URL, SUPABASE_KEY)


def exportar_grade() -> dict:
    """
    Lê a grade unificada do Supabase e converte para formato config_lake.json.
    """
    client = get_client()
    print("\n[EXPORTER] Consultando vw_grade_unificada...")

    response = (
        client.schema("hft_lake")
        .table("vw_grade_unificada")
        .select("*")
        .in_("status", ["APROVADO", "CONDICIONAL"])
        .order("n_filtros", desc=True)
        .order("ev_g2", desc=True)
        .execute()
    )

    registros = response.data
    print(f"[EXPORTER] {len(registros)} estratégias encontradas")

    config = {}
    for r in registros:
        # strategy_id no mesmo formato do sistema antigo para compatibilidade futura
        strategy_id = f"T{r['hh_mm'].replace(':','')}_LAKE_{r['ativo'].replace('_','')}_{r['direcao']}"

        config[strategy_id] = {
            "ativo":           r["ativo"],
            "hh_mm":           r["hh_mm"],
            "direcao":         r["direcao"],
            "p_win_g2":        r["wr_g2"],
            "p_win_1a":        r["wr_1a"],
            "ev_g2":           r["ev_g2"],
            "n_total":         r["n_total"],
            "n_hit":           r["n_hit"],
            "n_filtros":       r["n_filtros"],
            "filtros":         r["filtros_aprovados"],
            "sizing_override": r["stake_multiplier"],
            "status":          r["status"],
            "fonte":           "DATA_LAKE_V1",
        }

    return config


def salvar_config(config: dict):
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
    print(f"[EXPORTER] ✅ config_lake.json salvo: {len(config)} estratégias → {OUTPUT_PATH}")


def run_exporter():
    config = exportar_grade()
    salvar_config(config)

    # Sumário
    aprovadas = sum(1 for v in config.values() if v["status"] == "APROVADO")
    condicionais = sum(1 for v in config.values() if v["status"] == "CONDICIONAL")
    print(f"\n[EXPORTER] Sumário:")
    print(f"  APROVADO:    {aprovadas}")
    print(f"  CONDICIONAL: {condicionais}")
    print(f"  TOTAL:       {len(config)}")


if __name__ == "__main__":
    run_exporter()
```

### 7.4 lake_runner.py — Orquestrador

```python
"""
lake_runner.py — Orquestrador da nova arquitetura Data Lake

EXECUTA EM SEQUÊNCIA:
  1. lake_loader  → Agrega métricas do catalog.db
  2. lake_uploader → Envia para hft_lake.hft_raw_metrics
  3. lake_exporter → Gera config_lake.json

USO:
  python data_lake/lake_runner.py

NÃO interfere com nenhum processo existente.
"""

import time
from lake_loader import run_loader
from lake_uploader import upload
from lake_exporter import run_exporter


def main():
    inicio = time.time()
    print("\n" + "="*60)
    print("  ORACLE QUANT — DATA LAKE RUNNER")
    print("="*60)

    # Passo 1: Carregar
    print("\n[RUNNER] === PASSO 1/3: LOADER ===")
    t1 = time.time()
    df = run_loader()
    print(f"[RUNNER] Loader: {round(time.time()-t1, 1)}s")

    if df.empty:
        print("[RUNNER] ❌ Nenhum dado carregado. Abortando.")
        return

    # Passo 2: Upload
    print("\n[RUNNER] === PASSO 2/3: UPLOADER ===")
    t2 = time.time()
    resultado = upload(df)
    print(f"[RUNNER] Uploader: {round(time.time()-t2, 1)}s")

    # Passo 3: Exportar
    print("\n[RUNNER] === PASSO 3/3: EXPORTER ===")
    t3 = time.time()
    run_exporter()
    print(f"[RUNNER] Exporter: {round(time.time()-t3, 1)}s")

    total = round(time.time() - inicio, 1)
    print(f"\n{'='*60}")
    print(f"  ✅ DATA LAKE COMPLETO em {total}s")
    print(f"  Registros processados: {resultado['inseridos']}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
```

---

## 8. COMANDOS DE INSTALAÇÃO VIA CLI (Claude Code)

Execute estes comandos em sequência no terminal para construir toda a infraestrutura:

```bash
# 1. Criar estrutura de pastas
mkdir -p data_lake/sql

# 2. Instalar dependências novas (sem remover as existentes)
pip install supabase python-dotenv --break-system-packages

# 3. Executar SQLs no Supabase via CLI (requer supabase CLI instalado)
# OU copiar o conteúdo de cada .sql para o SQL Editor do painel Supabase

# Se usar supabase CLI:
supabase db execute --file data_lake/sql/01_create_schema.sql
supabase db execute --file data_lake/sql/02_create_hft_raw_metrics.sql
supabase db execute --file data_lake/sql/03_view_fv1_minuto_solido.sql
supabase db execute --file data_lake/sql/04_view_fv2_minuto_de_primeira.sql
supabase db execute --file data_lake/sql/05_view_fv3_minuto_quente.sql
supabase db execute --file data_lake/sql/06_view_fv4_minuto_resiliente.sql
supabase db execute --file data_lake/sql/07_view_fv5_minuto_dominante.sql
supabase db execute --file data_lake/sql/08_view_grade_unificada.sql

# 4. Rodar o pipeline completo
cd data_lake
python lake_runner.py
```

---

## 9. VARIÁVEIS DE AMBIENTE NECESSÁRIAS

Adicionar ao `.env` existente (sem remover nenhuma variável atual):

```env
# DATA LAKE — novas variáveis (não conflitam com as existentes)
SUPABASE_URL=https://seu-projeto.supabase.co
SUPABASE_KEY=sua-service-role-key
```

---

## 10. CHECKLIST DE VALIDAÇÃO PÓS-IMPLEMENTAÇÃO

Após rodar o pipeline, verificar no painel Supabase:

```
✅ Schema hft_lake criado
✅ Tabela hft_lake.hft_raw_metrics com 14.400 linhas (5 ativos × 1.440 min × 2 direções)
✅ View vw_fv1_minuto_solido retorna resultados
✅ View vw_fv2_minuto_de_primeira retorna resultados
✅ View vw_fv3_minuto_quente retorna resultados
✅ View vw_fv4_minuto_resiliente retorna resultados
✅ View vw_fv5_minuto_dominante retorna resultados
✅ View vw_grade_unificada retorna APROVADO e CONDICIONAL
✅ Arquivo data_lake/config_lake.json gerado
✅ Sistema antigo (config.json + run_sniper.py) continua funcionando intacto
```

---

## 11. PRÓXIMOS PASSOS (Após Validação)

1. Comparar `config_lake.json` vs `config.json` — avaliar qualidade das estratégias novas
2. Rodar em paralelo por 2 semanas sem tocar no Sniper
3. Quando aprovado: criar `run_sniper_lake.py` que lê `config_lake.json` (cópia do Sniper atual, sem alterar o original)
4. Migração gradual: ativar lake em 20% dos clientes, depois 50%, depois 100%
5. Só então arquivar o sistema antigo

---

*Este documento é a fonte da verdade para a implementação da nova arquitetura.*
*O PRD.md original (sistema antigo) permanece intocável e continua sendo a referência do sistema legado.*
