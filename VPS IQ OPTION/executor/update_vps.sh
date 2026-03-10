#!/usr/bin/env bash
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# update_vps.sh — Atualiza todos os arquivos do IQ Option Executor na VPS
# 
# Como usar:
#   1. Copie este arquivo para a VPS:
#      scp update_vps.sh root@SEU_IP:/root/iq_executor/
#
#   2. Execute na VPS:
#      cd /root/iq_executor && bash update_vps.sh
#
# Data: 2026-03-06
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

set -euo pipefail

EXECUTOR_DIR="/root/catalogadorderiv/VPS IQ OPTION/executor"
BACKUP_DIR="/root/catalogadorderiv/executor_backup_$(date +%Y%m%d_%H%M%S)"
VENV_PYTHON="/root/catalogadorderiv/.venv/bin/python"
VENV_PIP="/root/catalogadorderiv/.venv/bin/pip"

# Carrega SUPABASE_HFT_KEY do .env para uso na migração SQL
set -a
[ -f "$EXECUTOR_DIR/.env" ]            && source "$EXECUTOR_DIR/.env" 2>/dev/null || true
[ -f /root/catalogadorderiv/.env ]     && source /root/catalogadorderiv/.env 2>/dev/null || true
set +a

SUPABASE_HFT_URL="${SUPABASE_HFT_URL:-https://ypqekkkrfklaqlzhkbwg.supabase.co}"

echo "╔══════════════════════════════════════════════════════════════╗"
echo "║  IQ Option Executor — VPS Update Script (2026-03-06)       ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

# ── 0. Migração SQL — adiciona colunas order_id e gale_level ─────────────────
echo "[0/5] Executando migração SQL ..."
if [ -n "${SUPABASE_HFT_KEY:-}" ]; then
    MIGRATION_SQL="ALTER TABLE iq_gale_state ADD COLUMN IF NOT EXISTS order_id BIGINT; ALTER TABLE iq_gale_state ADD COLUMN IF NOT EXISTS gale_level INT DEFAULT 0;"
    HTTP_STATUS=$(curl -s -o /tmp/migration_result.txt -w "%{http_code}" \
        -X POST "${SUPABASE_HFT_URL}/rest/v1/rpc/run_migration" \
        -H "apikey: ${SUPABASE_HFT_KEY}" \
        -H "Authorization: Bearer ${SUPABASE_HFT_KEY}" \
        -H "Content-Type: application/json" \
        -d "{\"sql\": \"${MIGRATION_SQL}\"}" \
        --max-time 15 2>/dev/null || echo "000")
    if [ "$HTTP_STATUS" = "200" ] || [ "$HTTP_STATUS" = "204" ]; then
        echo "       ✅ Migração SQL aplicada."
    else
        echo "       ⚠️  Migração SQL retornou HTTP $HTTP_STATUS (pode já ter sido aplicada — continuando)."
        cat /tmp/migration_result.txt 2>/dev/null | head -5 || true
    fi
else
    echo "       ⚠️  SUPABASE_HFT_KEY não encontrada — pulando migração SQL."
fi
echo ""

