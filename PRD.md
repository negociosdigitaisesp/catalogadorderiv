# 📄 PRD.md — Motor de Inteligência Estatística (HFT Varejo)

## Projeto: Catalogador de Índices Sintéticos — Deriv

**Versão:** 2.0  
**Status:** Aprovado pelo Chief & Tech Lead  
**Data:** 2026-02-25  
**Repositório:** `projeto_catalogador/`

---

> ⚠️ **INSTRUÇÕES PARA A IA DA IDE (Cursor / Claude / Copilot)**
>
> Você está atuando como **Tech Lead Sênior** deste projeto.  
> Antes de escrever qualquer linha de código, leia este documento na íntegra.  
> Após a leitura, confirme que entendeu:
>
> 1. A arquitetura de **3 Camadas** (Oráculo → Sniper → Espelho)
> 2. As **5 Regras Absolutas de Código** (Anti-Vibe Coding)
> 3. O **Dicionário de Dados** (schema do Supabase)
> 4. As **6 Estratégias Validadas** (S1 a S6)
> 5. A **Filosofia dos 7 Pilares** (Zero Achismo, Apenas EV)
>
> Se você entendeu tudo, comece pela **Fase 1: math_engine.py**.  
> Nunca escreva código que viole as regras absolutas desta seção 5.

---

# VISÃO GERAL DO PRODUTO (Versão 3.0 — "Oracle Quant")

O **ORACLE QUANT** é um motor de inteligência quantitativa de alta performance integrado ao ecossistema **Million Bots**. Sua missão é a detecção e execução de **Anomalias Probabilísticas Temporais** em Índices Sintéticos da Deriv (R_10 a R_100, Crash, Boom, DEX, Daily Reset).

O sistema opera sob o regime de **Rejeição Técnica Total**, ignorando indicadores convencionais (RSI, Médias, Suporte/Resistência). A única fonte de verdade é a **Frequência de Ciclo Histórica**, baseada em três pilares:

- **Mapeamento de Agenda (HH:MM):** Identificação de horários "viciados" estatisticamente nos últimos 30 dias.
- **Estatística de Recuperação (Gale 2):** Uso do Martingale 1 e 2 como ferramentas de cobertura de variância, validadas por probabilidade real de acerto acumulado (G2 > 95%).
- **Peso de Recorrência (30/7):** Score ponderado que prioriza padrões estáveis no longo prazo (30 dias) que confirmam força no curto prazo (7 dias).

---

## 🔄 Fluxo de Dados e Processamento (Arquitetura 80/20)

### CAMADA A — O ORÁCULO (Offline / PC Local)

- **Mineração:** Varre 30 dias de histórico M1 (~43.200 velas por ativo).
- **Descoberta:** O Agente _"Auto Quant Discovery"_ utiliza um **Self-Healing Loop** (Workflow de Autocorreção) com o **Gatekeeper** (`sanity_check.py`) para garantir que apenas padrões matematicamente íntegros sejam catalogados.
- **Output:** Gera a **Grade Horária de Elite** em um arquivo `config.json` leve.

---

### CAMADA B — O SNIPER (Online / VPS Backend)

- **Vigilância:** Atua como um _"Relógio de Precisão"_. Lê o `config.json` e monitora o WebSocket da Deriv.
- **Execução:** Dispara o gatilho `PRE_SIGNAL` no **segundo 50** de cada horário agendado, enviando o sinal para o Supabase no schema isolado `hft_quant`.

---

### CAMADA C — O ESPELHO (Front-end Million Bots)

- **Interface:** Exibe a Grade Horária e os sinais em tempo real via **Supabase Realtime**.
- **Bridge de Execução:** Realiza a entrada automática na conta do cliente via **API JS/TS**, garantindo latência mínima e execução fiel ao horário catalogado.

## 2. FILOSOFIA DE DESIGN — OS 7 PILARES DO ORACLE QUANT

Toda decisão arquitetural, lógica de mineração e código de execução deve respeitar os pilares abaixo. O sistema opera sob o regime de **Probabilidade Temporal Pura**.

