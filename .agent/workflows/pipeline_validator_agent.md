---
description: Pipeline Validator Agent Instructions
---

Você é o agente responsável por validar o pipeline do Auto Quant Discovery.
Sua missão é executar os prompts de validação UM POR VEZ, em ordem, 
esperando aprovação antes de avançar.

REGRA PRINCIPAL: Nunca pule etapas. Nunca rode dois módulos juntos.

=============================================================
SEQUÊNCIA DE EXECUÇÃO OBRIGATÓRIA
=============================================================

ETAPA 0 — LEITURA OBRIGATÓRIA (faça isso AGORA antes de qualquer coisa)
-------------------------------------------------------------
Leia estes arquivos nesta ordem exata:
1. @PRD.md
2. @agente/core/data_loader.py
3. @agente/core/hypothesis_generator.py
4. @agente/core/pattern_miner.py
5. @agente/core/strategy_validator.py
6. @agente/core/strategy_writer.py
7. @agente/core/agent_discovery.py

Depois de ler, responda APENAS:
"LEITURA CONCLUÍDA — aguardando comando para iniciar ETAPA 1"

Não faça mais nada até eu dizer "pode ir".

=============================================================
ETAPA 1 — Validar DataLoader (M0)
=============================================================
(Execute apenas quando eu disser "pode ir" após ETAPA 0)

Abra @agente/core/data_loader.py e responda cada item abaixo com ✅ OK ou ❌ FALHOU + linha + motivo + correção:

[ ] 1. load_or_fetch verifica se catalog.db já existe antes de baixar?
[ ] 2. Se o catalog.db existe, fresco (<24h) E profundo (>=40k candles/ativo), usa cache sem baixar nada?
[ ] 3. O download acontece UMA ÚNICA VEZ e os dados ficam no SQLite local?
[ ] 4. parse_candles_to_catalog gera: timestamp, ativo, hh_mm, dia_semana, cor_atual, mhi_seq, proxima_1, proxima_2, proxima_3, tendencia_m5, tendencia_m15?
[ ] 5. proxima_1, proxima_2 e proxima_3 contêm APENAS "VERDE", "VERMELHA" ou "?"? Nunca NaN?
[ ] 6. mhi_seq usa as 3 velas ANTERIORES (shift para trás), não as próximas?
[ ] 7. Epoch de cache vem de time.time(), nunca de datetime.now()?

Ao final escreva:
- "M0 APROVADO — aguardando comando para ETAPA 2" (se todos OK)
- "M0 REPROVADO — listando correções necessárias" (se algum falhou)

Se REPROVADO: aplique SOMENTE as correções dos itens que falharam.
Não mexa em nada além disso.
Depois diga: "Correções aplicadas — aguardando confirmação para revalidar M0"

=============================================================
ETAPA 2 — Validar HypothesisGenerator (M1)
=============================================================
(Execute apenas quando eu disser "pode ir" após M0 APROVADO)

Abra @agente/core/hypothesis_generator.py e responda:

[ ] 1. generate_hypotheses usa SOMENTE: hh_mm, dia_semana, cor_atual, mhi_seq, tendencia_m5, tendencia_m15? Zero indicadores técnicos?
[ ] 2. Edge = p_win_condicional - p_win_ativo (por ativo), não global?
[ ] 3. Grupos com N < min_n são descartados ANTES de calcular edge?
[ ] 4. Prioridade = edge_bruto * log(N)?
[ ] 5. Hipóteses com edge_bruto < min_edge são descartadas antes de entrar na lista?
[ ] 6. Lista final: máximo 200 itens, ordenada maior→menor prioridade?
[ ] 7. Nenhuma hipótese com p_win_condicional >= 1.0 pode passar?

Ao final: "M1 APROVADO — aguardando comando para ETAPA 3" ou "M1 REPROVADO — listando correções"

=============================================================
ETAPA 3 — Validar PatternMiner (M2) — CRÍTICO
=============================================================
(Execute apenas quando eu disser "pode ir" após M1 APROVADO)

Este é o módulo mais perigoso. Erros aqui geram win rate 100% e dados irreais.

Abra @agente/core/pattern_miner.py e responda:

[ ] 1. INVARIANTE: n_1a + n_gale1 + n_gale2 + n_hit == n_valid para TODOS os grupos?
[ ] 2. As máscaras booleanas seguem esta lógica EXATA:
       win_1a   = proxima_1 == win_color AND ciclo completo
       win_gale1 = ~win_1a AND proxima_2 == win_color AND ciclo completo
       win_gale2 = ~win_1a AND ~win_gale1 AND proxima_3 == win_color
       hit       = ~win_1a AND ~win_gale1 AND ~win_gale2
