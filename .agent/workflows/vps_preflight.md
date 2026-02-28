---
description: 
---

Ao executar o @PRE_FLIGHT_CHECKER, a IA deve:
Criar o script tests/vps_simulation.py.
Este script deve Mockar (fingir) o relógio da Deriv para 10 segundos antes de uma das estratégias aprovadas no seu config.json.
Ele deve rodar o Sniper em modo de teste.
Validação de Sucesso: O teste só passa se o Sniper inserir uma linha na tabela hft_quant.signals e o log no terminal mostrar: [SIMULATION] Signal triggered successfully."