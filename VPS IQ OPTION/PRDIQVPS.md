# PRD — IQ Option Executor Multi-Tenant (VPS)

**Versão:** 2.0.0 | **Atualizado:** 2026-03-05 | **Status:** Em Produção

---

## 1. Objetivo

Executar ordens na IQ Option para múltiplos clientes em paralelo, controlado 100% pelo Supabase HFT. A VPS não aceita conexões diretas do frontend — toda comunicação acontece via banco de dados.

**Premissas invioláveis:**

- Sem proxy. Sem extensão Chrome.
- Sem conexão direta frontend → VPS.
- 1 processo isolado por cliente (multiprocessing).
- Nunca crashar por falha de rede externa (Supabase 502, RemoteProtocolError).

---

## 2. Arquitetura Geral

```
[Frontend (Supabase A)]
    ↓ ativa is_running=true em bot_clients
[Supabase HFT B — ypqekkkrfklaqlzhkbwg]
    ↓ poll a cada 5s
[main.py — Supervisor]
    ↓ 1 multiprocessing.Process por cliente ativo
┌──────────────┬──────────────┬──────────────┐
│  Worker      │  Worker      │  Worker      │
│  email_A     │  email_B     │  email_C     │
│  IQ_Option() │  IQ_Option() │  IQ_Option() │
│  WS próprio  │  WS próprio  │  WS próprio  │
└──────────────┴──────────────┴──────────────┘
    ↑ lê sinais de iq_quant_signals (status=CONFIRMED)
    ↓ grava resultado em iq_trade_results
```

**Isolamento:** Cada `multiprocessing.Process` tem address space e socket TCP independente. A IQ Option vê N usuários autenticados separados.

---

## 3. Servidores e Credenciais

| Recurso          | Valor                                            |
| ---------------- | ------------------------------------------------ |
| VPS IP           | `173.212.209.45`                                 |
| VPS User         | `root`                                           |
| VPS Path         | `/root/catalogadorderiv/VPS IQ OPTION/executor/` |
| Python VPS       | `/root/catalogadorderiv/.venv/bin/python`        |
| Supabase HFT URL | `https://ypqekkkrfklaqlzhkbwg.supabase.co`       |
| Log executor     | `/root/catalogadorderiv/logs/executor.log`       |
| Log sniper       | `/root/catalogadorderiv/logs/iq_sniper.log`      |

---

## 4. Schema Supabase HFT (Banco B)

### `bot_clients` — Controle de Clientes

```sql
client_id       TEXT UNIQUE     -- ID do bot
iq_email        TEXT            -- credencial IQ Option
iq_password     TEXT            -- credencial IQ Option
is_running      BOOLEAN         -- TRUE = executor cria worker
balance_type    TEXT            -- 'PRACTICE' | 'REAL'
last_heartbeat  TIMESTAMPTZ     -- atualizado pelo worker a cada 10s
estrategia_ativa TEXT           -- ex: 'T1705' (filtra sinais)
mode            TEXT            -- 'demo' | 'live'
```

### `iq_quant_signals` — Fila de Sinais

```sql
id              BIGSERIAL PK
client_id       TEXT            -- qual worker deve executar
ativo           TEXT            -- ex: 'EURUSD'
direcao         TEXT            -- 'CALL' | 'PUT'
status          TEXT            -- CONFIRMED → executing → executed
estrategia      TEXT            -- ex: 'T1705_up'
timestamp_sinal BIGINT          -- epoch Unix
stake           NUMERIC         -- valor da operação
gale_level      INT             -- 0=base, 1=G1, 2=G2
resultado       TEXT            -- 'win' | 'loss'
contexto        JSONB
```

### `iq_session_config` — Configuração de Risco por Cliente

```sql
client_id TEXT UNIQUE, stake NUMERIC (def 1.0),
stop_win NUMERIC (def 50.0), stop_loss NUMERIC (def 25.0),
martingale_on BOOLEAN, iq_email TEXT, iq_password TEXT
```

### `iq_trade_results` — Histórico (TTL 24h)

```sql
client_id, signal_id, ativo, direcao, stake,
gale_level, resultado, profit, estrategia_id,
executed_at, expires_at
```

### `vw_iq_session_stats` — PnL das últimas 24h

Usada pelo worker para calcular stop_win/stop_loss em tempo real.

---

## 5. Módulos do Executor

### `main.py` — Supervisor

- Loop infinito, poll 2s (30s backoff em erro)
- Detecta `is_running=true` em `bot_clients`
- Lança 1 `multiprocessing.Process` por cliente novo
- Termina processos de clientes desativados
- Try/except global — nunca crashar por rede

### `worker.py` — Worker por Cliente

