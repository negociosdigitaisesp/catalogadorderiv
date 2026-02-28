---
description: Protocolo de Autocorreção e Diagnóstico para evitar loops de erro
---

1. **MAPEAMENTO DE CONTEXTO**: Antes de sugerir qualquer código, abra e leia:
   - `PRD.md` (regras de negócio)
   - Arquivo onde o erro ocorre
   - Schema do banco no `hft_oracle_results`
2. **HIPÓTESES**: Liste 3 motivos técnicos do porquê o erro está ocorrendo (Ex: Erro de shift no Gale, Coluna ausente no Supabase, Variável nula).
3. **ISOLAMENTO**: Crie ou atualize o `core/sanity_check.py` para injetar um dado que PROVE que o erro existe.
4. **CORREÇÃO CIRÚRGICA**: Implemente a correção da Hipótese #1 apenas.
5. **AUDITORIA OBRIGATÓRIA**: Rode `python core/sanity_check.py`.
   - Se falhar: Descarte o código e tente a Hipótese #2.
   - Se passar: Verifique se a mudança não quebrou o `win_rate_g2`.
6. **RESULTADO**: Só entregue a resposta se o teste de sanidade for verde.
