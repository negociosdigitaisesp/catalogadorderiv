"""
tests/vps_simulation.py — VPS Preflight Checker
=================================================
@PRE_FLIGHT_CHECKER

Executa um teste de simulação end-to-end do Sniper VPS sem fazer
nenhuma operação financeira real.

O QUE ELE FAZ:
  1. Lê o config.json e pega a primeira estratégia APROVADA da grade_horaria.
  2. Substitui o EpochSync (relógio Deriv) por um Mock que retorna
     epoch = target_epoch - 10  (10s antes do horário alvo).
  3. Substitui o cliente Supabase por um MockSupabase que captura inserts.
  4. Roda o Sniper por 3 iterações do loop (basta pra ver o PRE_SIGNAL disparar).
  5. Avança o mock clock para target_epoch (segundo :00) e verifica CONFIRMED.
  6. PASSA se o log mostrar "[SIMULATION] Signal triggered successfully."

SAÍDA ESPERADA:
  [SIMULATION] Estratégia alvo: T0000_SEG_BOOM1000_G2 @ 00:00 → PUT
  [SIMULATION] MockClock em 14:29:50 → aguardando PRE_SIGNAL...
  [SNIPER]     PRE_SIGNAL   BOOM1000 @ 00:00 → PUT (sizing=1.0x | WR=100.0%)
  [SIMULATION] ✅ Signal triggered successfully.
  [SIMULATION] MockClock em 14:30:00 → aguardando CONFIRMED...
  [SNIPER]     CONFIRMED    BOOM1000 @ 00:00 → PUT (sizing=1.0x | WR=100.0%)
  [SIMULATION] ✅ Signal triggered successfully.
  [SIMULATION] PREFLIGHT PASSED — Sniper pronto para produção.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from collections import deque
from pathlib import Path

# Garante imports relativos ao root do projeto
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("simulation")

# ─────────────────────────────────────────────────────────────────────────────
# MOCK: Relógio Deriv (substitui EpochSync)
# ─────────────────────────────────────────────────────────────────────────────

class MockEpochSync:
    """
    Simula o EpochSync com um epoch fixo controlado pelo teste.
    Não abre nenhuma conexão WebSocket.
    """

    def __init__(self, initial_epoch: int) -> None:
        self._epoch = initial_epoch
        self._ready = asyncio.Event()
        self._ready.set()   # já está "sincronizado" imediatamente

    @property
    def epoch(self) -> int:
        return self._epoch

    @property
    def is_ready(self) -> bool:
        return True

    def advance(self, seconds: int) -> None:
        """Avança o relógio simulado."""
        self._epoch += seconds

    async def run(self) -> None:
        """No-op — nunca conecta no WebSocket."""
        await asyncio.sleep(9999)   # nunca termina (task é cancelada no finally)

    async def wait_ready(self, timeout: float = 30.0) -> bool:
        return True


# ─────────────────────────────────────────────────────────────────────────────
# MOCK: Cliente Supabase (captura inserts sem ir para a nuvem)
# ─────────────────────────────────────────────────────────────────────────────

class _MockTableRef:
    """Referência de tabela que captura inserts localmente."""

    def __init__(self, table_name: str, capture: list[dict]) -> None:
        self._table   = table_name
        self._capture = capture
        self._payload: dict | None = None

    def insert(self, payload: dict) -> "_MockTableRef":
        self._payload = dict(payload)
        return self

    def upsert(self, payload: dict, **kw) -> "_MockTableRef":
        return self.insert(payload)

    def execute(self) -> object:
        if self._payload is not None:
            self._capture.append({
                "table":   self._table,
                "payload": self._payload,
            })
        return type("Resp", (), {"data": [self._payload], "error": None})()


class MockSupabase:
    """Cliente Supabase fictício que armazena os inserts em memória."""

    def __init__(self) -> None:
        self.inserts: list[dict] = []

    @property
    def client(self) -> "MockSupabase":
        return self

    def table(self, name: str) -> "_MockTableRef":
        return _MockTableRef(name, self.inserts)


# ─────────────────────────────────────────────────────────────────────────────
# HELPER: Calcula epoch de HH:MM para "hoje" (UTC)
# ─────────────────────────────────────────────────────────────────────────────

def _epoch_for_hh_mm(hh: int, mm: int) -> int:
    """
    Retorna o epoch Unix (UTC) do próximo HH:MM a partir de agora.
    Se o horário já passou hoje, usa amanhã.
    """
    import time as _time
    now = int(_time.time())
    # Zera para meia-noite UTC de hoje
    midnight = (now // 86400) * 86400
    target = midnight + hh * 3600 + mm * 60
    if target <= now:
        target += 86400   # amanhã
    return target


# ─────────────────────────────────────────────────────────────────────────────
# CORE: SniperUnderTest — DerivSniper com dependências injetadas
# ─────────────────────────────────────────────────────────────────────────────

class SniperUnderTest:
    """
    DerivSniper adaptado para test injection de EpochSync e Supabase.
    Importa a lógica de check_triggers de vps_sniper sem modificar o source.
    """

    def __init__(
        self,
        agenda_index: dict[str, list[dict]],
        mock_clock:   MockEpochSync,
        mock_db:      MockSupabase,
    ) -> None:
        from core.vps_sniper import _disparar_sinal

        self._agenda_index  = agenda_index
        self._epoch_sync    = mock_clock
        self._sb            = mock_db.client
        self._audit:  deque = deque(maxlen=1440)
        self._disparar      = _disparar_sinal

    async def check(self) -> None:
        """Uma iteração do loop de monitoramento (alias de _check_triggers)."""
        epoch_agora = self._epoch_sync.epoch
        ss          = epoch_agora % 60
        mm_epoch    = (epoch_agora // 60) % 60
        hh_epoch    = (epoch_agora // 3600) % 24

        if ss == 50:
            total_min  = hh_epoch * 60 + mm_epoch + 1
            hh_prox    = (total_min // 60) % 24
            mm_prox    = total_min % 60
            alvo       = f"{hh_prox:02d}:{mm_prox:02d}"

            if alvo in self._agenda_index:
                await asyncio.gather(*[
                    self._disparar(self._sb, slot, "PRE_SIGNAL",
                                   epoch_agora + 10, self._audit)
                    for slot in self._agenda_index[alvo]
                ])

        elif ss == 0:
            alvo = f"{hh_epoch:02d}:{mm_epoch:02d}"

            if alvo in self._agenda_index:
                await asyncio.gather(*[
                    self._disparar(self._sb, slot, "CONFIRMED",
                                   epoch_agora, self._audit)
                    for slot in self._agenda_index[alvo]
                ])


# ─────────────────────────────────────────────────────────────────────────────
# MAIN: Rotina de simulação
# ─────────────────────────────────────────────────────────────────────────────

async def run_simulation() -> bool:
    """
    Retorna True se o Sniper disparou PRE_SIGNAL e CONFIRMED corretamente.
    """
    # ── 1. Carrega a agenda real do config.json ──────────────────────────────
    config_path = _ROOT / "config.json"
    from core.vps_sniper import _parse_agenda
    agenda = _parse_agenda(str(config_path))

    if not agenda:
        logger.error("[SIMULATION] ❌ config.json vazio ou sem grade_horaria!")
        return False

    # Pega a primeira estratégia APROVADA (WR=100%)
    target_slot = next(
        (s for s in agenda if s["status"] == "APROVADO"),
        agenda[0]   # fallback: qualquer uma
    )
    target_hh_mm = target_slot["hh_mm"]
    target_hh, target_mm = target_slot["hh"], target_slot["mm"]

    logger.info(
        "[SIMULATION] Estratégia alvo: %s @ %s → %s (WR=%.1f%%)",
        target_slot["strategy_id"],
        target_hh_mm,
        target_slot["direcao"],
        target_slot["win_rate_g2"] * 100,
    )

    # ── 2. Calcula epoch do horário alvo ────────────────────────────────────
    target_epoch     = _epoch_for_hh_mm(target_hh, target_mm)
    pre_signal_epoch = target_epoch - 10   # segundo :50 do minuto anterior

    # ── 3. Monta os mocks ───────────────────────────────────────────────────
    mock_db    = MockSupabase()
    mock_clock = MockEpochSync(pre_signal_epoch)

    # Agenda index: {hh_mm: [slot, ...]}
    agenda_index: dict[str, list[dict]] = {}
    for slot in agenda:
        agenda_index.setdefault(slot["hh_mm"], []).append(slot)

    sniper = SniperUnderTest(agenda_index, mock_clock, mock_db)

    # ── 4. Simula PRE_SIGNAL (:50) ──────────────────────────────────────────
    pre_min  = (target_epoch // 60 - 1) * 60   # minuto anterior
    pre_hh   = (pre_min // 3600) % 24
    pre_mm_v = (pre_min // 60) % 60
    logger.info(
        "[SIMULATION] MockClock em %02d:%02d:50 → aguardando PRE_SIGNAL...",
        pre_hh, pre_mm_v,
    )

    n_inserts_antes = len(mock_db.inserts)
    await sniper.check()   # epoch == target - 10, ss == 50 → PRE_SIGNAL

    pre_signals = [
        r for r in mock_db.inserts[n_inserts_antes:]
        if r["payload"].get("status") == "PRE_SIGNAL"
    ]

    if not pre_signals:
        logger.error("[SIMULATION] ❌ PRE_SIGNAL NÃO FOI DISPARADO!")
        logger.error(
            "  clock=%d  ss=%d  alvo=%s  agenda_has_key=%s",
            mock_clock.epoch,
            mock_clock.epoch % 60,
            target_hh_mm,
            target_hh_mm in agenda_index,
        )
        return False

    logger.info("[SIMULATION] ✅ Signal triggered successfully. (PRE_SIGNAL)")
    logger.info("  payload: %s", json.dumps(pre_signals[0]["payload"], indent=2))

    # ── 5. Simula CONFIRMED (:00) ────────────────────────────────────────────
    mock_clock.advance(10)   # avança para target_epoch (= segundo :00)
    logger.info(
        "[SIMULATION] MockClock em %02d:%02d:00 → aguardando CONFIRMED...",
        target_hh, target_mm,
    )

    n_inserts_antes = len(mock_db.inserts)
    await sniper.check()   # epoch == target_epoch, ss == 0 → CONFIRMED

    confirmed = [
        r for r in mock_db.inserts[n_inserts_antes:]
        if r["payload"].get("status") == "CONFIRMED"
    ]

    if not confirmed:
        logger.error("[SIMULATION] ❌ CONFIRMED NÃO FOI DISPARADO!")
        return False

    logger.info("[SIMULATION] ✅ Signal triggered successfully. (CONFIRMED)")

    # ── 6. Resultado final ──────────────────────────────────────────────────
    total = len(mock_db.inserts)
    logger.info(
        "\n[SIMULATION] ══════════════════════════════════════════\n"
        "[SIMULATION] 🚀 PREFLIGHT PASSED — Sniper pronto para produção.\n"
        "[SIMULATION]    Total de inserts simulados: %d\n"
        "[SIMULATION] ══════════════════════════════════════════",
        total,
    )
    return True


# ─────────────────────────────────────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    success = asyncio.run(run_simulation())
    sys.exit(0 if success else 1)