# ── 1. Backup ─────────────────────────────────────────────────────────────────
echo "[1/5] Criando backup em $BACKUP_DIR ..."
mkdir -p "$BACKUP_DIR"
cp -r "$EXECUTOR_DIR"/*.py "$EXECUTOR_DIR"/requirements.txt "$BACKUP_DIR/" 2>/dev/null || true
echo "       ✅ Backup salvo."
echo ""

# ── 2. Parar executor ────────────────────────────────────────────────────────
echo "[2/5] Parando executor atual ..."
pkill -f "python.*main.py" 2>/dev/null || true
sleep 2
echo "       ✅ Executor parado."
echo ""

# ── 3. Escrever arquivos atualizados ─────────────────────────────────────────
echo "[3/5] Atualizando arquivos ..."

# ── config.py ──
cat > "$EXECUTOR_DIR/config.py" << 'PYEOF'
import os

SUPABASE_HFT_URL = "https://ypqekkkrfklaqlzhkbwg.supabase.co"
SUPABASE_HFT_KEY = os.getenv("SUPABASE_HFT_KEY")

IQ_PROXY = os.getenv("IQ_PROXY")

POLL_INTERVAL_SEC      = 10
SIGNAL_WINDOW_SEC      = 300   # descarta sinais mais antigos que 5 min
MAX_CLIENTS            = 50
RECONNECT_ATTEMPTS     = -1    # -1 = infinito
HEARTBEAT_INTERVAL_SEC = 10
MAX_RETRIES            = 3
RETRY_BASE_DELAY       = 2     # segundos (backoff: 2, 4, 8)

assert SUPABASE_HFT_KEY, "SUPABASE_HFT_KEY não definida no ambiente"
PYEOF
echo "       ✓ config.py"

# ── logger.py ──
cat > "$EXECUTOR_DIR/logger.py" << 'PYEOF'
import logging


def get_logger(prefix: str) -> logging.Logger:
    logger = logging.getLogger(prefix)
    if not logger.handlers:
        handler = logging.StreamHandler()
        fmt = logging.Formatter(
            f"%(asctime)s [{prefix}] %(levelname)s %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        handler.setFormatter(fmt)
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)
    return logger
PYEOF
echo "       ✓ logger.py"

# ── supabase_client.py ──
cat > "$EXECUTOR_DIR/supabase_client.py" << 'PYEOF'
"""
supabase_client.py — Camada de rede blindada para o executor IQ.

Todas as chamadas httpx passam por _safe_request(), que:
  1. Tenta até MAX_RETRIES vezes com backoff exponencial.
  2. Captura httpx.HTTPStatusError, httpx.RequestError, RemoteProtocolError.
  3. NUNCA lança exceção para o caller — retorna None em caso de falha total.

Funções de leitura possuem fallback seguro:
  - get_active_clients()     → [] (supervisor não cria novos workers)
  - is_client_running()      → True (worker NÃO se mata à toa)
  - get_session_config()     → _RISK_DEFAULTS (opera com risco padrão)
  - get_session_pnl()        → 0.0 (não força stop)
"""

import logging
import time

import httpx
import httpcore

from config import (
    SUPABASE_HFT_URL,
    SUPABASE_HFT_KEY,
    SIGNAL_WINDOW_SEC,
    MAX_RETRIES,
    RETRY_BASE_DELAY,
)

log = logging.getLogger("SUPABASE_NET")

HEADERS = {
    "apikey": SUPABASE_HFT_KEY,
    "Authorization": f"Bearer {SUPABASE_HFT_KEY}",
    "Content-Type": "application/json",
    "Prefer": "return=minimal",
}

# Usa trust_env=False para ignorar variáveis HTTP_PROXY/HTTPS_PROXY
# e evitar que o Supabase tente passar pelo proxy da IQ Option.
# Timeout aumentado de 10s → 30s para redes instáveis.
http_client = httpx.Client(trust_env=False, headers=HEADERS, timeout=30)


# ═══════════════════════════════════════════════════════════════════════════════
# WRAPPER SEGURO — Nunca lança exceção
# ═══════════════════════════════════════════════════════════════════════════════

def _safe_request(method: str, url: str, *, params=None, json=None, label: str = ""):
    """
    Executa uma requisição httpx com retry + backoff.

    Retorna o objeto httpx.Response em caso de sucesso, ou None em caso de
    falha total após todas as tentativas.

    Args:
        method: "get", "post", "patch"
        url: URL completa do endpoint
        params: query params (dict)
        json: body JSON (dict)
        label: nome da operação para logs
    """
    global http_client

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            fn = getattr(http_client, method)
            kwargs = {}
            if params is not None:
                kwargs["params"] = params
            if json is not None:
                kwargs["json"] = json

            r = fn(url, **kwargs)
            r.raise_for_status()
            return r

        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            log.warning(
                "[%s] HTTP %d (tentativa %d/%d): %s",
                label, status, attempt, MAX_RETRIES, url,
            )

        except (httpx.RemoteProtocolError, httpcore.RemoteProtocolError) as exc:
            log.warning(
                "[%s] RemoteProtocolError (tentativa %d/%d): %s",
                label, attempt, MAX_RETRIES, exc,
            )

        except httpx.RequestError as exc:
            log.warning(
                "[%s] RequestError (tentativa %d/%d): %s",
                label, attempt, MAX_RETRIES, exc,
            )

        except Exception as exc:
            log.warning(
                "[%s] Erro inesperado (tentativa %d/%d): %s",
                label, attempt, MAX_RETRIES, exc,
            )

        # ── Backoff exponencial ──────────────────────────────────────────
        if attempt < MAX_RETRIES:
            delay = RETRY_BASE_DELAY * (2 ** (attempt - 1))  # 2s, 4s, 8s
            log.info("[%s] Aguardando %ds antes de retry...", label, delay)
            time.sleep(delay)

        # Se falhou por erro de conexão, tenta recriar o http_client
        if attempt == MAX_RETRIES - 1:
            try:
                log.info("[%s] Recriando http_client...", label)
                http_client.close()
                http_client = httpx.Client(
                    trust_env=False, headers=HEADERS, timeout=30
                )
            except Exception:
                pass

    log.error("[%s] Falha total após %d tentativas: %s", label, MAX_RETRIES, url)
    return None


# ═══════════════════════════════════════════════════════════════════════════════
# FUNÇÕES PÚBLICAS — Todas com fallback seguro
# ═══════════════════════════════════════════════════════════════════════════════

def get_active_clients() -> list[dict]:
    """Retorna todos os clientes com is_running=true.
    Fallback: [] (supervisor não cria novos workers)."""
    r = _safe_request(
        "get",
        f"{SUPABASE_HFT_URL}/rest/v1/bot_clients",
        params={"is_running": "eq.true", "select": "*"},
        label="get_active_clients",
    )
    if r is None:
        return []
    return r.json()


def get_confirmed_signals(client_id: str, estrategia_ativa: str = None) -> list[dict]:
    """Retorna sinais CONFIRMED recentes para GLOBAL ou client_id específico.

    Aceita sinais com client_id = 'GLOBAL' (sinais de mercado) OU
    sinais específicos do cliente. Idempotência via set no worker.py.

    Fallback: [] (nenhum sinal para executar).
    """
    cutoff = int(time.time()) - SIGNAL_WINDOW_SEC
    url = (
        f"{SUPABASE_HFT_URL}/rest/v1/iq_quant_signals"
        f"?status=eq.CONFIRMED"
        f"&timestamp_sinal=gte.{cutoff}"
        f"&client_id=in.(GLOBAL,{client_id})"
        f"&select=*&order=timestamp_sinal.asc&limit=10"
    )
    # Filtro de estratégia removido — sinais usam naming diferente
    r = _safe_request("get", url, label="get_confirmed_signals")
    if r is None:
        return []
    return r.json()


def patch_signal(signal_id: int, body: dict) -> int:
    """Atualiza campos de um sinal pelo id. Retorna o status HTTP.
    Fallback: 0 (sem crash)."""
    r = _safe_request(
        "patch",
        f"{SUPABASE_HFT_URL}/rest/v1/iq_quant_signals",
        params={"id": f"eq.{signal_id}"},
        json=body,
        label="patch_signal",
    )
    return r.status_code if r else 0


def is_client_running(client_id: str) -> bool:
    """Verifica se o cliente ainda está ativo no Supabase.
    Fallback: True (worker NÃO se mata à toa por falha de rede)."""
    r = _safe_request(
        "get",
        f"{SUPABASE_HFT_URL}/rest/v1/bot_clients",
        params={"client_id": f"eq.{client_id}", "select": "is_running", "limit": "1"},
        label="is_client_running",
    )
    if r is None:
        return True  # FALLBACK: assume ainda rodando
    data = r.json()  # retorna LIST
    return bool(data) and data[0].get("is_running", False)


def update_heartbeat(client_id: str) -> None:
    """Atualiza o timestamp de heartbeat do cliente.
    Fire-and-forget: nunca crasha."""
    _safe_request(
        "patch",
        f"{SUPABASE_HFT_URL}/rest/v1/bot_clients",
        params={"client_id": f"eq.{client_id}"},
        json={"last_heartbeat": "now()"},
        label="update_heartbeat",
    )


def cleanup_stale_executing(max_age_minutes: int = 5) -> int:
    """Marca sinais 'executing' mais antigos que max_age_minutes como 'executed/timeout'.

    Safety net: se um worker morrer entre patch(executing) e patch(executed),
    esta função garante que o sinal não fica preso para sempre.
    Chamada pelo supervisor a cada ciclo.

    Fallback: 0 (sem crash).
    """
    r = _safe_request(
        "post",
        f"{SUPABASE_HFT_URL}/rest/v1/rpc/cleanup_stale_executing",
        json={"max_age_minutes": max_age_minutes},
        label="cleanup_stale_executing",
    )
    if r is None:
        return 0
    try:
        return r.json() or 0
    except Exception:
        return 0


_RISK_DEFAULTS = {"stake": 1.0, "stop_win": 50.0, "stop_loss": 25.0, "martingale_on": True}


def get_session_config(client_id: str) -> dict:
    """Retorna stake, stop_win, stop_loss do cliente (tabela iq_session_config).
    Fallback: _RISK_DEFAULTS."""
    r = _safe_request(
        "get",
        f"{SUPABASE_HFT_URL}/rest/v1/iq_session_config"
        f"?client_id=eq.{client_id}&select=*&limit=1",
        label="get_session_config",
    )
    if r is None:
        return _RISK_DEFAULTS.copy()
    try:
        data = r.json()
        return data[0] if data else _RISK_DEFAULTS.copy()
    except Exception:
        return _RISK_DEFAULTS.copy()


def insert_trade_result(result: dict) -> None:
    """Salva resultado de uma operação em iq_trade_results (feed em tempo real do front).
    Fire-and-forget: nunca crasha."""
    _safe_request(
        "post",
        f"{SUPABASE_HFT_URL}/rest/v1/iq_trade_results",
        json=result,
        label="insert_trade_result",
    )



def get_any_pending_gale(client_id: str) -> dict | None:
    """Retorna O PRIMEIRO estado de Gale ativo para este client_id.

    Prioridade do estado-máquina:
      - 'pending'  → há uma ordem em voo (não fazer nada)
      - 'loss_g0'  → loss no G0, deve disparar G1
      - 'loss_g1'  → loss no G1, deve disparar G2
      - 'loss_g2'  → Gale esgotado (deve limpar)

    Fallback: None (nenhum Gale ativo — buscar sinal novo).
    """
    r = _safe_request(
        "get",
        f"{SUPABASE_HFT_URL}/rest/v1/iq_gale_state",
        params={
            "client_id": f"eq.{client_id}",
            "select": "*",
            "order": "created_at.asc",
            "limit": "1",
        },
        label="get_any_pending_gale",
    )
    if r is None:
        return None
    try:
        data = r.json()
        return data[0] if data else None
    except Exception:
        return None


def get_signal_by_id(signal_id: str) -> dict | None:
    """Retorna os dados completos de um sinal pelo ID (para retomada de Gale).

    Fallback: None (sinal não encontrado ou erro de rede).
    """
    r = _safe_request(
        "get",
        f"{SUPABASE_HFT_URL}/rest/v1/iq_quant_signals",
        params={
            "id": f"eq.{signal_id}",
            "select": "*",
            "limit": "1",
        },
        label="get_signal_by_id",
    )
    if r is None:
        return None
    try:
        data = r.json()
        return data[0] if data else None
    except Exception:
        return None


def get_gale_state(client_id: str, signal_id: int) -> dict | None:
    """Consulta o iq_gale_state para um par (client_id, signal_id).

    Retorna o registro completo (dict) se existir e last_result != 'win',
    ou None se não houver entrada (G0 ainda não foi tentado ou já ganhou).

    Esta função é a FONTE DE VERDADE para decidir se devemos fazer Gale.
    Fallback: None (assume que é G0 para não bloquear operação).
    """
    r = _safe_request(
        "get",
        f"{SUPABASE_HFT_URL}/rest/v1/iq_gale_state",
        params={
            "client_id": f"eq.{client_id}",
            "signal_id": f"eq.{signal_id}",
            "select": "*",
            "limit": "1",
        },
        label="get_gale_state",
    )
    if r is None:
        return None
    try:
        data = r.json()
        return data[0] if data else None
    except Exception:
        return None


def upsert_gale_state(client_id: str, signal_id: int, last_result: str) -> None:
    """Cria ou atualiza o estado de Gale no iq_gale_state (single source of truth).

    Estratégia: DELETE+INSERT (não depende de UNIQUE constraint).
    Isso evita o erro 409 Conflict do PostgREST quando a constraint não existe.

    last_result: 'pending' | 'loss_g0' | 'loss_g1' | 'loss_g2'

    Fire-and-forget: nunca crasha.
    """
    # 1. DELETE qualquer entrada existente para este (client_id, signal_id)
    _safe_request(
        "delete",
        f"{SUPABASE_HFT_URL}/rest/v1/iq_gale_state",
        params={
            "client_id": f"eq.{client_id}",
            "signal_id": f"eq.{signal_id}",
        },
        label="upsert_gale_state_delete",
    )

    # 2. INSERT o novo estado
    _safe_request(
        "post",
        f"{SUPABASE_HFT_URL}/rest/v1/iq_gale_state",
        json={
            "client_id":   str(client_id),
            "signal_id":   str(signal_id),
            "last_result": last_result,
        },
        label="upsert_gale_state_insert",
    )


def delete_gale_state(client_id: str, signal_id: int) -> None:
    """Remove o estado de Gale após ciclo completo (win ou G2 executado).

    Fire-and-forget: nunca crasha.
    """
    _safe_request(
        "delete",
        f"{SUPABASE_HFT_URL}/rest/v1/iq_gale_state",
        params={
            "client_id": f"eq.{client_id}",
            "signal_id": f"eq.{signal_id}",
        },
        label="delete_gale_state",
    )


def get_session_pnl(client_id: str) -> float:
    """Retorna PnL acumulado das últimas 24h via view vw_iq_session_stats.
    Fallback: 0.0 (não força stop)."""
    r = _safe_request(
        "get",
        f"{SUPABASE_HFT_URL}/rest/v1/vw_iq_session_stats"
        f"?client_id=eq.{client_id}&select=pnl&limit=1",
        label="get_session_pnl",
    )
    if r is None:
        return 0.0
    try:
        data = r.json()
        return float(data[0].get("pnl", 0)) if data else 0.0
    except Exception:
        return 0.0
PYEOF
echo "       ✓ supabase_client.py"

# ── worker.py ──
cat > "$EXECUTOR_DIR/worker.py" << 'PYEOF'
"""
worker.py — Worker por Cliente (Candle-Close + Gale Instantâneo)

Arquitetura:
  - ZERO polling de api.get_async_order(). Resultado via fechamento de vela.
  - Gale disparado em < 200ms após detectar LOSS pelo candle close.
  - iq_gale_state no Supabase é a FONTE DE VERDADE para retomada pós-crash.

Loop principal (state-driven):
  PRIORIDADE 1 — Checar iq_gale_state. Se loss_gN → disparar G(N+1).
  PRIORIDADE 2 — Buscar sinais novos CONFIRMED. Executar G0.
"""
import time


from iqoptionapi.stable_api import IQ_Option

from config import HEARTBEAT_INTERVAL_SEC, POLL_INTERVAL_SEC, IQ_PROXY
from logger import get_logger
from supabase_client import (
    delete_gale_state,
    get_any_pending_gale,
    get_confirmed_signals,
    get_session_config,
    get_session_pnl,
    get_signal_by_id,
    insert_trade_result,
    is_client_running,
    patch_signal,
    update_heartbeat,
    upsert_gale_state,
)

# ── Constantes de Gale ────────────────────────────────────────────────────────
GALE_MULTIPLIERS = {0: 1.0, 1: 2.2, 2: 5.0}
GALE_MAX_LEVEL   = 2


# ═══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def _mask_email(email: str) -> str:
    """Mascara email para logs: m***9@gmail.com"""
    try:
        local, domain = email.split("@", 1)
        if len(local) > 2:
            return f"{local[0]}{'*' * (len(local) - 2)}{local[-1]}@{domain}"
        return f"{local[0]}***@{domain}"
    except Exception:
        return "***@***"


def _get_entry_price(api: IQ_Option, ativo: str, log) -> float | None:
    """Obtém o preço atual (último close) via api.get_candles().
    Usado como preço de entrada logo após api.buy()."""
    try:
        candles = api.get_candles(ativo, 60, 1, time.time())
        if candles and len(candles) > 0:
            return float(candles[-1].get("close", 0))
    except Exception as exc:
        log.warning("[CANDLE] Erro ao obter preço de entrada: %s", exc)
    return None


def _wait_candle_close_and_check(
    api: IQ_Option,
    ativo: str,
    direcao: str,
    entry_price: float,
    order_id: int,
    log,
) -> dict:
    """
    Aguarda o fechamento da vela (candle close) e determina win/loss localmente.
    Se detectar LOSS no candle, retorna instantaneamente.
    Tenta capturar o profit real com check_win_v3 como fallback seguro.
    """
    now = time.time()
    seconds_to_next_minute = 60 - (now % 60)
    sleep_time = max(seconds_to_next_minute - 1, 0)
    
    log.info(
        "[CANDLE] Aguardando %.1fs até candle close | ativo=%s",
        sleep_time, ativo,
    )
    time.sleep(sleep_time)
    time.sleep(2)  # delay para processamento da vela

    close_price = None
    try:
        candles = api.get_candles(ativo, 60, 2, time.time())
        if candles and len(candles) >= 2:
            close_price = float(candles[-2].get("close", 0))
            log.info(
                "[CANDLE] Close detectado: entry=%.6f | close=%.6f",
                entry_price, close_price,
            )
    except Exception as exc:
        log.warning("[CANDLE] Erro ao obter candle de fechamento: %s", exc)

    if close_price is not None and entry_price > 0:
        if direcao == "call":
            won = close_price > entry_price
        else:
            won = close_price < entry_price

        result_label = "WIN" if won else "LOSS"
        log.info("[CANDLE] Resultado por candle: %s", result_label)

        # LOSS → retorno INSTANTÂNEO para disparar Gale imediatamente
        if not won:
            return {"won": False, "profit": 0.0}

        # WIN → tenta obter profit real via check_win_v3 (timeout curto)
        estimated_profit = 0.0
        try:
            deadline_profit = time.time() + 15
            while time.time() < deadline_profit:
                result = api.check_win_v3(order_id)
                if result is not None:
                    win_amount = float(result.get("win_amount", 0) or 0)
                    loss_amt = float(result.get("profit_amount", 0) or 0)
                    if win_amount == 0 and loss_amt == 0:
                        time.sleep(0.5)
                        continue
                    estimated_profit = win_amount if win_amount > 0 else -loss_amt
                    break
                time.sleep(0.5)
        except Exception:
            pass

        return {"won": True, "profit": estimated_profit}

    # Fallback total caso candle não retorne dados
    log.warning("[CANDLE] Fallback para check_win_v3 (candle indisponível)")
    deadline = time.time() + 90
    while time.time() < deadline:
        try:
            result = api.check_win_v3(order_id)
            if result is not None:
                win_amount = float(result.get("win_amount", 0) or 0)
                loss_amt = float(result.get("profit_amount", 0) or 0)
                if win_amount == 0 and loss_amt == 0:
                    time.sleep(0.5)
                    continue
                won = win_amount > 0
                profit = win_amount if won else -loss_amt
                return {"won": won, "profit": profit}
        except Exception:
            pass
        time.sleep(0.5)

    log.error("[RESULT] Timeout 90s sem resultado — assumindo LOSS por segurança")
    return {"won": False, "profit": 0.0}


def _execute_order(
    api:         IQ_Option,
    signal:      dict,
    gale_level:  int,
    client_id:   str,
    base_stake:  float,
    estrategia:  str,
    log,
) -> bool:
    """
    Executa uma ordem e determina resultado via candle close.
    Se LOSS → persiste em iq_gale_state para Gale imediato no próximo ciclo.

    Logs:
        [EXEC] Ativo: X | Direcao: Y | Tentativa: G0/G1/G2 | Stake: Z
    """
    sig_id  = signal.get("id")
    ativo   = signal.get("ativo", "EURUSD")
    direcao = signal.get("direcao", "CALL").lower()
    duracao = 1

    stake_used = round(base_stake * GALE_MULTIPLIERS.get(gale_level, 1.0), 2)

    log.info(
        "[EXEC] Ativo: %s | Direcao: %s | Tentativa: G%d | Stake: $%.2f",
        ativo, direcao.upper(), gale_level, stake_used,
    )

    # Marca 'pending' ANTES de abrir (blindagem de memória pós-crash)
    upsert_gale_state(client_id, str(sig_id), "pending")
    patch_signal(sig_id, {"status": "executing"})

    try:
        check, order_id = api.buy(stake_used, ativo, direcao, duracao)

        if not check:
            log.error("[EXEC] Ordem REJEITADA | order_id=%s | G%d", order_id, gale_level)
            upsert_gale_state(client_id, str(sig_id), f"loss_g{gale_level}")
            patch_signal(sig_id, {"status": "executed"})
            return False

        log.info("[EXEC] Ordem ACEITA | order_id=%s | G%d", order_id, gale_level)

        # Captura preço de entrada imediatamente após o buy
        entry_price = _get_entry_price(api, ativo, log)
        if entry_price:
            log.info("[EXEC] Preço de entrada: %.6f", entry_price)
        else:
            log.warning("[EXEC] Preço de entrada indisponível — fallback para polling")

        # ── CANDLE CLOSE: aguarda e determina resultado ──────────────────
        result = _wait_candle_close_and_check(
            api, ativo, direcao, entry_price or 0, order_id, log,
        )

        won          = result.get("won", False)
        profit       = result.get("profit", 0)
        status_final = "win" if won else "loss"

        log.info(
            "[EXEC] Resultado G%d: %s | profit=%.2f",
            gale_level, status_final.upper(), profit,
        )

        # Persiste trade result
        insert_trade_result({
            "client_id":     client_id,
            "signal_id":     sig_id,
            "ativo":         ativo,
            "direcao":       direcao.upper(),
            "stake":         stake_used,
            "gale_level":    gale_level,
            "resultado":     status_final,
            "profit":        profit,
            "estrategia_id": estrategia or "",
        })

        if won:
            log.info("[EXEC] ✅ WIN G%d — ciclo encerrado para sinal %s", gale_level, sig_id)
            delete_gale_state(client_id, str(sig_id))
            patch_signal(sig_id, {"status": "executed", "resultado": status_final})
        else:
            if gale_level < GALE_MAX_LEVEL:
                # Gale: persiste loss_gN → próximo ciclo do while detecta e dispara G(N+1) IMEDIATAMENTE
                upsert_gale_state(client_id, str(sig_id), f"loss_g{gale_level}")
                log.info(
                    "[EXEC] 🔁 LOSS G%d — Gale G%d será disparado IMEDIATAMENTE",
                    gale_level, gale_level + 1,
                )
            else:
                log.warning("[EXEC] 🛑 LOSS G%d — Gale ESGOTADO para sinal %s", gale_level, sig_id)
                delete_gale_state(client_id, str(sig_id))
            patch_signal(sig_id, {"status": "executed", "resultado": status_final})

        return True

    except Exception as exc:
        log.error("[EXEC] Exceção G%d: %s", gale_level, exc)
        upsert_gale_state(client_id, str(sig_id), f"loss_g{gale_level}")
        patch_signal(sig_id, {"status": "executed"})
        return False


# ═══════════════════════════════════════════════════════════════════════════════
# PROCESSO PRINCIPAL
# ═══════════════════════════════════════════════════════════════════════════════

def run_client_worker(client: dict) -> None:
    """
    Processo isolado para um único cliente IQ Option.

    Loop principal (state-driven, candle-close):
      1. Checa is_client_running (heartbeat, circuit breaker).
      2. PRIORIDADE 1: Verifica iq_gale_state → executa Gale se pendente.
      3. PRIORIDADE 2: Busca sinais CONFIRMED → executa como G0.
    """
    client_id    = client["client_id"]
    email        = client["iq_email"]
    password     = client["iq_password"]
    balance_type = client.get("balance_type", "PRACTICE")
    estrategia   = client.get("estrategia_ativa") or ""

    log = get_logger(f"WORKER:{client_id}")
    log.info("Worker iniciado | email=%s | balance=%s", _mask_email(email), balance_type)

    # ── 1. Conectar ────────────────────────────────────────────────────────────
    if IQ_PROXY:
        import os
        os.environ["HTTP_PROXY"]  = IQ_PROXY
        os.environ["HTTPS_PROXY"] = IQ_PROXY
        log.info("Usando proxy para IQ Option: %s", IQ_PROXY)

    api = IQ_Option(email, password)

    MAX_CONNECT_ATTEMPTS = 3
    connect_attempts = 0

    while connect_attempts < MAX_CONNECT_ATTEMPTS:
        try:
            connected, reason = api.connect()
        except Exception as e:
            log.error("Exceção no connect (tentativa %d): %s", connect_attempts + 1, e)
            connect_attempts += 1
            if connect_attempts < MAX_CONNECT_ATTEMPTS:
                time.sleep(30 * connect_attempts)
            continue

        if connected:
            log.info("Conectado à IQ Option ✅")
            break
        else:
            log.error("Falha na conexão (tentativa %d): %s", connect_attempts + 1, reason)
            connect_attempts += 1
            if connect_attempts < MAX_CONNECT_ATTEMPTS:
                time.sleep(30 * connect_attempts)

    if connect_attempts >= MAX_CONNECT_ATTEMPTS:
        log.error("❌ Circuit breaker de conexão — desativando cliente no Supabase.")
        try:
            import httpx
            from config import SUPABASE_HFT_URL, SUPABASE_HFT_KEY
            httpx.patch(
                f"{SUPABASE_HFT_URL}/rest/v1/bot_clients?client_id=eq.{client_id}",
                json={"is_running": False},
                headers={
                    "apikey": SUPABASE_HFT_KEY,
                    "Authorization": f"Bearer {SUPABASE_HFT_KEY}",
                    "Content-Type": "application/json",
                },
                timeout=5,
            )
        except Exception as e:
            log.error("Erro ao desligar no Supabase: %s", e)
        return

    api.change_balance(balance_type)
    log.info("Balance definido: %s", balance_type)

    last_heartbeat_ts = time.time()
    executed_signals: set = set()  # idempotência para sinais novos (G0)
    executed_signals_ts: dict = {}  # timestamp de inserção para limpeza
    reconnect_count  = 0
    EXECUTED_TTL_SEC = 600  # limpa sinais executados há mais de 10 min

    # Circuit breaker Supabase
    MAX_SUPABASE_FAILURES = 10
    consecutive_supabase_failures = 0

    # ── 2. Loop principal (State-Driven, Candle-Close) ─────────────────────────
    while True:

        # a) Verifica se cliente ainda está ativo
        try:
            if not is_client_running(client_id):
                log.info("Cliente desativado no Supabase. Encerrando worker.")
                break
            consecutive_supabase_failures = 0
        except Exception as exc:
            consecutive_supabase_failures += 1
            log.warning(
                "Falha ao checar is_client_running (%d/%d): %s",
                consecutive_supabase_failures, MAX_SUPABASE_FAILURES, exc,
            )
            if consecutive_supabase_failures >= MAX_SUPABASE_FAILURES:
                log.error("❌ Circuit breaker Supabase: %d falhas. Encerrando.", MAX_SUPABASE_FAILURES)
                break
            time.sleep(5)
            continue

        # b) Heartbeat periódico
        now = time.time()
        if now - last_heartbeat_ts >= HEARTBEAT_INTERVAL_SEC:
            update_heartbeat(client_id)
            last_heartbeat_ts = now

        # c) Verifica conexão WebSocket
        if not api.check_connect():
            _delay = min(2 ** reconnect_count, 30)
            log.warning("WebSocket desconectado. Aguardando %ds (tentativa %d)...", _delay, reconnect_count + 1)
            time.sleep(_delay)
            reconnect_count += 1
            api.connect()
            continue
        reconnect_count = 0

        # d) Carrega config de risco
        config     = get_session_config(client_id)
        base_stake = float(config.get("stake", 1.0))
        stop_win   = float(config.get("stop_win", 50.0))
        stop_loss  = float(config.get("stop_loss", 25.0))

        # e) Verifica Stop Win / Stop Loss
        current_pnl = get_session_pnl(client_id)
        if current_pnl >= stop_win:
            log.info("🏆 STOP WIN atingido ($%.2f >= $%.2f) — pausando", current_pnl, stop_win)
            time.sleep(max(POLL_INTERVAL_SEC, 5))
            continue
        if current_pnl <= -stop_loss:
            log.info("🛑 STOP LOSS atingido ($%.2f <= -$%.2f) — pausando", current_pnl, stop_loss)
            time.sleep(max(POLL_INTERVAL_SEC, 5))
            continue

        # ── PRIORIDADE 1: Checar iq_gale_state ────────────────────────────────
        # O Gale é resolvido ANTES de buscar sinais novos.
        # Se o worker crashou e voltou, ele retoma o ciclo aqui.
        gale_entry = get_any_pending_gale(client_id)

        if gale_entry:
            last_result = gale_entry.get("last_result", "")
            sig_id_str  = str(gale_entry.get("signal_id"))

            if last_result == "pending":
                try:
                    from datetime import datetime, timezone, timedelta
                    # Tenta expires_at primeiro, senão usa created_at + 3 min
                    expires_str = gale_entry.get("expires_at", "") or gale_entry.get("created_at", "")
                    if expires_str:
                        ref_dt = datetime.fromisoformat(expires_str.replace("Z", "+00:00"))
                        # Se não tinha expires_at, adiciona 3 min ao created_at
                        if not gale_entry.get("expires_at"):
                            ref_dt = ref_dt + timedelta(minutes=3)
                        if datetime.now(timezone.utc) > ref_dt:
                            log.warning("[STATE] Pending EXPIRADO (>3min) → limpando sinal %s", sig_id_str)
                            delete_gale_state(client_id, sig_id_str)
                            continue
                except Exception as e:
                    log.warning("[STATE] Erro ao checar expires_at: %s", e)
                # Pending ainda válido — ordem em voo, aguarda com sleep curto
                log.debug("[STATE] Ordem em voo para sinal %s — aguardando...", sig_id_str)
                time.sleep(2)
                continue

            elif last_result.startswith("loss_g"):
                try:
                    gale_done = int(last_result.replace("loss_g", ""))
                except ValueError:
                    gale_done = 0

                next_gale = gale_done + 1

                if next_gale > GALE_MAX_LEVEL:
                    log.warning("[STATE] G%d loss — Gale esgotado. Limpando sinal %s.", gale_done, sig_id_str)
                    delete_gale_state(client_id, sig_id_str)
                    time.sleep(1)
                    continue

                log.info(
                    "[STATE] 🔁 Detectado loss_g%d → disparando G%d IMEDIATAMENTE para sinal %s",
                    gale_done, next_gale, sig_id_str,
                )

                signal = get_signal_by_id(sig_id_str)
                if signal is None:
                    log.error("[STATE] Sinal %s não encontrado — limpando Gale.", sig_id_str)
                    delete_gale_state(client_id, sig_id_str)
                    continue

                # 🚀 GALE INSTANTÂNEO — sem sleep intermediário
                _execute_order(api, signal, next_gale, client_id, base_stake, estrategia, log)
                continue  # volta ao topo para checar se tem mais Gale

            else:
                log.warning("[STATE] Estado inesperado '%s' — limpando sinal %s.", last_result, sig_id_str)
                delete_gale_state(client_id, sig_id_str)

        # ── PRIORIDADE 2: Buscar sinais novos CONFIRMED ────────────────────────
        try:
            signals = get_confirmed_signals(client_id, estrategia if estrategia else None)
        except Exception as exc:
            log.error("Erro ao buscar sinais: %s", exc)
            time.sleep(max(POLL_INTERVAL_SEC, 5))
            continue

        # Limpeza periódica de sinais antigos (anti-memory-leak)
        now_ts = time.time()
        stale = [sid for sid, ts in executed_signals_ts.items()
                 if now_ts - ts > EXECUTED_TTL_SEC]
        for sid in stale:
            executed_signals.discard(sid)
            del executed_signals_ts[sid]

        for signal in signals:
            sig_id = signal.get("id")

            if sig_id in executed_signals:
                continue

            executed_signals.add(sig_id)
            executed_signals_ts[sig_id] = time.time()
            log.info("[STATE] Novo sinal %s detectado → executando G0", sig_id)
            _execute_order(api, signal, gale_level=0, client_id=client_id,
                           base_stake=base_stake, estrategia=estrategia, log=log)
            break  # 1 ativo por vez

        # Anti-spam APENAS quando não executou nada neste ciclo
        # Se executou ordem (G0 ou Gale), volta imediatamente para checar estado
        time.sleep(1)
PYEOF
echo "       ✓ worker.py"

# ── main.py ──
cat > "$EXECUTOR_DIR/main.py" << 'PYEOF'
"""
main.py — Supervisor Multi-Tenant IQ Option Executor

Responsabilidades:
  - Poll bot_clients a cada POLL_INTERVAL_SEC para detectar clientes ativos.
  - Lança 1 multiprocessing.Process por cliente ativo.
  - Encerra processos de clientes desativados (is_running=false).
  - Nunca para: loop infinito com tratamento de exceções.

Uso:
    python main.py

Deploy:
    nohup python main.py > logs/executor.log 2>&1 &
"""

import multiprocessing
import time

from config import POLL_INTERVAL_SEC
from logger import get_logger
from supabase_client import get_active_clients, cleanup_stale_executing
from worker import run_client_worker

log = get_logger("SUPERVISOR")


def main() -> None:
    log.info("Executor supervisor iniciado")

    # client_id → Process
    active_processes: dict[str, multiprocessing.Process] = {}

    while True:
        try:
            clients    = get_active_clients()
            active_ids = {c["client_id"] for c in clients}

            # Limpa sinais presos em 'executing' por workers mortos
            try:
                cleaned = cleanup_stale_executing(5)
                if cleaned:
                    log.info("Cleaned %d stale executing signals", cleaned)
            except Exception:
                pass  # não-crítico

            # Inicia workers para clientes novos ou que crasharam
            for client in clients:
                cid  = client["client_id"]
                proc = active_processes.get(cid)
                if proc is None or not proc.is_alive():
                    if proc is not None:
                        log.warning("Worker client_id=%s morreu. Reiniciando.", cid)
                    else:
                        log.info("Novo cliente detectado. Iniciando worker client_id=%s", cid)

                    p = multiprocessing.Process(
                        target=run_client_worker,
                        args=(client,),
                        name=f"worker-{cid}",
                        daemon=True,
                    )
                    p.start()
                    active_processes[cid] = p

            # Encerra workers de clientes desativados
            for cid in list(active_processes.keys()):
                if cid not in active_ids:
                    proc = active_processes[cid]
                    if proc.is_alive():
                        log.info("Cliente desativado. Terminando worker client_id=%s", cid)
                        proc.terminate()
                        proc.join(timeout=5)
                    del active_processes[cid]

        except Exception as exc:
            log.error("Erro no supervisor: %s", exc)
            # Backoff longo para não spammar Supabase em caso de erro
            time.sleep(30)
            continue

        time.sleep(POLL_INTERVAL_SEC)


if __name__ == "__main__":
    multiprocessing.set_start_method("spawn")
    main()
PYEOF
echo "       ✓ main.py"

# ── monitor.py ──
cat > "$EXECUTOR_DIR/monitor.py" << 'PYEOF'
"""
monitor.py — Módulo de Monitoramento e Alertas

Detecta e dispara alertas para 3 cenários críticos:

  1. LOGIN_FAILURE   — falhas consecutivas de login na IQ Option
  2. SUPABASE_DOWN   — Supabase inacessível por mais de X minutos
  3. DUPLICATE_WORKER — mais de 1 processo para o mesmo client_id

Canal de alerta configurável via variável de ambiente:
  ALERT_DISCORD_WEBHOOK  → POST no webhook do Discord
  (ausente)              → apenas log.critical

Uso no main.py:
    from monitor import AlertManager
    alert = AlertManager()
    alert.on_login_failure("cli_001")
    alert.on_supabase_error()
    alert.check_duplicate_workers(active_processes)
"""

import os
import time
from collections import defaultdict

import httpx

from logger import get_logger

log = get_logger("MONITOR")

# Thresholds configuráveis via env
_MAX_LOGIN_FAILURES  = int(os.getenv("ALERT_MAX_LOGIN_FAILURES", "3"))
_MAX_SUPABASE_DOWN_S = int(os.getenv("ALERT_MAX_SUPABASE_DOWN_MIN", "5")) * 60
_DISCORD_WEBHOOK     = os.getenv("ALERT_DISCORD_WEBHOOK", "")


def _send_discord(message: str) -> None:
    """Envia alerta para o webhook do Discord (fire-and-forget)."""
    if not _DISCORD_WEBHOOK:
        return
    try:
        httpx.post(
            _DISCORD_WEBHOOK,
            json={"content": f"🚨 **IQ EXECUTOR ALERT**\n{message}"},
            timeout=5,
        )
    except Exception as exc:
        log.warning("Falha ao enviar alerta Discord: %s", exc)


def _alert(code: str, message: str) -> None:
    """Loga em CRITICAL e envia para Discord se configurado."""
    log.critical("[ALERT:%s] %s", code, message)
    _send_discord(f"`[{code}]` {message}")


class AlertManager:
    """
    Gerencia contadores de falha e dispara alertas quando thresholds são atingidos.

    Instanciar 1 vez no supervisor e passar para cada ciclo do loop principal.
    """

    def __init__(self) -> None:
        # client_id → contagem de falhas de login consecutivas
        self._login_failures: dict[str, int] = defaultdict(int)

        # Timestamp da primeira falha Supabase consecutiva (0 = OK)
        self._supabase_down_since: float = 0.0

        # Controle de alerta já enviado (evita spam)
        self._alerted: set[str] = set()

    # ── Login IQ Option ───────────────────────────────────────────────────────

    def on_login_failure(self, client_id: str) -> None:
        """Registra 1 falha de login. Alerta se atingir threshold."""
        self._login_failures[client_id] += 1
        count = self._login_failures[client_id]
        log.warning(
            "Falha de login client_id=%s (%d/%d)",
            client_id, count, _MAX_LOGIN_FAILURES,
        )
        alert_key = f"login:{client_id}"
        if count >= _MAX_LOGIN_FAILURES and alert_key not in self._alerted:
            self._alerted.add(alert_key)
            _alert(
                "LOGIN_FAILURE",
                f"client_id={client_id} falhou no login {count}x consecutivo. "
                f"Verifique credenciais no Supabase (bot_clients).",
            )

    def on_login_success(self, client_id: str) -> None:
        """Reseta contador após login bem-sucedido."""
        if self._login_failures[client_id] > 0:
            log.info("Login OK client_id=%s — resetando contador de falhas.", client_id)
        self._login_failures[client_id] = 0
        self._alerted.discard(f"login:{client_id}")

    # ── Supabase ──────────────────────────────────────────────────────────────

    def on_supabase_error(self) -> None:
        """Registra indisponibilidade do Supabase. Alerta se > threshold."""
        if self._supabase_down_since == 0.0:
            self._supabase_down_since = time.time()
            log.warning("Supabase inacessível — iniciando contador de downtime.")

        down_seconds = time.time() - self._supabase_down_since
        if down_seconds >= _MAX_SUPABASE_DOWN_S and "supabase_down" not in self._alerted:
            self._alerted.add("supabase_down")
            _alert(
                "SUPABASE_DOWN",
                f"Supabase inacessível há {down_seconds / 60:.1f} min. "
                f"Verifique a conexão da VPS com https://ypqekkkrfklaqlzhkbwg.supabase.co",
            )

    def on_supabase_ok(self) -> None:
        """Reseta contador de downtime após sucesso."""
        if self._supabase_down_since > 0.0:
            down = time.time() - self._supabase_down_since
            log.info("Supabase recuperado após %.0fs de indisponibilidade.", down)
        self._supabase_down_since = 0.0
        self._alerted.discard("supabase_down")

    # ── Workers duplicados ────────────────────────────────────────────────────

    def check_duplicate_workers(
        self,
        active_processes: dict,      # client_id → Process
        max_per_client: int = 1,
    ) -> None:
        """
        Verifica se algum client_id tem mais de max_per_client processos vivos.
        (Deveria ser impossível, mas é um safety net.)
        """
        from collections import Counter
        alive_by_client: Counter = Counter()
        for cid, proc in active_processes.items():
            if proc.is_alive():
                alive_by_client[cid] += 1

        for cid, count in alive_by_client.items():
            if count > max_per_client:
                alert_key = f"dup:{cid}"
                if alert_key not in self._alerted:
                    self._alerted.add(alert_key)
                    _alert(
                        "DUPLICATE_WORKER",
                        f"client_id={cid} tem {count} workers vivos simultaneamente! "
                        f"Máximo permitido: {max_per_client}. Investigar imediatamente.",
                    )

    # ── Status resumido ───────────────────────────────────────────────────────

    def status_summary(self) -> dict:
        """Retorna snapshot do estado atual para debug/logging."""
        return {
            "login_failures":      dict(self._login_failures),
            "supabase_down_sec":   (
                round(time.time() - self._supabase_down_since, 1)
                if self._supabase_down_since > 0 else 0
            ),
            "active_alerts":       list(self._alerted),
        }
PYEOF
echo "       ✓ monitor.py"

# ── requirements.txt ──
cat > "$EXECUTOR_DIR/requirements.txt" << 'PYEOF'
git+https://github.com/Lu-Yi-Hsun/iqoptionapi.git
httpx>=0.28.0
pytest>=8.0.0
pytest-mock>=3.0.0
PYEOF
echo "       ✓ requirements.txt"

echo ""
echo "       ✅ Todos os 6 arquivos atualizados."
echo ""

# ── 4. Reinstalar dependências ────────────────────────────────────────────────
echo "[4/5] Reinstalando dependências ..."
cd "$EXECUTOR_DIR"
$VENV_PIP install -r requirements.txt --quiet
echo "       ✅ Dependências instaladas."
echo ""

# ── 5. Reiniciar executor ────────────────────────────────────────────────────
echo "[5/5] Reiniciando executor ..."
mkdir -p "$EXECUTOR_DIR/logs"
cd "$EXECUTOR_DIR"

# Carrega variáveis de ambiente do .env do executor ou do root
set -a
[ -f "$EXECUTOR_DIR/.env" ] && source "$EXECUTOR_DIR/.env" 2>/dev/null || true
[ -f /root/catalogadorderiv/.env ] && source /root/catalogadorderiv/.env 2>/dev/null || true
set +a

if [ -z "${SUPABASE_HFT_KEY:-}" ]; then
    echo "       ❌ SUPABASE_HFT_KEY não encontrada no ambiente!"
    echo "          Defina com: export SUPABASE_HFT_KEY='sua_chave' >> /root/.bashrc"
    exit 1
fi

nohup $VENV_PYTHON main.py > logs/executor.log 2>&1 &
EXECUTOR_PID=$!
sleep 2

if kill -0 "$EXECUTOR_PID" 2>/dev/null; then
    echo "       ✅ Executor reiniciado com PID=$EXECUTOR_PID"
else
    echo "       ❌ Executor não iniciou. Cheque logs/executor.log"
    tail -20 logs/executor.log
fi

echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║  ✅ UPDATE COMPLETO — $(date '+%Y-%m-%d %H:%M:%S')         ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""
echo "  Backup: $BACKUP_DIR"
echo "  Logs:   tail -f $EXECUTOR_DIR/logs/executor.log"
echo ""

tail -f "$EXECUTOR_DIR/logs/executor.log"
