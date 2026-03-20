# PROMPT — Implementar Modo Supremo no Frontend (Isolado)

## CONTEXTO DO PROJETO

Você está trabalhando no **Oracle Quant Frontend** (Next.js + TypeScript + Tailwind CSS).
Leia este documento na íntegra antes de escrever uma linha de código.

---

## REGRAS ABSOLUTAS (não negociáveis)

1. **NÃO toque em nenhum arquivo existente.** Zero modificações em:
   - `hooks/useOracleResults.ts`
   - `components/OracleTable.tsx`
   - `components/SignalCard.tsx`
   - `components/StatusBadge.tsx`
   - `types/discovery.ts`
   - `app/page.tsx`
   - `app/layout.tsx`
   - Qualquer outro arquivo já existente

2. **Crie apenas arquivos novos**, em caminhos novos.

3. **Não instale dependências novas.** Use apenas o que já existe:
   - `react`, `next`, `typescript`
   - `@supabase/supabase-js` (já instalado, client em `lib/supabaseClient`)
   - `lucide-react` (ícones)
   - `cn()` de `@/lib/utils`
   - `tailwindcss` com o design system existente

---

## O QUE VOCÊ VAI CONSTRUIR

Uma nova seção chamada **"Modo Supremo"** — uma página/aba isolada que exibe
os sinais de mais alta qualidade da nova arquitetura Data Lake.

**Esses sinais têm uma diferença crítica do sistema antigo:**
- `modo_operacao: "SEM_GALE"` → sem martingale, flat bet
- `max_gale: 0` → o frontend NUNCA deve exibir G1/G2 para esses sinais
- `stake_leverage: 1.2 | 1.5 | 2.0` → multiplicador de stake elevado
- `status: "SUPREMO"` → nível acima de APROVADO

---

## ARQUITETURA DA FONTE DE DADOS

### Supabase — Schema hft_lake (não é public)

A view `hft_lake.vw_grade_suprema` vive em um schema separado.
O PostgREST do Supabase só expõe `public` por padrão.

**SOLUÇÃO: usar RPC (função SQL no schema public).**

Antes de escrever o frontend, o usuário precisa rodar este SQL no Supabase SQL Editor:

```sql
-- Criar função RPC pública que lê o schema hft_lake
CREATE OR REPLACE FUNCTION public.get_grade_suprema()
RETURNS TABLE (
  ativo           TEXT,
  hh_mm           TEXT,
  direcao         TEXT,
  n_filtros       BIGINT,
  filtros_aprovados TEXT,
  tem_fv6         BOOLEAN,
  wr_1a           NUMERIC,
  wr_g2           NUMERIC,
  ev_gale2        NUMERIC,
  ev_1a_puro      NUMERIC,
  score_30_7      NUMERIC,
  n_total         INT,
  n_hit           INT,
  stake_leverage  NUMERIC,
  ev_fv6          NUMERIC,
  wr_1a_fv6       NUMERIC,
  assimetria_1a   NUMERIC,
  status          TEXT,
  modo_operacao   TEXT,
  stake_multiplier NUMERIC,
  max_gale        INT
)
LANGUAGE sql
SECURITY DEFINER
AS $$
  SELECT
    ativo, hh_mm, direcao,
    n_filtros, filtros_aprovados, tem_fv6,
    wr_1a, wr_g2, ev_gale2, ev_1a_puro, score_30_7,
    n_total, n_hit,
    stake_leverage, ev_fv6, wr_1a_fv6, assimetria_1a,
    status, modo_operacao, stake_multiplier, max_gale
  FROM hft_lake.vw_grade_suprema
  WHERE status IN ('SUPREMO', 'APROVADO', 'CONDICIONAL')
  ORDER BY
    CASE WHEN tem_fv6 THEN 0 ELSE 1 END,
    n_filtros DESC,
    ev_gale2 DESC NULLS LAST;
$$;
```

---

## SHAPE DOS DADOS (o que vem do Supabase)

```typescript
interface SupremoResult {
  ativo: string;            // "R_10", "R_25", "R_50", "R_75", "R_100"
  hh_mm: string;            // "14:30"
  direcao: "CALL" | "PUT";

  n_filtros: number;        // quantos filtros FV1-FV6 aprovaram
  filtros_aprovados: string;// "FV1, FV2, FV4, FV6"
  tem_fv6: boolean;         // TRUE = modo supremo (sem gale)

  wr_1a: number;            // 0.72 = 72% de acerto na 1ª entrada
  wr_g2: number;            // 0.95 = 95% acumulado com Gale 2
  ev_gale2: number;         // EV do ciclo Gale 2 (referência)
  ev_1a_puro: number;       // EV do flat bet SEM gale (+0.258)
  score_30_7: number;       // score de consistência temporal

  n_total: number;          // amostras em 30 dias
  n_hit: number;            // perdas totais em 30 dias

  stake_leverage: number;   // 1.2 | 1.5 | 2.0
  ev_fv6: number | null;    // EV específico do filtro FV6
  wr_1a_fv6: number | null; // WR_1a específico do FV6
  assimetria_1a: number | null; // gap CALL vs PUT no mesmo horário

  status: "SUPREMO" | "APROVADO" | "CONDICIONAL";
  modo_operacao: "SEM_GALE" | "GALE_2";
  stake_multiplier: number; // 2.0 | 1.0 | 0.5
  max_gale: number;         // 0 para SUPREMO, 2 para demais
}
```

---

## DESIGN SYSTEM EXISTENTE (use exatamente estes tokens)