| #   | Pilar                             | Descrição Prática                                                                                                                                                                                                 |
| --- | --------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | **Pensamento de Série Binária**   | O trade não é visto como uma entrada única, mas como uma **Série de até 3 tentativas** (1ª entrada + Gale 1 + Gale 2). O resultado é binário: **WIN na Série** ou **HIT (Loss Total)**.                           |
| 2   | **Contexto Temporal (HH:MM)**     | O principal driver de assertividade é o **Horário**. O contexto é definido por: `HH:MM` + Dia da Semana + Ativo. Indicadores como RSI ou Médias são ruído; o relógio é a única fonte de sinal.                    |
| 3   | **Recorrência de 30 Dias**        | A validade estatística é extraída de uma **janela rolante de 30 dias**. Um horário só é _"Elite"_ se o padrão de cor da vela se repetiu com consistência histórica comprovada.                                    |
| 4   | **Valor Esperado Real (EV)**      | O cálculo do EV deve obrigatoriamente incluir o custo do Gale. `EV = (P_win_serie × Lucro_Serie) – (P_hit × 8.2)`. Se o lucro das vitórias não cobrir matematicamente o custo do HIT, a estratégia é descartada.  |
| 5   | **Sizing de Ciclo**               | O gerenciamento de banca é aplicado sobre o **custo total da série (8.2 unidades)**. O sistema utiliza o **Quarter Kelly** para garantir que um HIT isolado não comprometa a sobrevivência da conta.              |
| 6   | **Peso de Recência (Score 30/7)** | Princípio da _"Podridão do Ciclo"_. O sistema aplica peso maior à performance dos **últimos 7 dias (40%)** comparado aos 30 dias (60%). Se um padrão de 30 dias parou de funcionar na última semana, o score cai. |
| 7   | **Integridade Autocorretiva**     | Uso obrigatório de um **Gatekeeper** (`sanity_check.py`). Nenhuma estratégia é aprovada se a matemática de contagem (Wins vs Losses) não for auditada e aprovada pelo script de integridade antes do deploy.      |

---

# 3. ARQUITETURA DO SISTEMA — 3 CAMADAS (Grade Horária)

```
┌─────────────────────────────────────────────────────────────────┐
│  CAMADA A — O ORÁCULO QUANT (PC Local / Agente Autônomo)        │
│                                                                 │
│  Input:  Histórico Profundo (30 dias / 43.200 velas por ativo)  │
│  Faz:    Mapeamento de 1.440 min, Contagem de Wins (1ª, G1, G2) │
│  Agente: "Auto Quant Discovery" com Self-Healing Loop           │
│  Gatekeeper: sanity_check.py (Auditoria de contagem e shifts)   │
│  Output: config.json (Agenda de Elite 95%+)                     │
│                                                                 │
│  Stack:  Python, Pandas (Vetorizado), NumPy, SQLite             │
│  Roda:   Semanalmente ou sob demanda para renovar a agenda      │
└───────────────────────────┬─────────────────────────────────────┘
                            │ config.json (Agenda HH:MM + Dir)
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│  CAMADA B — O SNIPER DE AGENDA (Online / VPS Backend)           │
│                                                                 │
│  Input:  config.json + WebSocket Deriv (Relógio de Precisão)    │
│  Faz:    Monitoramento de Tempo. Standby até o horário alvo.    │
│  Lógica: No segundo 50 do minuto anterior → envia PRE_SIGNAL    │
│          Gere sequência: Entrada Real → Gale 1 → Gale 2         │
│  Output: INSERT no Supabase (Schema: hft_quant)                 │
│                                                                 │
│  Stack:  Python 3.10+, asyncio, websockets                      │
│  Roda:   24/7 na VPS (Consumo ultra-baixo de recursos)          │
└───────────────────────────┬─────────────────────────────────────┘
                            │ Real-time Event (INSERT/UPDATE)
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│  CAMADA C — O EXECUTOR (Front-end Million Bots)                 │
│                                                                 │
│  Input:  Sinais do Supabase Realtime + Token Deriv do Cliente   │
│  Faz:    Ponte de Execução (Execution Bridge).                  │
│  Ação:   Dispara ordem buy/sell via JS/TS direto para corretora │
│  Delay:  Alvo < 200ms entre sinal no banco e clique na conta    │
└─────────────────────────────────────────────────────────────────┘
```

