"""
tests/test_supabase.py
Testa os helpers do supabase_client.py com mocks de httpx.
ATENÇÃO: As funções agora usam http_client (instância), não httpx.get global.
"""

import sys
import os

# Garante que o diretório pai (executor/) está no path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unittest.mock import MagicMock, patch, PropertyMock

import httpx
import httpcore
import supabase_client


def _mock_response(json_data, status_code=200):
    """Fábrica de mock de resposta httpx."""
    mock = MagicMock()
    mock.status_code = status_code
    mock.json.return_value = json_data
    mock.raise_for_status.return_value = None
    return mock


def _mock_502():
    """Fábrica de mock para resposta 502."""
    resp = MagicMock()
    resp.status_code = 502
    resp.raise_for_status.side_effect = httpx.HTTPStatusError(
        "502 Bad Gateway", request=MagicMock(), response=resp
    )
    return resp


# ─── 1. get_active_clients ────────────────────────────────────────────────────

def test_get_active_clients_returns_list():
    payload = [
        {"client_id": "cli_001", "iq_email": "a@b.com", "is_running": True},
        {"client_id": "cli_002", "iq_email": "c@d.com", "is_running": True},
    ]
    mock_client = MagicMock()
    mock_client.get.return_value = _mock_response(payload)
    with patch.object(supabase_client, "http_client", mock_client):
        result = supabase_client.get_active_clients()
    assert isinstance(result, list)
    assert len(result) == 2
    assert result[0]["client_id"] == "cli_001"


# ─── 2. is_client_running — True ─────────────────────────────────────────────

def test_is_client_running_true():
    mock_client = MagicMock()
    mock_client.get.return_value = _mock_response([{"is_running": True}])
    with patch.object(supabase_client, "http_client", mock_client):
        result = supabase_client.is_client_running("cli_001")
    assert result is True


# ─── 3. is_client_running — False ────────────────────────────────────────────

def test_is_client_running_false_when_stopped():
    mock_client = MagicMock()
    mock_client.get.return_value = _mock_response([{"is_running": False}])
    with patch.object(supabase_client, "http_client", mock_client):
        result = supabase_client.is_client_running("cli_001")
    assert result is False


# ─── 4. patch_signal ─────────────────────────────────────────────────────────

def test_patch_signal_returns_204():
    mock_client = MagicMock()
    mock_client.patch.return_value = _mock_response({}, status_code=204)
    with patch.object(supabase_client, "http_client", mock_client):
        code = supabase_client.patch_signal(42, {"status": "executed"})
    assert code == 204


# ─── 5. get_confirmed_signals — lista vazia ───────────────────────────────────

def test_get_confirmed_signals_empty():
    mock_client = MagicMock()
    mock_client.get.return_value = _mock_response([])
    with patch.object(supabase_client, "http_client", mock_client):
        result = supabase_client.get_confirmed_signals("cli_001")
    assert result == []


# ═══ NOVOS TESTES: Blindagem de rede ═══════════════════════════════════════════

# ─── 6. get_active_clients — 502 → fallback [] ───────────────────────────────

def test_get_active_clients_502_returns_empty():
    """Quando Supabase retorna 502, get_active_clients deve retornar [] sem crash."""
    mock_client = MagicMock()
    mock_client.get.return_value = _mock_502()
    with (
        patch.object(supabase_client, "http_client", mock_client),
        patch("supabase_client.time.sleep"),  # pula delays de retry
    ):
        result = supabase_client.get_active_clients()
    assert result == []


# ─── 7. is_client_running — RemoteProtocolError → fallback True ──────────────

def test_is_client_running_remote_protocol_error_returns_true():
    """Quando o servidor desconecta, is_client_running retorna True (não mata worker)."""
    mock_client = MagicMock()
    mock_client.get.side_effect = httpx.RemoteProtocolError(
        "Server disconnected without sending a response."
    )
    with (
        patch.object(supabase_client, "http_client", mock_client),
        patch("supabase_client.time.sleep"),
    ):
        result = supabase_client.is_client_running("cli_001")
    assert result is True


# ─── 8. is_client_running — timeout → fallback True ─────────────────────────

def test_is_client_running_timeout_returns_true():
    """Quando a requisição dá timeout, is_client_running retorna True."""
    mock_client = MagicMock()
    mock_client.get.side_effect = httpx.ReadTimeout("The read operation timed out")
    with (
        patch.object(supabase_client, "http_client", mock_client),
        patch("supabase_client.time.sleep"),
    ):
        result = supabase_client.is_client_running("cli_001")
    assert result is True


# ─── 9. _safe_request retries 3x antes de falhar ────────────────────────────

def test_safe_request_retries_max_times():
    """_safe_request deve tentar MAX_RETRIES vezes antes de retornar None."""
    mock_client = MagicMock()
    mock_client.get.side_effect = httpx.ConnectError("Connection refused")
    with (
        patch.object(supabase_client, "http_client", mock_client),
        patch("supabase_client.time.sleep"),
        patch("supabase_client.MAX_RETRIES", 3),
    ):
        result = supabase_client._safe_request("get", "https://fake.url", label="test")
    assert result is None
    assert mock_client.get.call_count == 3


# ─── 10. _safe_request succeeds on 2nd attempt ──────────────────────────────

def test_safe_request_succeeds_on_retry():
    """_safe_request deve retornar resposta válida se retry funciona."""
    good_resp = _mock_response({"ok": True})
    mock_client = MagicMock()
    mock_client.get.side_effect = [
        httpx.ConnectError("Connection refused"),
        good_resp,
    ]
    with (
        patch.object(supabase_client, "http_client", mock_client),
        patch("supabase_client.time.sleep"),
    ):
        result = supabase_client._safe_request("get", "https://fake.url", label="test")
    assert result is not None
    assert result.json() == {"ok": True}
    assert mock_client.get.call_count == 2
