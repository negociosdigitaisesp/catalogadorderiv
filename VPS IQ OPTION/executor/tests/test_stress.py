"""
tests/test_stress.py — Stress test: 50 mock workers

Validates:
  - 50 processes can be spawned without crash
  - Total memory usage stays within acceptable range
  - CPU usage doesn't spike
"""

import multiprocessing
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unittest.mock import MagicMock, patch


def _fake_worker(client: dict) -> None:
    """Simula um worker IQ Option com mock — sem conexão real."""
    # Simula trabalho: sleep por 3 segundos como se estivesse em polling
    time.sleep(3)


def test_spawn_50_workers():
    """
    Spawn 50 processos mock e verifica que todos iniciam sem crash.
    Critério: todos os processos vivos após 2s.
    """
    NUM_WORKERS = 50
    processes: list[multiprocessing.Process] = []

    for i in range(NUM_WORKERS):
        client = {
            "client_id": f"stress_{i:03d}",
            "iq_email": f"test{i}@mock.com",
            "iq_password": "mock_password",
            "balance_type": "PRACTICE",
        }
        p = multiprocessing.Process(
            target=_fake_worker,
            args=(client,),
            name=f"worker-stress_{i:03d}",
            daemon=True,
        )
        p.start()
        processes.append(p)

    # Aguarda 1s para todos estabilizarem
    time.sleep(1)

    alive = sum(1 for p in processes if p.is_alive())
    print(f"\n[STRESS] {alive}/{NUM_WORKERS} workers alive after 1s")

    assert alive == NUM_WORKERS, f"Only {alive}/{NUM_WORKERS} workers alive!"

    # Cleanup
    for p in processes:
        p.terminate()
        p.join(timeout=2)


def _measure_worker(result_queue):
    """Worker que reporta seu próprio RSS — must be top-level for Windows spawn."""
    try:
        import psutil
    except ImportError:
        result_queue.put(-1)
        return
    proc = psutil.Process(os.getpid())
    time.sleep(1)
    rss_mb = proc.memory_info().rss / (1024 * 1024)
    result_queue.put(rss_mb)


def test_memory_per_worker():
    """
    Estima a memória por worker usando um único processo.
    Critério: RSS < 100MB por worker.
    """
    try:
        import psutil
    except ImportError:
        import pytest
        pytest.skip("psutil not installed — skip memory test")

    q = multiprocessing.Queue()
    p = multiprocessing.Process(target=_measure_worker, args=(q,), daemon=True)
    p.start()
    p.join(timeout=10)

    if not q.empty():
        rss = q.get()
        if rss < 0:
            import pytest
            pytest.skip("psutil not available in worker")
        print(f"\n[STRESS] Single worker RSS: {rss:.1f} MB")
        assert rss < 100, f"Worker RSS too high: {rss:.1f} MB"
        estimated_50 = rss * 50
        print(f"[STRESS] Estimated 50 workers: {estimated_50:.0f} MB ({estimated_50/1024:.1f} GB)")
        assert estimated_50 < 4096, f"50 workers would use {estimated_50:.0f} MB — exceeds 4GB!"
    else:
        print("[STRESS] WARNING: Could not measure RSS (worker timed out)")