---

# 4. ESTRATÉGIAS DE MINERAÇÃO (V1, V2, V4)

> O sistema foca em padrões de repetição algorítmica por horário. O Gale 2 é utilizado como ferramenta de exaustão do ruído de 1 minuto. **Nenhuma variação usa `dia_semana` no agrupamento** — decisão arquitetural para maximizar o N amostral.

### Anti-Overfitting: TRAIN/TEST Split (Todas as Variações)

Todas as variações obrigatoriamente usam o `_split_train_test`:

- **TRAIN (dias ímpares):** Usado APENAS para determinar a direção dominante (CALL/PUT).
- **TEST (dias pares):** Usado para calcular a Win Rate real (out-of-sample).
- Com 30 dias de dados, cada grupo tem ~15 amostras no TEST.
- Isso **impede overfitting** — a direção nunca é escolhida nos mesmos dados que medem o WR.

---

### V1 — Puro Horário

- **Agrupamento:** `(ativo, hh_mm)` — todos os dias.
- **Lógica:** Identifica minutos específicos (ex: `13:55`) que repetem a mesma cor de vela consistentemente nos últimos 30 dias.
- **Split:** TRAIN determina direção, TEST calcula WR.
- **N esperado:** ~15 (metade dos ~30 dias, após split).

### V2 — Bloco MHI de Horário (Cor + Tempo)

- **Agrupamento:** `(ativo, hh_mm, mhi_seq)` — todos os dias.
- **Lógica:** Analisa as 3 velas anteriores ao horário alvo. A pergunta: "Às 13:55, quando as últimas 3 velas foram V-V-R, qual a assertividade?"
- **Split:** TRAIN determina direção, TEST calcula WR.
- **N esperado:** ~3-8 (MHI subdivide em 8 sequências possíveis). Precisa de >60 dias para atingir N≥15.

### ~~V3 — Abolida~~ _(Engolida pela V4)_

> V3 usava o mesmo agrupamento que V4 `(ativo, hh_mm)` sem o score de recência. Era 100% redundante. Removida na refatoração de 27/02/2026.

### V4 — Recorrência Recente (Score 30/7)

- **Agrupamento:** `(ativo, hh_mm)` — todos os dias.
- **Lógica:** Aplica média ponderada de recência: `Score = (WR_30d × 0.6) + (WR_7d × 0.4)`.
- **Objetivo:** Priorizar horários que estão _"quentes"_ na última semana.
- **Split:** TRAIN determina direção, TEST calcula WR.
- **Prioridade sobre V1:** Se um `(ativo, hh_mm)` aparece na V4, ele é removido da V1 (deduplicação no `mine_all`).

---

### 🗺️ Roadmap: Variações Futuras (Não Implementadas)

| Variação                     | Conceito                          | Status                                     |
| ---------------------------- | --------------------------------- | ------------------------------------------ |
| **V5** — Janela Tripla       | Confluência M1 + M5 + M15         | 🔜 Planejado                               |
| **V6** — Horário Espelho     | Simetria temporal (10:30 ↔ 14:30) | 🔜 Planejado                               |
| **V7** — Filtro de Sequência | Pior sequência de Hits            | ✅ **Implementado no Validator** (Corte 4) |

> **Nota:** V7 não é uma variação de mineração — é um **filtro de validação**. Já está implementado no `strategy_validator.py` como Corte 4 (`max_consec_hit >= 3 → REPROVADO`).

---

### 📏 Tabela de Assertividade Alvo (Payout 85%)

| Nível de Sinal       | Win Rate 1ª Entrada | Win Rate Gale 2 | EV Gale 2 | Status     |
| :------------------- | :------------------ | :-------------- | :-------- | :--------- |
| **ELITE (Aprovado)** | ≥ 55%               | ≥ 90%           | > +0.10   | Stake 1.0x |
| **CONDICIONAL**      | < 55% ou EV ≤ 0.10  | ≥ 88%           | > 0.0     | Stake 0.5x |
| **LIXO (Reprovado)** | qualquer            | < 88%           | ≤ 0.0     | Ignorado   |

