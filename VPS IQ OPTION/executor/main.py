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
from monitor import AlertManager
from supabase_client import get_active_clients, cleanup_stale_executing
from worker import run_client_worker

log = get_logger("SUPERVISOR")


def _stop_worker_process(proc: multiprocessing.Process, cid: str) -> bool:
    """Tenta encerrar processo de worker com terminate + kill fallback."""
    if not proc.is_alive():
        return True

    proc.terminate()
    proc.join(timeout=5)

    if not proc.is_alive():
        return True

    log.warning("Worker client_id=%s nao encerrou com terminate; forçando kill.", cid)
    try:
        proc.kill()
    except Exception as exc:
        log.error("Falha ao matar worker client_id=%s: %s", cid, exc)
        return False

    proc.join(timeout=2)
    if proc.is_alive():
        log.error("Worker client_id=%s ainda vivo apos kill.", cid)
        return False
    return True


def main() -> None:
    log.info("Executor supervisor iniciado")

    # client_id → Process
    active_processes: dict[str, multiprocessing.Process] = {}
    alert = AlertManager()

    while True:
        try:
            clients    = get_active_clients()

            # AlertManager: distingue lista vazia real de falha de rede
            # get_active_clients() retorna [] tanto em erro quanto em vazio normal;
            # usamos a ausência de exceção como sinal de sucesso de rede.
            alert.on_supabase_ok()

            active_ids = {c["client_id"] for c in clients}

            # Verifica workers duplicados a cada ciclo
            alert.check_duplicate_workers(active_processes)

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
                    log.info("Cliente desativado. Terminando worker client_id=%s", cid)
                    stopped = _stop_worker_process(proc, cid)
                    if stopped:
                        del active_processes[cid]
                    else:
                        log.warning(
                            "Worker client_id=%s mantido no mapa para evitar spawn duplicado.",
                            cid,
                        )

        except Exception as exc:
            log.error("Erro no supervisor: %s", exc)
            alert.on_supabase_error()
            # Backoff longo para não spammar Supabase em caso de erro
            time.sleep(30)
            continue

        time.sleep(POLL_INTERVAL_SEC)


if __name__ == "__main__":
    multiprocessing.set_start_method("spawn")
    main()