- Conecta IQ Option via WebSocket (3 tentativas; falha total → `is_running=false`)
- **Loop principal (mínimo 5s entre ciclos):**
  1. `is_client_running()` — fallback `True`, circuit breaker 10 falhas
  2. Heartbeat a cada 10s
  3. WebSocket check → reconecta se caído
  4. Busca sinais `CONFIRMED` em `iq_quant_signals`
  5. Verifica stop_win/stop_loss via `get_session_pnl()`
  6. Executa `api.buy()` — lock: 1 ativo por vez
  7. Aguarda resultado (polling 0.5s, timeout 90s)
  8. Grava em `iq_trade_results` + atualiza status do sinal

### `supabase_client.py` — Camada de Rede Blindada

- **`_safe_request()`**: retry 3x, backoff 2s→4s→8s
- Captura: `HTTPStatusError`, `RequestError`, `RemoteProtocolError`
- Recria `http_client` na penúltima tentativa
- **Nunca lança exceção**

**Fallbacks:**

| Função                 | Fallback                                      |
| ---------------------- | --------------------------------------------- |
| `get_active_clients()` | `[]`                                          |
| `is_client_running()`  | `True`                                        |
| `get_session_config()` | defaults (stake=1, stop_win=50, stop_loss=25) |
| `get_session_pnl()`    | `0.0`                                         |
| `patch_signal()`       | `0` (sem crash)                               |
| `update_heartbeat()`   | noop                                          |

### `monitor.py` — AlertManager

| Alerta             | Trigger                        | Canal              |
| ------------------ | ------------------------------ | ------------------ |
| `LOGIN_FAILURE`    | 3 falhas consecutivas de login | Discord + CRITICAL |
| `SUPABASE_DOWN`    | Inacessível >5 min             | Discord + CRITICAL |
| `DUPLICATE_WORKER` | >1 processo por cliente        | Discord + CRITICAL |

Config: `ALERT_DISCORD_WEBHOOK`, `ALERT_MAX_LOGIN_FAILURES`, `ALERT_MAX_SUPABASE_DOWN_MIN`

### `config.py`

```python
POLL_INTERVAL_SEC      = 2     # ciclo do supervisor
SIGNAL_WINDOW_SEC      = 300   # descarta sinais > 5min
HEARTBEAT_INTERVAL_SEC = 10
MAX_RETRIES            = 3
RETRY_BASE_DELAY       = 2     # backoff: 2s, 4s, 8s
```

---

## 6. Fluxo Completo

```
1. Frontend → bot_clients: is_running=true
2. Supervisor detecta → Process(run_client_worker)
3. Worker conecta IQ Option (WebSocket)
4. Loop 5s:
   ├─ is_client_running? → False = encerra
   ├─ heartbeat
   ├─ get_confirmed_signals → lista
   ├─ stop_win/stop_loss check
   └─ para cada sinal novo:
       patch(executing) → api.buy() → wait_result()
       → insert_trade_result() → patch(executed)
5. Frontend → bot_clients: is_running=false
6. Worker encerra → Supervisor mata processo
```

---

## 7. Deploy

```bash
# Iniciar (na VPS)
pkill -f "python main.py" || true
cd "/root/catalogadorderiv/VPS IQ OPTION/executor"
nohup /root/catalogadorderiv/.venv/bin/python main.py \
  > /root/catalogadorderiv/logs/executor.log 2>&1 &
tail -f /root/catalogadorderiv/logs/executor.log

# Testes (na VPS)
/root/catalogadorderiv/.venv/bin/python -m pytest tests/ -v

# Upload (PowerShell local)
scp "VPS IQ OPTION\executor\supabase_client.py" "root@173.212.209.45:/root/catalogadorderiv/VPS IQ OPTION/executor/"
scp "VPS IQ OPTION\executor\worker.py"          "root@173.212.209.45:/root/catalogadorderiv/VPS IQ OPTION/executor/"
scp "VPS IQ OPTION\executor\main.py"            "root@173.212.209.45:/root/catalogadorderiv/VPS IQ OPTION/executor/"
scp "VPS IQ OPTION\executor\config.py"          "root@173.212.209.45:/root/catalogadorderiv/VPS IQ OPTION/executor/"
```

---

## 8. Resiliência

| Falha                      | Comportamento                              |
| -------------------------- | ------------------------------------------ |
| Supabase 502               | Retry 3x → backoff → supervisor: sleep 30s |
| RemoteProtocolError        | Retry 3x → worker não morre                |
| 10 falhas consecutivas     | Circuit breaker → encerra graciosamente    |
| IQ Option desconecta       | Reconexão automática                       |
| Credencial inválida        | 3 tentativas → is_running=false → Alert    |
| Worker morreu              | Supervisor detecta → recria                |
| Sinal duplicado            | Set idempotente → nunca executa 2x         |
| Sinal preso em "executing" | cleanup_stale_executing(5min)              |

---

## 9. Roadmap

- [ ] Gale automático (G1/G2) baseado em `gale_level` do sinal
- [ ] Discord Webhook ativo em produção
- [ ] SSH por chave (remover senha)
- [ ] Dashboard de PnL consumindo `vw_iq_session_stats`
