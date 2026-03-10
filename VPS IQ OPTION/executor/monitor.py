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
