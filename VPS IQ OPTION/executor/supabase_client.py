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
    SIGNAL_FETCH_LIMIT,
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
    r = _safe_request(
        "get",
        f"{SUPABASE_HFT_URL}/rest/v1/iq_quant_signals",
        params={
            "status": "eq.CONFIRMED",
            "timestamp_sinal": f"gte.{cutoff}",
            "client_id": f"in.(GLOBAL,{client_id})",
            "select": "*",
            "order": "timestamp_sinal.desc",
            "limit": str(SIGNAL_FETCH_LIMIT),
        },
        label="get_confirmed_signals",
    )
    if r is None:
        return []
    rows = r.json()

    if not estrategia_ativa:
        return rows

    estrategia_norm = str(estrategia_ativa).strip().lower()
    if not estrategia_norm:
        return rows

    # Filtro defensivo local: aceita diferentes naming conventions
    # de estratégia sem depender de um único campo no banco.
    strategy_keys = ("estrategia", "estrategia_id", "strategy", "strategy_id", "setup_id")
    filtered: list[dict] = []
    for row in rows:
        for key in strategy_keys:
            raw = row.get(key)
            if raw is None:
                continue
            if estrategia_norm in str(raw).strip().lower():
                filtered.append(row)
                break
    return filtered


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


def upsert_gale_state(
    client_id: str,
    signal_id: int,
    last_result: str,
    *,
    order_id: int = None,
    gale_level: int = 0,
) -> None:
    """Cria ou atualiza o estado de Gale no iq_gale_state (single source of truth).

    Estratégia: DELETE+INSERT (não depende de UNIQUE constraint).
    Isso evita o erro 409 Conflict do PostgREST quando a constraint não existe.

    last_result: 'pending' | 'loss_g0' | 'loss_g1' | 'loss_g2'
    order_id: ID da ordem IQ Option (salvo no pending para recuperação pós-crash)
    gale_level: nível Gale desta operação (0, 1 ou 2)

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
    payload: dict = {
        "client_id":   str(client_id),
        "signal_id":   str(signal_id),
        "last_result": last_result,
        "gale_level":  gale_level,
    }
    if order_id is not None:
        payload["order_id"] = int(order_id)

    _safe_request(
        "post",
        f"{SUPABASE_HFT_URL}/rest/v1/iq_gale_state",
        json=payload,
        label="upsert_gale_state_insert",
    )


def claim_signal(signal_id: int) -> bool:
    """Tenta reivindicar um sinal CONFIRMED atomicamente.

    Faz PATCH condicional: só muda status se ainda for CONFIRMED.
    Se dois workers competirem pelo mesmo sinal, apenas UM recebe a linha
    de volta — o outro recebe [] e retorna False.

    Retorna True se conseguiu reivindicar, False se já foi reivindicado.
    Fallback em erro de rede: False (não executa na dúvida — segurança > disponibilidade).
    """
    try:
        r = http_client.patch(
            f"{SUPABASE_HFT_URL}/rest/v1/iq_quant_signals",
            params={"id": f"eq.{signal_id}", "status": "eq.CONFIRMED"},
            json={"status": "executing"},
            headers={"Prefer": "return=representation"},
        )
        r.raise_for_status()
        rows = r.json()
        claimed = bool(rows)
        if not claimed:
            log.warning("[claim_signal] Sinal %s já reivindicado por outro worker", signal_id)
        return claimed
    except Exception as exc:
        log.warning("[claim_signal] Erro ao reivindicar sinal %s: %s — pulando", signal_id, exc)
        return False


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