---

## 5. REGRAS ABSOLUTAS DE CÓDIGO — ANTI-VIBE CODING

> ❌ A IA **NÃO DEVE** fazer nenhuma das ações abaixo. Se fizer, o código será rejeitado.

1. **❌ SEM loops bloqueantes.** Proibido `time.sleep()` e `requests` síncronos. Tudo usa `async/await`.
2. **❌ SEM salvar ticks no banco.** O Supabase recebe **APENAS sinais gerados**. Ticks e candles vivem exclusivamente na RAM (`collections.deque`). Nunca no disco, nunca no banco.
3. **❌ SEM relógio local.** Proibido `datetime.now()` para lógica de trading. Obrigatório usar o `epoch timestamp` que vem no JSON da Deriv.
4. **❌ SEM objetos complexos na RAM.** O deque de histórico contém apenas listas de `floats` (preços puros). Sem dicionários, sem DataFrames no loop de rede.
5. **❌ SEM indicadores técnicos.** Proibido RSI, MACD, médias móveis ou qualquer ferramenta de AT convencional. Apenas frequências empíricas e Z-Score.

---

# 6. DICIONÁRIO DE DADOS — CONTRATOS ESTREITOS (v3.0)

Toda a estrutura de dados foi desenhada para garantir **Transparência Total**. O sistema não salva apenas a "Win Rate", mas a contagem bruta de cada estágio da série (1ª, G1, G2).

---

## 6.1 Isolamento de Schema

Para evitar o _"Erro Gigante"_ de misturar dados com o sistema Million Bots legado, todas as novas tabelas devem residir no schema:

```
hft_quant
```

---

## 6.2 Tabela: `hft_quant.oracle_results` (A Grade de Inteligência)

Esta tabela armazena a agenda de horários Elite descoberta pelo Agente.

```sql
CREATE TABLE hft_quant.oracle_results (
  id              BIGSERIAL PRIMARY KEY,
  strategy_id     TEXT UNIQUE NOT NULL,   -- Ex: "T1430_SEG_R75_G2"
  ativo           TEXT NOT NULL,          -- Ex: "R_75", "BOOM500"
  hh_mm           TEXT NOT NULL,          -- Horário alvo (Ex: "14:30")
  dia_semana      INT NOT NULL,           -- 0 (Seg) a 6 (Dom)
  direcao         TEXT NOT NULL,          -- "CALL" ou "PUT"

  -- Métricas de Assertividade (Fator de Confiança)
  n_total         INT NOT NULL,           -- Total de ocorrências em 30 dias
  win_rate_1a     FLOAT NOT NULL,         -- % de acerto sem Gale
  win_rate_g1     FLOAT NOT NULL,         -- % de acerto acumulado até Gale 1
  win_rate_g2     FLOAT NOT NULL,         -- % de acerto acumulado até Gale 2 (Elite)
  n_hit           INT NOT NULL,           -- Qtd de vezes que deu LOSS no G2

  -- Scores e Status
  score_30_7      FLOAT NOT NULL,         -- Média ponderada recência/histórico
  status          TEXT NOT NULL,          -- "APROVADO" | "CONDICIONAL" | "REPROVADO"
  sniper_active   BOOLEAN DEFAULT FALSE,  -- Controle de ativação pelo cliente

  config_otimizada JSONB,                 -- Metadados: { "tipo": "V1", "max_gale": 2 }
  last_update     TIMESTAMPTZ DEFAULT NOW()
);
```

```sql
create table public.hft_oracle_results (
  id bigserial not null,
  ativo text not null,
  estrategia text not null,
  win_rate numeric not null,
  n_amostral integer not null,
  ev_real numeric not null,
  edge_vs_be numeric not null,
  status text not null,
  config_otimizada jsonb null,
  last_update timestamp with time zone null default now(),
  p_value numeric null,
  win_rate_gale1 numeric null,
  ev_gale1 numeric null,
  strategy_id text null,
  sharpe numeric null,
  sizing_override numeric null,
  valid_until bigint null,
  constraint hft_oracle_results_pkey primary key (id),
  constraint hft_oracle_results_upsert_key unique NULLS not distinct (ativo, estrategia, strategy_id)
) TABLESPACE pg_default;
);
```

