---
description: Sincronização entre o modelo Python e o Schema do Supabase
---

1. **INSPEÇÃO**: Leia o arquivo `core/database.py`.
2. **COMPARAÇÃO**: Compare os dicionários de INSERT com a estrutura SQL do banco.
3. **MIGRATION**: Se houver diferença, gere o script `ALTER TABLE` correspondente.
4. **RELOAD**: Execute o comando de reload do schema no Supabase para limpar o cache da API.
5. **VALIDAÇÃO**: Faça um `INSERT` de teste e delete em seguida para confirmar que a coluna foi aceita.
