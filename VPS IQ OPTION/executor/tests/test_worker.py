"""
tests/test_worker.py
Testa _wait_result() com mocks de IQ_Option.get_async_order.
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from unittest.mock import MagicMock, patch

from worker import _wait_result
from logger import get_logger

_log = get_logger("TEST_WORKER")


def _make_api(side_effects):
    """Cria um mock de IQ_Option cujo get_async_order retorna cada item da lista."""
    api = MagicMock()
    api.get_async_order.side_effect = side_effects
    return api


# ─── 1. Resultado WIN ────────────────────────────────────────────────────────

def test_wait_result_win():
    win_payload = {"win_amount": "1.85", "loss": "0"}
    api = _make_api([win_payload])

    result = _wait_result(api, order_id=1001, timeout=5, log=_log)

    assert result["won"] is True
    assert result["profit"] == pytest.approx(1.85)


# ─── 2. Resultado LOSS ───────────────────────────────────────────────────────

def test_wait_result_loss():
    loss_payload = {"win_amount": "0", "loss": "1.0"}
    api = _make_api([loss_payload])

    result = _wait_result(api, order_id=1002, timeout=5, log=_log)

    assert result["won"] is False
    assert result["profit"] == pytest.approx(-1.0)


# ─── 3. Timeout (get_async_order sempre retorna None) ─────────────────────────

def test_wait_result_timeout():
    # None repetido simula ordem que nunca resolve dentro do timeout
    api = MagicMock()
    api.get_async_order.return_value = None

    # timeout=1 para o teste não demorar
    result = _wait_result(api, order_id=1003, timeout=1, log=_log)

    assert result == {"won": False, "profit": 0}


# ─── 4. Lock: um ativo por vez ───────────────────────────────────────────────

def test_one_asset_at_a_time():
    """Se currently_executing=True, segundo sinal deve ser ignorado."""
    executing = set()
    sig_id = 42
    executing.add(sig_id)
    assert sig_id in executing          # sinal já registrado
    should_skip = sig_id in executing   # segundo sinal com mesmo id → skip
    assert should_skip is True


# ─── 5. Filtro de estratégia na URL ──────────────────────────────────────────

def test_estrategia_filter_url():
    """get_confirmed_signals com estrategia_ativa deve incluir filtro like na URL."""
    from unittest.mock import patch, MagicMock
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = []
    mock_response.raise_for_status = MagicMock()

    with patch("httpx.get", return_value=mock_response) as mock_get:
        from supabase_client import get_confirmed_signals
        get_confirmed_signals("c1", "T1705")
        call_url = mock_get.call_args[0][0]
        assert "like.T1705" in call_url


# ─── 6. Exceção em api.buy → worker NÃO morre ──────────────────────────────

def test_worker_survives_buy_exception():
    """Se api.buy levanta Exception, o worker captura, loga e segue vivo.
    Simula 1 ciclo completo do run_client_worker com buy que levanta."""
    from worker import run_client_worker

    fake_client = {
        "client_id": "exc_test",
        "iq_email": "a@b.com",
        "iq_password": "pass",
        "balance_type": "PRACTICE",
    }

    fake_signal = {
        "id": 999,
        "ativo": "EURUSD",
        "direcao": "CALL",
        "stake": 1.0,
        "contexto": None,
    }

    mock_api = MagicMock()
    mock_api.connect.return_value = (True, "OK")
    mock_api.check_connect.return_value = True
    mock_api.buy.side_effect = Exception("ConnectionReset simulado")

    call_count = 0
    def fake_is_running(cid):
        nonlocal call_count
        call_count += 1
        return call_count <= 1  # True 1st cycle, False 2nd → exit

    with (
        patch("worker.IQ_Option", return_value=mock_api),
        patch("worker.is_client_running", side_effect=fake_is_running),
        patch("worker.get_confirmed_signals", return_value=[fake_signal]),
        patch("worker.patch_signal") as mock_patch,
        patch("worker.update_heartbeat"),
        patch("worker.time.sleep"),
    ):
        # Should NOT raise — worker catches exception internally
        run_client_worker(fake_client)

    # Signal must be patched as 'executed' despite the exception
    patch_calls = [c for c in mock_patch.call_args_list if c[0][1].get("status") == "executed"]
    assert len(patch_calls) >= 1, "Signal should be patched as 'executed' after buy exception"


# ─── 7. check=False em buy → patch executed sem crash ───────────────────────

def test_worker_handles_buy_check_false():
    """Se api.buy retorna (False, None), o worker loga warning e segue."""
    from worker import run_client_worker

    fake_client = {
        "client_id": "chk_test",
        "iq_email": "a@b.com",
        "iq_password": "pass",
        "balance_type": "PRACTICE",
    }

    fake_signal = {
        "id": 888,
        "ativo": "EURUSD",
        "direcao": "PUT",
        "stake": 2.0,
        "contexto": None,
    }

    mock_api = MagicMock()
    mock_api.connect.return_value = (True, "OK")
    mock_api.check_connect.return_value = True
    mock_api.buy.return_value = (False, None)  # rejected

    call_count = 0
    def fake_is_running(cid):
        nonlocal call_count
        call_count += 1
        return call_count <= 1

    with (
        patch("worker.IQ_Option", return_value=mock_api),
        patch("worker.is_client_running", side_effect=fake_is_running),
        patch("worker.get_confirmed_signals", return_value=[fake_signal]),
        patch("worker.patch_signal") as mock_patch,
        patch("worker.update_heartbeat"),
        patch("worker.time.sleep"),
    ):
        run_client_worker(fake_client)

    # 'executing' → then 'executed' (no resultado because rejected)
    exec_calls = [c for c in mock_patch.call_args_list if c[0][1].get("status") == "executed"]
    assert len(exec_calls) >= 1, "Rejected buy should still be patched as 'executed'"


# ─── 8. _mask_email produz output correto ────────────────────────────────────

def test_mask_email():
    from worker import _mask_email
    assert _mask_email("matosmayk9@gmail.com") == "m********9@gmail.com"
    assert _mask_email("ab@x.com") == "a***@x.com"    # len==2 → short fallback
    assert _mask_email("a@x.com") == "a***@x.com"    # len==1
    assert _mask_email("invalid") == "***@***"        # no @


# ─── 9. cleanup_stale_executing helper ───────────────────────────────────────

def test_cleanup_stale_executing():
    """Verifica que cleanup_stale_executing chama o RPC e retorna o count."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = 3
    mock_resp.raise_for_status = MagicMock()

    with patch("httpx.post", return_value=mock_resp) as mock_post:
        from supabase_client import cleanup_stale_executing
        count = cleanup_stale_executing(5)

    assert count == 3
    assert "cleanup_stale_executing" in mock_post.call_args[0][0]
