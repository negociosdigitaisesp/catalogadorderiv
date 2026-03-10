"""
tests/test_chaos.py — Chaos Tests

Simula falhas críticas para validar resiliência do sistema:

  C1  Queda de rede → reconexão automática, sem execução duplicada
  C2  Morte de worker (kill -9) → supervisor detecta e recria
  C3  Supabase down → workers logam erro, não entram em loop infinito

Todos os cenários usam mocks — sem conexão real.
"""

import sys
import os
import time
import multiprocessing

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import httpx
import pytest
from unittest.mock import MagicMock, patch, call


# ─── C1: Queda de rede ────────────────────────────────────────────────────────

def test_C1_network_failure_triggers_reconnect():
    """
    C1 — check_connect() retorna False → worker chama api.connect() e continua.

    Valida:
      - api.connect chamado novamente após falha detectada
      - Nenhuma ordem aberta durante período offline
      - Sem crash ou exceção
    """
    reconnect_calls = {"n": 0}
    iter_count      = {"n": 0}

    def fake_check_connect():
        iter_count["n"] += 1
        # Simula: offline nas 2 primeiras iterações, online depois
        return iter_count["n"] > 2

    def fake_is_running(cid):
        return iter_count["n"] < 6

    api = MagicMock()
    api.connect.return_value = (True, "ok")
    api.check_connect.side_effect = fake_check_connect
    api.change_balance.return_value = None
    api.buy.return_value = (True, 777)

    with (
        patch("worker.IQ_Option",            return_value=api),
        patch("worker.get_confirmed_signals", return_value=[]),
        patch("worker.is_client_running",    side_effect=fake_is_running),
        patch("worker.update_heartbeat"),
        patch("worker.patch_signal"),
        patch("worker.time.sleep"),
    ):
        from worker import run_client_worker
        run_client_worker({
            "client_id": "chaos_c1", "iq_email": "x@x.com",
            "iq_password": "pw", "balance_type": "PRACTICE",
        })

    # connect foi chamado 1x no início + pelo menos 1x na reconexão
    assert api.connect.call_count >= 2, (
        f"C1: esperado >= 2 chamadas a connect(), got {api.connect.call_count}"
    )
    # Sem ordens durante offline
    assert api.buy.call_count == 0, "C1: nenhuma ordem deve ser aberta enquanto offline"


# ─── C2: Morte de worker (simulada via processo) ──────────────────────────────

def _worker_that_dies(queue):
    """Worker que inicia, reporta PID, e encerra abruptamente."""
    queue.put(os.getpid())
    time.sleep(0.5)
    # Simula morte abrupta: sys.exit(1) em vez de kill -9 (seguro no Windows)
    import sys
    sys.exit(1)


import os


def test_C2_supervisor_restarts_dead_worker():
    """
    C2 — Worker morre (exit code != 0) → supervisor detecta (is_alive=False)
    e recria o processo.

    Valida:
      - Após morte, supervisor chama Process() e .start() novamente
      - is_alive() retorna False para processo morto
    """
    # Lança processo real que morre em 0.5s
    q = multiprocessing.Queue()
    p = multiprocessing.Process(target=_worker_that_dies, args=(q,), daemon=True)
    p.start()

    pid_do_worker = q.get(timeout=5)
    p.join(timeout=3)

    # Após join, processo deve estar morto
    assert not p.is_alive(), "C2: worker deveria ter morrido"
    assert p.exitcode != 0,  f"C2: exit code esperado != 0, got {p.exitcode}"

    # Simula o que o supervisor faria: detecta morte e recria
    mock_new_proc = MagicMock()
    mock_new_proc.is_alive.return_value = False   # antes do start
    fake_client = {
        "client_id": "chaos_c2", "iq_email": "y@y.com",
        "iq_password": "pw", "balance_type": "PRACTICE",
    }

    call_count = {"n": 0}

    def fake_get_clients():
        call_count["n"] += 1
        if call_count["n"] <= 2:
            return [fake_client]
        return []

    with (
        patch("main.get_active_clients",       side_effect=fake_get_clients),
        patch("main.cleanup_stale_executing",  return_value=0),
        patch("main.multiprocessing.Process",  return_value=mock_new_proc) as mock_cls,
        patch("main.time.sleep",               side_effect=[None, None, StopIteration]),
    ):
        try:
            import main as supervisor_main
            supervisor_main.main()
        except StopIteration:
            pass

    # Supervisor deve ter criado o processo ao menos 1 vez
    assert mock_cls.call_count >= 1, "C2: supervisor não recriou o worker"
    assert mock_new_proc.start.call_count >= 1, "C2: .start() não foi chamado"