## 6.3 Tabela: `agent_cycles`

````sql
create table public.agent_cycles (
  id bigserial not null,
  started_at bigint not null,
  duration_seconds numeric null,
  registros_carregados integer null default 0,
  hipoteses_geradas integer null default 0,
  padroes_minerados integer null default 0,
  aprovadas integer null default 0,
  condicionais integer null default 0,
  reprovadas integer null default 0,
  estrategias_escritas integer null default 0,
  created_at timestamp with time zone null default now(),
  constraint agent_cycles_pkey primary key (id)
) TABLESPACE pg_default;
---

## 6.4 Tabela: `hft_catalogo_estrategias` - Recebe os sinais do Sniper

```sql
create table public.hft_catalogo_estrategias (
  id bigserial not null,
  ativo text not null,
  estrategia text not null,
  direcao text not null,
  p_win_historica numeric not null,
  status text not null,
  timestamp_sinal bigint not null,
  contexto jsonb null,
  created_at timestamp with time zone null default now(),
  constraint hft_catalogo_estrategias_pkey primary key (id)
) TABLESPACE pg_default;
````

---

## 6.5 Schema do campo `contexto` (JSONB)

Este campo é enviado pela VPS no momento do sinal para justificar a entrada no Front-end do cliente.

```json
{
  "win_counts": {
    "direct": 22, // Vitórias de 1ª nos últimos 30 dias
    "gale_1": 5, // Vitórias no Gale 1 nos últimos 30 dias
    "gale_2": 2, // Vitórias no Gale 2 nos últimos 30 dias
    "hits": 1 // Quantidade de erros totais (Hit Gale 2)
  },
  "metrics": {
    "win_rate_g2": 0.967, // Assertividade final acumulada
    "recency_7d": 0.92, // Assertividade da última semana
    "score_30_7": 0.95 // Score ponderado final
  },
  "execution": {
    "v_strategy": "V1_MINUTO_OURO", // Qual variação disparou o sinal
    "max_gale_allowed": 2, // Trava de segurança de Gale
    "hh_mm_target": "14:30" // Horário agendado
  }
}
```

---

## 7 Schema do `config.json` (A Agenda do Sniper)

Gerado pelo Oráculo no PC local e lido pela **VPS Sniper**. Este arquivo contém a _"Escala de Trabalho"_ do robô.

```json
{
  "T1430_SEG_R75_G2": {
    "ativo": "R_75",
    "hh_mm": "14:30",
    "dia_semana": 0, // 0 = Segunda-feira
    "direcao": "CALL",
    "p_win_g2": 0.97, // 97% de acerto histórico
    "ev_g2": 0.643, // Valor esperado considerando custo do Gale 2
    "kelly_quarter": 0.015, // Sizing sugerido (1.5% da banca)
    "n_total": 30, // Ocorrências no mês
    "sizing_override": 1.0, // Multiplicador de stake (1.0 = normal, 0.5 = condicional)
    "status": "APROVADO"
  },
  "T1505_SEG_BOOM500_G2": {
    "ativo": "BOOM500",
    "hh_mm": "15:05",
    "dia_semana": 0,
    "direcao": "PUT",
    "p_win_g2": 0.95,
    "ev_g2": 0.582,
    "kelly_quarter": 0.012,
    "n_total": 28,
    "sizing_override": 1.0,
    "status": "APROVADO"
  }
}
```

## 8. ESTRUTURA DO CATÁLOGO — 10 CAMPOS OBRIGATÓRIOS (v3.0)

Esta estrutura reside no SQLite local (`catalog/catalog.db`). Ela foi desenhada para ser uma **Matriz Temporal Profunda**, onde cada linha carrega o resultado do presente e o desfecho do futuro (G1 e G2), permitindo cálculos de Win Rate instantâneos sem processamento pesado.

| #   | Campo          | Tipo     | Descrição Prática                                                             |
| --- | -------------- | -------- | ----------------------------------------------------------------------------- |
| 1   | `timestamp`    | `BIGINT` | Epoch oficial retornado pela Deriv (Chave primária com Ativo).                |
| 2   | `ativo`        | `TEXT`   | Símbolo do índice (Ex: `R_75`, `BOOM500`, `CRASH1000`).                       |
| 3   | `hh_mm`        | `TEXT`   | A **Chave Mestra**: Horário no formato `HH:MM` (Ex: `"14:35"`).               |
| 4   | `dia_semana`   | `INT`    | Dia da semana de `0` (Segunda) a `6` (Domingo).                               |
| 5   | `mhi_seq`      | `TEXT`   | Cores das 3 velas anteriores (Ex: `"V-V-R"`). Fundamental para Estratégia V2. |
| 6   | `resultado_1a` | `TEXT`   | Cor da vela no minuto do sinal (`A` = Verde / `B` = Vermelha).                |
| 7   | `resultado_g1` | `TEXT`   | Cor da vela no minuto `T+1` (Para cálculo automático de Gale 1).              |
| 8   | `resultado_g2` | `TEXT`   | Cor da vela no minuto `T+2` (Para cálculo automático de Gale 2).              |
| 9   | `sessao`       | `TEXT`   | Sessão ativa: `Asian`, `London`, `Overlap` ou `NY`.                           |
| 10  | `magnitude`    | `TEXT`   | Filtro de Volatilidade: `"DENTRO"` ou `"FORA"` do range médio de 20 períodos. |

---

## 8. MÉTRICAS DE VALIDAÇÃO DE EDGE (Curadoria do Chief)

O Oráculo Quant atua sob um regime de **Exclusão Estatística**. Somente horários que provarem matematicamente que o lucro das vitórias cobre o custo do _"Hit"_ (Loss no Gale 2) são enviados para a VPS.

---

## 8. MÉTRICAS DE VALIDAÇÃO DE EDGE (O "Juiz de Rua")

O Oráculo Quant não usa mais um "sistema de pontuação" complexo e acadêmico. Ele opera como um trader institucional prático, aplicando **Cortes Obrigatórios (Eliminatórios)** e uma **Regra de Ouro** baseada na Lucratividade (EV) e Qualidade da Entrada (Independência do Gale).

---

### 8.1 Cortes Obrigatórios (O que gera um REPROVADO imediato)

Qualquer padrão catalogado deve sobreviver a todos os 4 cortes abaixo. Se falhar em apenas um, a estratégia é sumariamente **REPROVADA** e o Sniper a ignorará.

| #   | Critério de Sobrevivência | Regra de Corte      | Motivo Técnico                                                                                                   |
| --- | ------------------------- | ------------------- | ---------------------------------------------------------------------------------------------------------------- |
| 1   | Amostragem Mínima         | N < 15              | Dados insuficientes. Operar com menos de 15 repetições em 30 dias é jogo de azar.                                |
| 2   | Assertividade Segura      | Win Rate G2 < 88%   | Ficar abaixo de 88% no Gale 2 em M1 expõe o capital a um Risco de Ruína altíssimo.                               |
| 3   | Custo do Hit (EV)         | EV_Gale2 <= 0.0     | O lucro acumulado das vitórias na série **NÃO PAGA** o custo de um "Hit" (8.2 unidades). Matematicamente falido. |
| 4   | Filtro de Sequência (V7)  | max_consec_hit >= 3 | Padrão perigoso. O horário já errou o Gale 2 três vezes seguidas no passado.                                     |

---

### 8.2 A Regra de Ouro (O Selo de APROVADO - Elite)

Para receber o status máximo e permitir que o Sniper entre com **Stake 100% (1.0x)**, a estratégia deve passar nos cortes acima **E** bater **TODAS** estas três metas simultaneamente:

- **EV Sólido:** EV_Gale2 > +0.10 — A estratégia imprime dinheiro real a longo prazo.
- **Assertividade Elite:** Win Rate G2 >= 90% — Gordura de sobra para absorver a variância do mercado aberto.
- **Independência do Gale:** Win Rate 1ª Entrada >= 55% — A estratégia entra certo logo de cara. Ela não é refém do Gale para dar lucro.

---

### 8.3 A Regra de Contenção (O Selo CONDICIONAL)

Se a estratégia passou pelos 4 Cortes Obrigatórios (ou seja, ela é matematicamente viável e dá lucro), mas falhou em algum detalhe da "Regra de Ouro" (ex: tem EV positivo, mas só acerta 40% de primeira), ela entra na **Contenção**.

- **Ação:** O Sniper recebe o sinal, mas opera com **Stake Reduzida (0.5x)**.
- **Trava Anti-Duplicata:** Se um ativo (ex: R_100), no mesmo horário (ex: 14:10) e na mesma direção (CALL), for descoberto duas vezes por variações diferentes (ex: V1 e V4), a segunda descoberta é forçada para **CONDICIONAL** para evitar alavancagem dobrada do cliente no mesmo exato minuto.

---

### 8.4 Matriz de Decisão Resumida

| Status                      | Condição                                                 | Stake    |
| --------------------------- | -------------------------------------------------------- | -------- |
| ✅ **APROVADO (Elite)**     | Passa nos Cortes + Bate a Regra de Ouro                  | 1.0x     |
| ⚠️ **CONDICIONAL (Seguro)** | Passa nos Cortes + Falha na Regra de Ouro ou é Duplicata | 0.5x     |
| ❌ **REPROVADO (Lixo)**     | Cai em qualquer um dos 4 Cortes Obrigatórios             | Ignorado |

## 9. REQUISITOS NÃO-FUNCIONAIS (Performance Sniper)

Como o sistema opera por **Agenda (HH:MM)**, a carga sobre a infraestrutura é drasticamente menor, permitindo latência quase zero.

| Métrica                      | Alvo de Performance | Motivo Técnico                                                                    |
| ---------------------------- | ------------------- | --------------------------------------------------------------------------------- |
| **RAM (VPS)**                | `< 100MB`           | O Sniper não faz cálculos pesados; apenas monitora o relógio e uma lista JSON.    |
| **CPU (VPS)**                | `< 5%`              | O motor fica em Idle (espera) 99% do tempo, acordando apenas no segundo 50.       |
| **Latência (Gatilho)**       | `< 20ms`            | Tempo entre o relógio bater `:50` e o sinal ser enviado ao Supabase.              |
| **Latência (Ponte)**         | `< 150ms`           | Tempo total do sinal sair da VPS e disparar o clique no PC do cliente.            |
| **Uptime (Disponibilidade)** | `99.9%`             | Uso de Docker Compose com política `restart: always` e Exponential Backoff.       |
| **Precisão Temporal**        | Milissegundos       | Sincronização obrigatória com o epoch da Deriv, ignorando o relógio local da VPS. |

## 10. ROADMAP DE DESENVOLVIMENTO (Ciclo de Vida do Projeto)

O desenvolvimento segue a lógica de **Baixo Acoplamento**: construímos o motor matemático, depois a descoberta de dados e, por fim, a interface de execução.

| Fase | Módulo                         | Objetivo Principal                                                                      |
| ---- | ------------------------------ | --------------------------------------------------------------------------------------- |
| 1    | `core/math_engine.py`          | Implementar cálculos de EV para Séries (Gale 2) e Sizing de Ciclo.                      |
| 2    | `core/data_loader.py`          | Criar a Matriz Temporal (HH:MM) no SQLite local com 30 dias de histórico.               |
| 3    | `core/agent_discovery.py`      | O _"Cérebro"_: minerar as 7 variações (V1-V7) e identificar horários de 95%+.           |
| 4    | `core/sanity_check.py`         | Workflow de Autocorreção: Validar se a contagem de Wins/Hits é matematicamente íntegra. |
| 5    | `core/vps_sniper.py`           | Sniper de Agenda: monitorar o relógio Deriv e disparar sinais agendados.                |
| 6    | `frontend/execution_bridge.ts` | Integrar ao Million Bots: ouvir o Supabase e disparar ordens via Token do cliente.      |

---

## 11. ESTRUTURA DE PASTAS (Arquitetura Profissional)

```
projeto_oracle_quant/
│
├── PRD.md                      ← Este documento (Fonte da Verdade)
├── config.json                 ← Agenda de Elite gerada (HH:MM + Direção)
│
├── core/                       ← Motores Python (Back-end / VPS)
│   ├── math_engine.py          ← Cálculos de EV e Gale 2
│   ├── data_loader.py          ← Ingestão profunda (43.200 velas/ativo)
│   ├── pattern_miner.py        ← Mineração da Grade Horária
│   ├── agent_discovery.py      ← Orquestrador do Agente de I.A.
│   ├── sanity_check.py         ← Auditor de integridade (Anti-Lombra)
│   ├── vps_sniper.py           ← Sniper de Agenda (Vigia 24/7)
│   └── database.py             ← Persistência Híbrida (SQLite + Supabase)
│
├── catalog/                    ← Dados Locais (Offline)
│   ├── catalog.db              ← Matriz Temporal de 30 dias (SQLite)
│   └── reports/                ← Relatórios detalhados de cada horário
│
├── frontend/                   ← Interface Million Bots (Next.js / TS)
│   ├── pages/oracle-quant.tsx  ← Nova página do ecossistema
│   ├── components/ExecutionBridge.tsx  ← Ponte de clique automático
│   └── lib/supabase.ts         ← Conexão com Schema hft_quant
│
└── tests/                      ← Suíte de Testes (PyTest)
    ├── test_gale_logic.py      ← Validar shifts de Gale 1 e Gale 2
    └── test_sanity.py          ← Testes de estresse do Auditor