[ ] 3. Ciclo "completo" = proxima_1, proxima_2 E proxima_3 todos diferentes de "?"?
[ ] 4. wr_gale2 = 1.0 - p_hit? (não calculado de outra forma)
[ ] 5. Split TRAIN/TEST existe em V3 e V4? Direção só no TRAIN, WR só no TEST?
[ ] 6. Existe guard clause explícita que impede wr_gale2 >= 1.0 de sair do módulo?
[ ] 7. EV = (p_1a * 0.85) + (p_gale1 * 0.87) + (p_gale2 * 0.89) - (p_hit * 8.2)?
[ ] 8. n_win_1a, n_win_g1, n_win_g2, n_hit em _adaptar_para_pipeline são inteiros reais, não proporções?
[ ] 9. TODOS os métodos mine_v1, mine_v2, mine_v3, mine_v4 começam com df = df.copy()?

Ao final: "M2 APROVADO — aguardando comando para ETAPA 4" ou "M2 REPROVADO — listando correções"

=============================================================
ETAPA 4 — Validar StrategyValidator (M3)
=============================================================
(Execute apenas quando eu disser "pode ir" após M2 APROVADO)

Abra @agente/core/strategy_validator.py e responda:

[ ] 1. APROVADO exige os 3 juntos: wr_gale2 >= 0.95 E N >= 20 E score_ponderado >= 0.90?
[ ] 2. CONDICIONAL: wr_gale2 >= 0.90 E N >= 20? (N < 20 = REPROVADO mesmo com WR alto)
[ ] 3. Filtro V7: p_hit usado para calcular sequência máxima de hits? >= 3 consecutivos = REPROVADO?
[ ] 4. hit_rate no resultado = p_hit exato do PatternMiner, sem recalcular?
[ ] 5. stake_multiplier: APROVADO=1.0, CONDICIONAL=0.5, REPROVADO=0.0?
[ ] 6. validate_batch retorna dict com "aprovados", "condicionais", "reprovados"? Nenhuma oportunidade some?
[ ] 7. kelly_quarter = stake / 4.0?

Ao final: "M3 APROVADO — aguardando comando para ETAPA 5" ou "M3 REPROVADO — listando correções"

=============================================================
ETAPA 5 — Validar StrategyWriter (M4)
=============================================================
(Execute apenas quando eu disser "pode ir" após M3 APROVADO)

Abra @agente/core/strategy_writer.py e responda:

[ ] 1. generate_strategy_id gera: T{HHMM}_{DIA}_{ATIVO}_G2? Ex: T1430_SEG_R75_G2?
[ ] 2. build_config_entry inclui n_total, n_win_1a, n_win_g1, n_win_g2, n_hit como inteiros?
[ ] 3. update_config_json remove entradas sem campo hh_mm (limpeza Z-Score legado)?
[ ] 4. valid_until = descoberta_em + (90 * 24 * 3600)?
[ ] 5. write_all processa APROVADOS e CONDICIONAIS, ignora REPROVADOS silenciosamente?
[ ] 6. Campo "variacao" no config.json indica V1, V2, V3 ou V4?

Ao final: "M4 APROVADO — aguardando comando para ETAPA 6" ou "M4 REPROVADO — listando correções"

=============================================================
ETAPA 6 — Validar Orquestrador (AgentDiscovery) — ÚLTIMA ETAPA
=============================================================
(Execute SOMENTE se M0+M1+M2+M3+M4 estiverem todos APROVADOS)
(Execute apenas quando eu disser "pode ir")

Abra @agente/core/agent_discovery.py e responda:

[ ] 1. Ordem do pipeline: DataLoader → HypothesisGenerator → PatternMiner → StrategyValidator → StrategyWriter?
[ ] 2. DataFrame vazio do DataLoader = ciclo encerra ANTES dos outros módulos?
[ ] 3. Lista vazia do PatternMiner = ciclo encerra ANTES do StrategyValidator?
[ ] 4. Tabela agent_cycles recebe: started_at, duration_seconds, registros_carregados, hipoteses_geradas, padroes_minerados, aprovadas, condicionais, reprovadas, estrategias_escritas?
[ ] 5. Falha no Supabase NÃO interrompe o ciclo (NullSupabaseClient)?
[ ] 6. run_cycle é async com await correto em load_or_fetch e write_all?

Ao final:
- "SISTEMA COMPLETO — PRONTO PARA PRODUÇÃO" (todos os 6 módulos aprovados)
- "SISTEMA BLOQUEADO — módulos pendentes: [lista]"

=============================================================
REGRAS DE COMPORTAMENTO DO AGENTE
=============================================================

1. Sempre espere o comando "pode ir" entre etapas
2. Nunca corrija dois módulos ao mesmo tempo
3. Quando corrigir: mostre SOMENTE o bloco de código alterado, não o arquivo inteiro
4. Após cada correção diga quantos itens foram corrigidos e quais
5. Se aparecer win rate 100% em qualquer etapa: PARE TUDO e execute o diagnóstico:
   - Verifique se shift() está sendo usado dentro do PatternMiner (não pode)
   - Verifique se a invariante n_1a+n_gale1+n_gale2+n_hit == n_valid fecha
   - Só continue após confirmar que o irreal foi eliminado
6. Nunca rode o AgentDiscovery completo antes de todas as etapas estarem aprovadas