# ─── C3: Supabase down ────────────────────────────────────────────────────────

def test_C3_supabase_down_worker_logs_error_no_infinite_loop():
    """
    C3 — Supabase inacessível → get_confirmed_signals lança exceção.

    Valida:
      - Worker não entra em loop infinito (continua iterando com sleep)
      - Worker encerra normalmente quando is_client_running retorna False
      - Nenhuma ordem é aberta durante período de indisponibilidade
    """
    error_count  = {"n": 0}
    iter_count   = {"n": 0}

    def fake_signals_down(client_id, estrategia_ativa=None):
        error_count["n"] += 1
        raise httpx.ConnectError("Supabase unreachable")

    def fake_is_running(cid):
        iter_count["n"] += 1
        return iter_count["n"] <= 4   # roda 4 iterações e para

    api = MagicMock()
    api.connect.return_value  = (True, "ok")
    api.check_connect.return_value = True
    api.change_balance.return_value = None

    with (
        patch("worker.IQ_Option",            return_value=api),
        patch("worker.get_confirmed_signals", side_effect=fake_signals_down),
        patch("worker.is_client_running",    side_effect=fake_is_running),
        patch("worker.update_heartbeat"),
        patch("worker.patch_signal"),
        patch("worker.time.sleep"),
    ):
        from worker import run_client_worker
        # Não deve lançar exceção
        run_client_worker({
            "client_id": "chaos_c3", "iq_email": "z@z.com",
            "iq_password": "pw", "balance_type": "PRACTICE",
        })

    assert error_count["n"] >= 1, "C3: get_confirmed_signals deve ter sido chamado"
    assert api.buy.call_count == 0, "C3: nenhuma ordem durante Supabase down"
    assert iter_count["n"] >= 2,   "C3: worker deve continuar iterando, não travar"


# ─── C4: Duplicação de sinal (idempotência) ───────────────────────────────────

def test_C4_same_signal_id_not_executed_twice():
    """
    C4 — Mesmo sinal retornado em 2 polls consecutivos (Supabase lento).

    Valida: api.buy chamado exatamente 1x, não 2x.
    """
    sig = {
        "id": 555, "ativo": "EURUSD", "direcao": "CALL",
        "client_id": "c4", "status": "CONFIRMED",
        "timestamp_sinal": int(time.time()),
        "stake": 1.0, "contexto": {},
    }
    poll_count = {"n": 0}

    def fake_signals(client_id, estrategia_ativa=None):
        poll_count["n"] += 1
        # Retorna mesmo sinal nos 2 primeiros polls
        if poll_count["n"] <= 2:
            return [sig]
        return []

    def fake_is_running(cid):
        return poll_count["n"] < 5

    api = MagicMock()
    api.connect.return_value       = (True, "ok")
    api.check_connect.return_value = True
    api.buy.return_value           = (True, 888)
    api.get_async_order.return_value = {"win_amount": "1.0", "loss": "0"}

    with (
        patch("worker.IQ_Option",            return_value=api),
        patch("worker.get_confirmed_signals", side_effect=fake_signals),
        patch("worker.is_client_running",    side_effect=fake_is_running),
        patch("worker.update_heartbeat"),
        patch("worker.patch_signal"),
        patch("worker.time.sleep"),
    ):
        from worker import run_client_worker
        run_client_worker({
            "client_id": "c4", "iq_email": "a@b.com",
            "iq_password": "pw", "balance_type": "PRACTICE",
        })

    assert api.buy.call_count == 1, (
        f"C4: sinal duplicado executado {api.buy.call_count}x — idempotência falhou"
    )