```
Cores Tailwind configuradas no projeto:
  dark-bg       → fundo principal
  dark-card     → cards
  dark-border   → bordas
  dark-text     → texto secundário
  dark-accent   → azul (destaque)
  signal-win    → verde (CALL, vitória)
  signal-loss   → vermelho (PUT, perda)
  signal-pre    → amarelo (PRE_SIGNAL, condicional)
  signal-neutral→ cinza (neutro)

Utilitários:
  cn() de @/lib/utils  → combina classes Tailwind

Ícones (lucide-react):
  Zap, ShieldCheck, AlertTriangle, Activity,
  ArrowUpRight, ArrowDownRight, Percent,
  TrendingUp, Lock, Unlock
```

**Cor para SUPREMO:** use `amber-400` / `yellow-400` (ouro).
Não existe uma classe `signal-supremo` — use `text-amber-400`, `bg-amber-400/10`, `border-amber-400/30`.

---

## ARQUIVOS A CRIAR (apenas estes 3)

### 1. `types/supremo.ts`
Tipo TypeScript `SupremoResult` conforme o shape acima.

### 2. `hooks/useSupremoResults.ts`
Hook que:
- Chama `supabase.rpc('get_grade_suprema')` (não `.from(...)`)
- Retorna `{ results, loading, error, supremos, aprovados, condicionais }`
- `supremos` = filtro onde `tem_fv6 === true`
- SEM Realtime subscription (dados estáticos, atualizam só quando o pipeline roda)

### 3. `app/supremo/page.tsx`
Página completa com:
- Header com título "Modo Supremo" + badge SUPREMO dourado
- Explicação curta: "Operações sem martingale. Entre, ganhe ou pare."
- Contador de sinais por status (SUPREMO / APROVADO / CONDICIONAL)
- Tabela dos resultados com colunas:
  - Ativo
  - Horário (hh_mm)
  - Direção (badge verde/vermelho)
  - WR 1ª Entrada (destaque — essa é a métrica principal)
  - EV Flat Bet (ev_1a_puro) — em verde se > 0
  - Stake (stake_leverage com ícone ⚡)
  - Max Gale (badge "SEM GALE" em âmbar se max_gale = 0, senão "G2")
  - Filtros aprovados (badge pequeno com n_filtros e filtros_aprovados)
  - Status (badge SUPREMO em âmbar, APROVADO em verde, CONDICIONAL em amarelo)

---

## LÓGICA DE NEGÓCIO CRÍTICA (explique visualmente no UI)

```
SE max_gale === 0 (SUPREMO / SEM_GALE):
  → Badge "SEM GALE" em âmbar
  → Stake = stake_leverage (1.2x, 1.5x ou 2.0x)
  → Tooltip: "Entre com stake elevado. Se perder, PARE. Não há Gale."
  → EV exibido = ev_1a_puro (não ev_gale2)
  → WR exibido = wr_1a (não wr_g2)

SE max_gale === 2 (APROVADO / GALE_2):
  → Badge "G2" em verde/amarelo
  → Stake = stake_multiplier (1.0x ou 0.5x)
  → EV exibido = ev_gale2
  → WR exibido = wr_g2
```

---

## EXEMPLO DE CARD SUPREMO (referência visual)

```
┌─────────────────────────────────────────────────────────┐
│ ⚡ SUPREMO          R_75  14:30  ▲ CALL                 │
│─────────────────────────────────────────────────────────│
│  WR 1ª Entrada    EV Flat Bet    Stake       Max Gale   │
│  72.4%            +0.258         2.0x ⚡     SEM GALE   │
│─────────────────────────────────────────────────────────│
│  Amostras: 25     Hits 30d: 1    Filtros: FV2, FV3, FV6 │
│  Assimetria CALL vs PUT: +18pp                          │
└─────────────────────────────────────────────────────────┘
```

---

## ROTA DA NOVA PÁGINA

A nova página estará em:
```
/supremo
```

Acessível via `http://localhost:3000/supremo`

Não adicione link de navegação em nenhum componente existente.
O usuário acessa diretamente pela URL por enquanto.

---

## CHECKLIST DE VALIDAÇÃO

Antes de entregar, confirme:
- [ ] Zero modificações em arquivos existentes
- [ ] `types/supremo.ts` exporta `SupremoResult`
- [ ] `hooks/useSupremoResults.ts` usa `.rpc('get_grade_suprema')`
- [ ] `app/supremo/page.tsx` existe e renderiza sem erros
- [ ] Sinais com `max_gale = 0` exibem "SEM GALE" (nunca "G2")
- [ ] EV exibido para SUPREMO é `ev_1a_puro`, não `ev_gale2`
- [ ] WR exibido para SUPREMO é `wr_1a`, não `wr_g2`
- [ ] Stake exibido para SUPREMO é `stake_leverage`
- [ ] Badge SUPREMO usa cor âmbar/dourada (amber-400)
- [ ] Página funciona mesmo se a tabela estiver vazia (estado vazio tratado)

---

## MENSAGEM DE ESTADO VAZIO

Se não houver dados (view vazia ou pipeline não rodou ainda):

```
Nenhum sinal Supremo disponível.
Execute: python data_lake/supremo_runner.py
```

---

*Este prompt foi gerado com base na leitura completa de:*
- *`PRD.md` e `PRD_DATA_LAKE.md`*
- *`data_lake/sql/09_view_fv6_minuto_supremo.sql`*
- *`data_lake/sql/10_view_grade_suprema.sql`*
- *`frontend/hooks/useOracleResults.ts`*
- *`frontend/components/OracleTable.tsx`*
- *`frontend/components/SignalCard.tsx`*
- *`frontend/types/discovery.ts`*
- *`frontend/lib/utils.ts`*