```

---

## 12. PROMPT MESTRE PARA A I.A. (Vibe Coding / Claude Code)

Copie este prompt para iniciar qualquer nova funcionalidade. Ele garante que a I.A. não _"alucine"_ e respeite o seu método de 8 anos.

```
Você é o Tech Lead Sênior do projeto ORACLE QUANT (HFT de Elite).
Leia o arquivo @PRD.md v3.0 antes de agir.

CONFIRME QUE ENTENDEU:
1. O foco é GRADE HORÁRIA (HH:MM) e CICLOS, não indicadores técnicos.
2. O GALE 2 é uma ferramenta estatística de cobertura, com risco total de 8.2 unidades.
3. O workflow exige o Gatekeeper (sanity_check.py) para validar toda matemática.
4. Toda persistência deve ser no Schema hft_quant do Supabase.

TAREFA ATUAL:
[Descreva aqui se quer rodar o Oráculo, ajustar o Sniper ou criar a Ponte de Execução]

REGRAS DE OURO:
- Use Pandas GroupBy para agrupar 30 dias de horários.
- Calcule win_1a, win_g1, win_g2 e n_hit de forma explícita.
- Siga o regime de Context-Driven Development (CDD).
```

---

## 13. INTEGRAÇÃO MILLION BOTS (Veredito do Chief)

### 13.1 Isolamento de Dados (Anti-Erro)

- **Schema `hft_quant`:** Nenhuma tabela do novo sistema será criada no schema `public`. Isso garante que o Million Bots legado continue operando sem risco de conflito de nomes ou migrações corrompidas.
- **Whitelist de Ativos:** O Sniper só processa ativos que o Oráculo carimbou como `APROVADO` no banco de dados.

---

### 13.2 Bridge de Execução (Latência Zero)

- O sinal gerado pela VPS entra no Supabase como um evento de `INSERT`.
- A página **ORACLE QUANT** no Frontend Million Bots mantém uma conexão **WebSocket (Supabase Realtime)** aberta.
- Ao receber o sinal, o componente `ExecutionBridge` verifica o **Token Deriv** do cliente já presente na sessão e envia o frame de compra/venda diretamente para a corretora via **Client-Side** (IP do cliente).

---

### 13.3 Validação de Risco (Proteção de Capital)

- **Check de Stop Loss:** Antes de cada disparo de série (1ª entrada), o sistema consulta o estado global do Million Bots para checar se a meta diária ou o limite de perda foi atingido.
- **Trava de Hit:** Se um sinal de horário resultar em um **HIT** (Loss no Gale 2), o Sniper entra em modo de segurança para aquele ativo específico por **120 minutos**, aguardando a estabilização do ciclo algorítmico.
