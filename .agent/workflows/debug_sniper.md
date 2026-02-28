---
description: Diagnóstico de latência e gatilhos de tempo no Sniper VPS
---

1. **TIME SYNC**: Verifique se o código está usando o `epoch` da Deriv ou o relógio local (Erro crítico se for local).
2. **HEARTBEAT**: Analise os logs do Sniper para ver se o WebSocket está recebendo `{"ping": 1}` a cada 30s.
3. **WHITELIST**: Verifique se o ativo que você espera está marcado como `APROVADO` no `config.json`.
4. **LOG SNIFFING**: Imprima o Z-Score ou o contador de segundos no terminal para ver se o gatilho `:50` está sendo lido.
5. **SUPABASE CONN**: Teste se o `INSERT` no Supabase está retornando erro 400 ou 401.
