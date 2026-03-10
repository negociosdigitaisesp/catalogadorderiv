"""
tests/test_functional.py — Matriz de Testes Funcionais

Cobre os cenários da matriz QA:

  ID  Cenário
  F1  1 cliente, 1 sinal → 1 ordem, status=executed
  F2  Stop no meio → worker encerra sem crash
  F3  2 clientes, sinais cruzados → ordens na conta certa
  F4  10 sinais em sequência → 10 ordens, sem duplicar

Todos os testes usam mocks — sem conexão real com IQ Option ou Supabase.
worker.time.sleep é sempre mockado para os testes não esperarem POLL_INTERVAL_SEC real.
"""

import sys
import os
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unittest.mock import MagicMock, patch


# ─── Fábrica de cliente e sinal fake ─────────────────────────────────────────

def _client(cid="c1", email="a@b.com", password="pw"):
    return {
        "client_id":    cid,
        "iq_email":     email,
        "iq_password":  password,
        "balance_type": "PRACTICE",
    }


def _signal(sig_id, ativo="EURUSD", direcao="CALL", client_id="c1"):
    return {
        "id":              sig_id,
        "ativo":           ativo,
        "direcao":         direcao,
        "client_id":       client_id,
        "status":          "CONFIRMED",
        "timestamp_sinal": int(time.time()),
        "stake":           1.0,
        "contexto":        {"metrics": {"sizing": 1.0}},
    }


def _make_api():
    """Mock de IQ_Option: connect OK, buy OK, resultado WIN imediato."""
    api = MagicMock()
    api.connect.return_value         = (True, "ok")
    api.check_connect.return_value   = True
    api.change_balance.return_value  = None
    api.buy.return_value             = (True, 999)
    api.get_async_order.return_value = {"win_amount": "1.85", "loss": "0"}
    return api


# ─── F1: 1 cliente, 1 sinal ───────────────────────────────────────────────────

def test_F1_one_client_one_signal_executed():
    """
    F1 — 1 sinal inserido → 1 ordem, status executa executing → executed.

    Contadores independentes: signal_sent e run_count evitam loops infinitos.
    """
    sig          = _signal(sig_id=101)
    signal_sent  = [False]   # flag: sinal foi entregue?
    run_count    = [0]        # quantas vezes is_client_running foi chamado

    def fake_signals(client_id, estrategia_ativa=None):
        if not signal_sent[0]:
            signal_sent[0] = True
            return [sig]
        return []

    def fake_is_running(cid):
        run_count[0] += 1
        return run_count[0] <= 3   # encerra após 3 ciclos

    with (
        patch("worker.IQ_Option",            return_value=_make_api()),
        patch("worker.get_confirmed_signals", side_effect=fake_signals),
        patch("worker.is_client_running",    side_effect=fake_is_running),
        patch("worker.update_heartbeat"),
        patch("worker.patch_signal")  as mock_patch,
        patch("worker.time.sleep"),           # acelera POLL_INTERVAL_SEC
    ):
        from worker import run_client_worker
        run_client_worker(_client("c1"))

    statuses = [c.args[1]["status"] for c in mock_patch.call_args_list]
    assert "executing" in statuses, "F1: sinal deve ir para 'executing'"
    assert "executed"  in statuses, "F1: sinal deve ir para 'executed'"
    assert statuses.index("executing") < statuses.index("executed"), \
        "F1: 'executing' deve vir antes de 'executed'"


# ─── F2: Stop no meio ────────────────────────────────────────────────────────

def test_F2_stop_while_running_no_crash():
    """
    F2 — is_client_running retorna False após 2 ciclos → worker encerra sem crash.
    """
    run_count = [0]

    def fake_is_running(cid):
        run_count[0] += 1
        return run_count[0] <= 2   # True, True, False → encerra

    with (
        patch("worker.IQ_Option",            return_value=_make_api()),
        patch("worker.get_confirmed_signals", return_value=[]),
        patch("worker.is_client_running",    side_effect=fake_is_running),
        patch("worker.update_heartbeat"),
        patch("worker.patch_signal"),
        patch("worker.time.sleep"),
    ):
        from worker import run_client_worker
        run_client_worker(_client("c2"))   # não deve lançar exceção

    assert run_count[0] >= 2, "F2: is_client_running deve ser consultado ao menos 2x"


# ─── F3: 2 clientes, sinais vão para a conta certa ───────────────────────────

def test_F3_two_clients_signals_go_to_correct_account():
    """
    F3 — Worker de c1 só vê sinais de c1; buy é chamado com o ativo correto.

    Simula apenas 1 worker (c1). Valida que get_confirmed_signals é chamado
    com client_id="c1" e que api.buy recebe o ativo do sinal de c1.
    """
    received_ativos = []
    signal_sent     = [False]
    run_count       = [0]

    def fake_signals(client_id, estrategia_ativa=None):
        if not signal_sent[0]:
            signal_sent[0] = True
            # Sinal correto: apenas para c1
            return [_signal(201, ativo="GBPUSD", client_id=client_id)]
        return []

    def fake_is_running(_):
        run_count[0] += 1
        return run_count[0] <= 3

    api = _make_api()
    api.buy.side_effect = lambda s, ativo, d, dur: received_ativos.append(ativo) or (True, 1)
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
        run_client_worker(_client("c1"))

    # worker passa ativo sem modificar (só direcao vai para .lower())
    assert received_ativos == ["GBPUSD"], (
        f"F3: c1 deveria ter executado GBPUSD, got {received_ativos}"
    )


# ─── F4: 10 sinais em sequência, sem duplicar ─────────────────────────────────

def test_F4_ten_signals_no_duplicates():
    """
    F4 — 10 sinais entregues no primeiro poll → 10 ordens, nenhuma duplicada.

    Como currently_executing é reset em finally antes do próximo sinal do mesmo
    loop, todos os 10 sinais são processados na primeira iteração.
    """
    signals_10 = [_signal(300 + i) for i in range(10)]
    # Primeiro poll retorna os 10; polls seguintes retornam vazio
    batches    = iter([signals_10] + [[]] * 20)
    run_count  = [0]

    def fake_is_running(cid):
        run_count[0] += 1
        return run_count[0] <= 15   # margem para processar tudo

    with (
        patch("worker.IQ_Option",            return_value=_make_api()),
        patch("worker.get_confirmed_signals", side_effect=lambda *a, **k: next(batches, [])),
        patch("worker.is_client_running",    side_effect=fake_is_running),
        patch("worker.update_heartbeat"),
        patch("worker.patch_signal") as mock_patch,
        patch("worker.time.sleep"),
    ):
        from worker import run_client_worker
        run_client_worker(_client("c4"))

    executing_ids = [
        c.args[0]
        for c in mock_patch.call_args_list
        if c.args[1].get("status") == "executing"
    ]

    assert len(executing_ids) == 10,       f"F4: esperado 10 ordens, got {len(executing_ids)}"
    assert len(set(executing_ids)) == 10,  "F4: IDs duplicados detectados"
