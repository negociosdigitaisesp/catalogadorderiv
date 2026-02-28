---
description: Execução do ciclo completo de descoberta quantitativa (Oráculo)
---

1. **LOADER**: Execute `DataLoader` para garantir 30 dias de histórico M1.
2. **CLEANING**: Verifique se o banco local SQLite não tem duplicatas de horários.
3. **MINING**: Rode o `PatternMiner` buscando especificamente Grade Horária (HH:MM) e Ciclos de Cor (MHI).
4. **GALE VALIDATION**: Garanta que o cálculo do Gale 2 use risco de 8.2 e shift(-1), shift(-2).
5. **VALIDATOR**: Rode o `StrategyValidator` simplificado (Filtro de Elite 95%+).
6. **PERSISTENCE**: Atualize o `config.json` e faça o bulk_upsert para o Supabase no schema `public`.
7. **DASHBOARD CHECK**: Verifique se os novos sinais estão aparecendo no Dashboard Million Bots.
