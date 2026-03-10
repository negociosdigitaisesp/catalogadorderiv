"""
tests/test_supervisor.py
Testa 1 ciclo do supervisor (main loop) com mocks.
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import multiprocessing
from unittest.mock import MagicMock, patch, call


def test_supervisor_starts_worker():
    """
    Verifica que o supervisor lança 1 Process para 1 cliente ativo.
    Interrompe o loop infinito fazendo time.sleep levantar StopIteration
    após o primeiro ciclo.
    """
    fake_client = {
        "client_id": "cli_test",
        "iq_email":  "test@test.com",
        "iq_password": "secret",
        "balance_type": "PRACTICE",
    }

    mock_proc = MagicMock()
    mock_proc.is_alive.return_value = False  # simula processo não iniciado ainda

    with (
        patch("main.get_active_clients", return_value=[fake_client]),
        patch("main.multiprocessing.Process", return_value=mock_proc) as mock_process_cls,
        patch("main.time.sleep", side_effect=StopIteration),
    ):
        try:
            import main as supervisor_main
            supervisor_main.main()
        except StopIteration:
            pass  # ciclo único concluído — comportamento esperado

    # Confirma que Process foi criado com os args corretos
    mock_process_cls.assert_called_once_with(
        target=supervisor_main.run_client_worker,
        args=(fake_client,),
        name="worker-cli_test",
        daemon=True,
    )

    # Confirma que .start() foi chamado
    mock_proc.start.assert_called_once()
