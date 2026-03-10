"""
core/vps_sniper.py
===================
CAMADA B — O SNIPER DE AGENDA (Online / VPS Backend)

Responsabilidade:
  - Ler a grade_horaria do config.json gerado pelo Oráculo.
  - Manter UMA conexão WebSocket com a Deriv APENAS para sincronizar o
    epoch oficial (relógio de precisão). NUNCA datetime.now().
  - Monitorar os horários agendados com asyncio (loop 1 segundo).
  - Ao detectar: Horário_Alvo - 10 segundos (segundo :50):
      → Envia PRE_SIGNAL para a tabela hft_catalogo_estrategias no Supabase.
  - Ao detectar: segundo :00 exato do horário alvo:
      → Envia CONFIRMED para a mesma tabela.
  - Multi-ativo: até 10 sinais concorrentes usando asyncio.gather.

DESIGN DE RAM (<50MB):
  - Agenda carregada como lista plana de dicts (não DataFrames).
  - WebSocket broadcast de ticks descartado logo após extrair epoch.
  - Sem histórico de velas na RAM.
  - deque fixo de max 1440 sinais disparados (ring-buffer de auditoria).

REGRAS PRD ABSOLUTAS:
  - NUNCA datetime.now() → usa epoch da Deriv via WebSocket.
  - NUNCA indicadores técnicos.
  - NUNCA salvar ticks no banco.
  - Loops assíncronos (asyncio + websockets).
  - Reconexão com Exponential Backoff no WebSocket.

FLUXO TEMPORAL:
  t = epoch Deriv (segundos)
  hh_mm_alvo = "14:30"
  segundo_alvo = epoch do minuto 14:30:00
  PRE_SIGNAL  → t == segundo_alvo - 10  (14:29:50)
  CONFIRMED   → t == segundo_alvo        (14:30:00)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import random
from collections import deque
from pathlib import Path
from typing import Any, Optional

import websockets
from supabase import create_client, Client

logger = logging.getLogger(__name__)

# ─── Constantes ───────────────────────────────────────────────────────────────
_DERIV_WS            = "wss://ws.binaryws.com/websockets/v3"
_WS_RECONNECT_BASE   = 2.0      # segundos base para backoff
_WS_RECONNECT_MAX    = 60.0     # teto do backoff
_TICK_TIMEOUT        = 5.0      # tempo máximo para esperar 1 tick (sec)
_LOOP_INTERVAL       = 0.90     # intervalo do loop principal (sec) — < 1s p/ compensar drift
_PRE_SIGNAL_OFFSET   = 10       # seconds before target: disparo do PRE_SIGNAL
_SIGNAL_TABLE        = "hft_catalogo_estrategias"
_MAX_AUDIT_BUFFER    = 1440     # ring-buffer de sinais disparados (1 dia de minutos)

# Dias da semana: Python weekday() → 0 = Segunda, 6 = Domingo
_WEEKDAY_MAP = {0: "SEG", 1: "TER", 2: "QUA", 3: "QUI", 4: "SEX", 5: "SAB", 6: "DOM"}


# ─────────────────────────────────────────────────────────────────────────────
# 1. SINCRONIZADOR DE EPOCH (WebSocket Deriv)
# ─────────────────────────────────────────────────────────────────────────────

class EpochSync:
    """
    Mantém o epoch oficial da Deriv atualizado em background.

    Estratégia:
      - Assina o stream `ticks` de um ativo líquido (R_10) apenas para
        capturar o campo `epoch` do JSON →  descarta o resto.
      - Em caso de falha, usa o último epoch conhecido + tempo decorrido
        como fallback temporário (nunca datetime.now()).
      - Reconexão com exponential backoff + jitter.
    """

    def __init__(self, app_id: str) -> None:
        self.app_id     = app_id
        self._epoch:    int  = 0       # epoch mais recente da Deriv
        self._local_ts: float = 0.0    # asyncio.get_event_loop().time() no momento
        self._lock      = asyncio.Lock()
        self._ready     = asyncio.Event()

    @property
    def epoch(self) -> int:
        """Retorna o epoch Deriv estimado no momento atual."""
        if self._epoch == 0:
            return 0
        elapsed = asyncio.get_event_loop().time() - self._local_ts
        return self._epoch + int(elapsed)

    @property
    def is_ready(self) -> bool:
        return self._epoch > 0

    async def run(self) -> None:
        """Loop de sincronização com reconexão automática (Exponential Backoff)."""
        backoff = _WS_RECONNECT_BASE
        url = f"{_DERIV_WS}?app_id={self.app_id}"

        while True:
            try:
                import socket
                async with websockets.connect(
                    url,
                    ping_interval=20,
                    ping_timeout=30,
                    close_timeout=10,
                    family=socket.AF_INET,  # Força IPv4 para evitar timeout de rota IPv6
                ) as ws:
                    # Subscreve ticks do R_10 (ativo sempre aberto, mínima latência)
                    await ws.send(json.dumps({"ticks": "R_10", "subscribe": 1}))
                    backoff = _WS_RECONNECT_BASE   # reset ao conectar com sucesso

                    async for raw in ws:
                        data = json.loads(raw)
                        epoch = (
                            data.get("tick",       {}).get("epoch")
                            or data.get("history",  {}).get("times", [None])[-1]
                            or data.get("time",     {}).get("epoch")
                            or data.get("epoch")
                        )
                        if epoch:
                            async with self._lock:
                                self._epoch    = int(epoch)
                                self._local_ts = asyncio.get_event_loop().time()
                            if not self._ready.is_set():
                                self._ready.set()
                                logger.info("[EPOCH] Sincronizado com Deriv: epoch=%d", self._epoch)

            except asyncio.CancelledError:
                logger.info("[EPOCH] Cancelado.")
                return
            except Exception as exc:
                logger.warning("[EPOCH] Erro WS: %s | Reconectando em %.0fs...", exc, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2 + random.uniform(0, 1), _WS_RECONNECT_MAX)

    async def wait_ready(self, timeout: float = 30.0) -> bool:
        """Aguarda a primeira sincronização (com timeout)."""
        try:
            await asyncio.wait_for(self._ready.wait(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            logger.error("[EPOCH] Timeout aguardando sync com Deriv!")
            return False


# ─────────────────────────────────────────────────────────────────────────────
# 2. DECODIFICADOR DA AGENDA (config.json → lista plana)
# ─────────────────────────────────────────────────────────────────────────────

def _parse_agenda(config_path: str) -> list[dict]:
    """
    Lê o config.json e extrai a grade_horaria como lista plana de dicts.

    Cada item contém:
      hh: int, mm: int, ativo: str, direcao: str, hh_mm: str,
      status: str, sizing_override: float, strategy_id: str,
      win_rate_g2: float, ev_gale2: float, variacao: str,
      n_win_1a: int, n_win_g1: int, n_win_g2: int, n_hit: int, n_total: int
    """
    path = Path(config_path)
    if not path.exists():
        logger.error("[AGENDA] config.json não encontrado: %s", config_path)
        return []

    with open(path, "r", encoding="utf-8") as fp:
        raw = json.load(fp)

    # Suporta dois formatos:
    # 1. {"grade_horaria": [...]}    (novo formato do Oráculo v2)
    # 2. {"T1430_...": {...}, ...}   (formato legado dict-of-dicts)
    if "grade_horaria" in raw:
        entries = raw["grade_horaria"]
    elif isinstance(raw, list):
        entries = raw
    else:
        # Legado: dicionário de strategy_id -> dict
        entries = list(raw.values())

    agenda: list[dict] = []
    for e in entries:
        hh_mm = e.get("hh_mm") or e.get("horario_alvo")
        if not hh_mm:
            continue

        try:
            hh, mm = map(int, hh_mm.split(":"))
        except ValueError:
            continue

        config_otimizada = e.get("config_otimizada", {}) or {}

        agenda.append({
            "strategy_id":    e.get("strategy_id", f"T{hh_mm.replace(':','')}_{e.get('ativo','?')}"),
            "hh":             hh,
            "mm":             mm,
            "hh_mm":          hh_mm,
            "ativo":          e.get("ativo", "?"),
            "direcao":        e.get("direcao") or config_otimizada.get("direcao", "CALL"),
            "status":         e.get("status", "APROVADO"),
            "sizing_override": float(e.get("stake") or e.get("sizing_override") or 1.0),
            "win_rate_g2":    float(e.get("win_rate_g2") or e.get("win_rate") or 0.0),
            "ev_gale2":       float(e.get("ev_gale2")   or e.get("ev_real")   or 0.0),
            "variacao":       e.get("variacao") or e.get("variacao_estrategia") or "V1",
            "n_win_1a":       int(e.get("n_win_1a", 0)),
            "n_win_g1":       int(e.get("n_win_g1", 0) or e.get("n_gale1", 0)),
            "n_win_g2":       int(e.get("n_win_g2", 0) or e.get("n_gale2", 0)),
            "n_hit":          int(e.get("n_hit", 0)),
            "n_total":        int(e.get("n_total", 0)),
            "win_1a_rate":    float(e.get("win_1a_rate") or e.get("p_1a") or 0.0),
            "win_gale1_rate": float(e.get("win_gale1_rate") or e.get("p_gale1") or 0.0),
            "win_gale2_rate": float(e.get("win_gale2_rate") or e.get("p_gale2") or 0.0),
            "hit_rate":       float(e.get("hit_rate") or e.get("p_hit") or 0.0),
        })

    logger.info("[AGENDA] %d horários carregados do config.json", len(agenda))
    return agenda


# ─────────────────────────────────────────────────────────────────────────────
# 3. DISPARADOR DE SINAL (Supabase INSERT)
# ─────────────────────────────────────────────────────────────────────────────

async def _disparar_sinal(
    sb: Client,
    slot: dict,
    tipo: str,     # "PRE_SIGNAL" ou "CONFIRMED"
    epoch: int,
    audit: deque,
    table_name: str,
    client_id: str,
) -> None:
    """
    Insere um sinal (PRE_SIGNAL ou CONFIRMED) na tabela especificada no Supabase.

    O campo `contexto` carrega o snapshot estatístico que o Front-end
    exibirá ao cliente para justificar a entrada.
    """
    sinal_id = f"{tipo}_{slot['strategy_id']}_{epoch}_{client_id}"

    # Proteção anti-duplicata (ring-buffer de IDs recentes)
    if sinal_id in audit:
        logger.debug("[SNIPER] Sinal duplicado ignorado: %s", sinal_id)
        return
    audit.append(sinal_id)

    payload = {
        "ativo":            slot["ativo"],
        "estrategia":       slot["strategy_id"],
        "direcao":          slot["direcao"],
        "p_win_historica":  slot["win_rate_g2"],
        "status":           tipo,
        "timestamp_sinal":  epoch,
        "contexto": {
            "win_counts": {
                "direct": slot["n_win_1a"],
                "gale_1": slot["n_win_g1"],
                "gale_2": slot["n_win_g2"],
                "hits":   slot["n_hit"],
            },
            "metrics": {
                "win_rate_g2":  slot["win_rate_g2"],
                "win_rate_1a":  slot["win_1a_rate"],
                "ev_gale2":     slot["ev_gale2"],
                "sizing":       slot["sizing_override"],
            },
            "execution": {
                "v_strategy":       slot["variacao"],
                "max_gale_allowed": 2,
                "hh_mm_target":     slot["hh_mm"],
                "strategy_status":  slot["status"],
            },
        },
    }

    # The centralized raw metrics table doesn't have client_id in the schema cache
    if table_name != "hft_catalogo_estrategias":
        payload["client_id"] = client_id

    try:
        print(f"DEBUG DB: Payload sendo enviado: {payload}")
        await asyncio.to_thread(
            lambda: sb.table(table_name).insert(payload).execute()
        )
        logger.info(
            "[SNIPER] %-12s %s @ %s → %s (sizing=%.1fx | WR=%.1f%%)",
            tipo,
            slot["ativo"],
            slot["hh_mm"],
            slot["direcao"],
            slot["sizing_override"],
            slot["win_rate_g2"] * 100,
        )
        print(f"DEBUG DB: INSERT concluido com sucesso para {sinal_id}")
    except Exception as exc:
        logger.error(
            "[SNIPER] Erro ao inserir sinal %s para %s @ %s: %s",
            tipo, slot["ativo"], slot["hh_mm"], exc,
        )
        print(f"DEBUG DB: ERRO no INSERT - {exc}")


# ─────────────────────────────────────────────────────────────────────────────
# 4. CLASSE PRINCIPAL: DerivSniper
# ─────────────────────────────────────────────────────────────────────────────

class DerivSniper:
    """
    Sniper de Agenda de Elite — Camada B do Oracle Quant.

    Coordena:
      - EpochSync   → relógio oficial da Deriv
      - Agenda      → grade_horaria do config.json
      - Loop        → polling a cada ~0.9s para detectar janelas de disparo
      - Sinais      → PRE_SIGNAL (t-10s) e CONFIRMED (t+0s)
    """

    def __init__(
        self,
        config: dict | str,
        app_id:  str,
        token:   Optional[str],
        db:      Any,
        config_path: str = "config.json",
        table_name: str = _SIGNAL_TABLE,
        client_id: str = "GLOBAL",
    ) -> None:
        # Suporta tanto config já carregado quanto path para o arquivo
        if isinstance(config, str):
            config_path = config
            self._agenda = _parse_agenda(config_path)
        else:
            # config é o dict completo do config.json
            # Salva temporariamente para _parse_agenda
            import tempfile, json as _json
            tmp = tempfile.NamedTemporaryFile(
                mode="w", suffix=".json", delete=False, encoding="utf-8"
            )
            _json.dump(config, tmp)
            tmp.close()
            self._agenda = _parse_agenda(tmp.name)

        self._app_id   = str(app_id)
        self._token    = token
        self._sb       = db.client if hasattr(db, "client") else db
        self._epoch_sync = EpochSync(self._app_id)
        self._audit:  deque = deque(maxlen=_MAX_AUDIT_BUFFER)
        self._table_name = table_name
        self._client_id = client_id

        # Flag anti-duplo: garante 1 disparo por (tipo, strategy_id) por segundo.
        # Chave: "PRE_SIGNAL_T1430_SEG_R100_G2"  Valor: epoch_segundo em que disparou
        self._sent_this_second: dict[str, int] = {}

        # Trava do MINUTO SOBERANO: "PRE_hh_mm" / "CONFIRMED_hh_mm" → epoch_minuto
        # Garante que no máximo 1 sinal seja disparado por (tipo, hh_mm) por minuto,
        # mesmo que a agenda contenha múltiplos ativos para o mesmo horário.
        # Chave: "PRE_14:30"  Valor: epoch // 60 no momento do disparo
        self._minuto_soberano_fired: dict[str, int] = {}

        # Mapa: "HH:MM" → [slot, slot, ...]  (multi-ativo por horário)
        self._agenda_index: dict[str, list[dict]] = {}
        for slot in self._agenda:
            key = slot["hh_mm"]
            self._agenda_index.setdefault(key, []).append(slot)

        logger.info(
            "[SNIPER] Agenda com %d horários únicos | %d ativos",
            len(self._agenda_index),
            len(self._agenda),
        )

    # -------------------------------------------------------------------------
    # _check_triggers — núcleo do loop de decisão
    # -------------------------------------------------------------------------

    def _ja_disparou(self, tipo: str, strategy_id: str, epoch_agora: int) -> bool:
        """
        Retorna True se este (tipo, strategy_id) já foi disparado neste exato
        segundo de epoch. Registra o disparo se for a primeira vez.

        Garante: apenas 1 db.save_signal por ativo por segundo (mesmo que o
        loop de 0.9s execute mais de uma vez dentro do mesmo epoch-segundo).
        """
        key = f"{tipo}_{strategy_id}"
        if self._sent_this_second.get(key) == epoch_agora:
            logger.debug("[SNIPER] Bloqueado (sent_in_this_second): %s @ epoch=%d", key, epoch_agora)
            return True
        self._sent_this_second[key] = epoch_agora
        return False

    async def _check_triggers(self) -> None:
        """
        Verifica se o epoch atual bate com algum gatilho de disparo.

        Lógica:
          epoch_agora    = epoch Deriv (segundos)
          HH:MM:SS       = decompõe epoch
          segundo_alvo   = epoch_agora arredondado para o minuto exato (ss=00)
          PRE_SIGNAL quando ss == 50 e hh:mm+1 coincide com um slot agendado
          CONFIRMED  quando ss == 00 e hh:mm    coincide com um slot agendado

        Proteção anti-duplo:
          _ja_disparou() garante um único disparo por (tipo, ativo) por second.
        """
        epoch_agora = self._epoch_sync.epoch
        if epoch_agora == 0:
            return

        ss       = epoch_agora % 60
        mm_epoch = (epoch_agora // 60) % 60
        hh_epoch = (epoch_agora // 3600) % 24

        # PRE_SIGNAL: segundo :50 → dispara para o PRÓXIMO minuto (:xx+1:00)
        if ss == 50:
            total_min   = hh_epoch * 60 + mm_epoch + 1
            hh_prox     = (total_min // 60) % 24
            mm_prox     = total_min % 60
            alvo_hh_mm  = f"{hh_prox:02d}:{mm_prox:02d}"

            if alvo_hh_mm in self._agenda_index:
                # ── TRAVA DO MINUTO SOBERANO ────────────────────────────────
                # epoch_minuto identifica unicamente este slot de 60s.
                # Se já disparamos PRE_SIGNAL para este hh_mm neste minuto,
                # o sistema está em modo duplicado — bloqueia imediatamente.
                epoch_minuto   = epoch_agora // 60
                sovereign_key  = f"PRE_{alvo_hh_mm}"
                if self._minuto_soberano_fired.get(sovereign_key) == epoch_minuto:
                    logger.info(
                        "[SOVEREIGN] PRE_SIGNAL para %s ja disparado neste minuto (epoch_min=%d). Bloqueando.",
                        alvo_hh_mm, epoch_minuto,
                    )
                    return
                # ────────────────────────────────────────────────────────────

                epoch_confirmado = epoch_agora + 10

                slots = self._agenda_index[alvo_hh_mm]
                tarefas = [
                    _disparar_sinal(
                        self._sb, slot, "PRE_SIGNAL", epoch_confirmado, self._audit, self._table_name, self._client_id
                    )
                    for slot in slots
                    if not self._ja_disparou("PRE_SIGNAL", slot["strategy_id"], epoch_agora)
                ]
                if tarefas:
                    self._minuto_soberano_fired[sovereign_key] = epoch_minuto
                    
                    async def _fire_seq(tasks):
                        for t in tasks:
                            try:
                                await t
                                await asyncio.sleep(0.1) # Stagger requests
                            except Exception as e:
                                logger.error("[SNIPER] Erro no _fire_seq (PRE_SIGNAL): %s", e)

                    asyncio.create_task(_fire_seq(tarefas), name=f"pre_signal_{alvo_hh_mm}")

        # CONFIRMED: segundo :00 exato → dispara para este minuto
        elif ss == 0:
            alvo_hh_mm = f"{hh_epoch:02d}:{mm_epoch:02d}"

            if alvo_hh_mm in self._agenda_index:
                # ── TRAVA DO MINUTO SOBERANO ────────────────────────────────
                epoch_minuto  = epoch_agora // 60
                sovereign_key = f"CONFIRMED_{alvo_hh_mm}"
                if self._minuto_soberano_fired.get(sovereign_key) == epoch_minuto:
                    logger.info(
                        "[SOVEREIGN] CONFIRMED para %s ja disparado neste minuto (epoch_min=%d). Bloqueando.",
                        alvo_hh_mm, epoch_minuto,
                    )
                    return
                # ────────────────────────────────────────────────────────────

                slots = self._agenda_index[alvo_hh_mm]
                tarefas = [
                    _disparar_sinal(
                        self._sb, slot, "CONFIRMED", epoch_agora, self._audit, self._table_name, self._client_id
                    )
                    for slot in slots
                    if not self._ja_disparou("CONFIRMED", slot["strategy_id"], epoch_agora)
                ]
                if tarefas:
                    self._minuto_soberano_fired[sovereign_key] = epoch_minuto
                    
                    async def _fire_seq(tasks):
                        for t in tasks:
                            try:
                                await t
                                await asyncio.sleep(0.1) # Stagger requests
                            except Exception as e:
                                logger.error("[SNIPER] Erro no _fire_seq (CONFIRMED): %s", e)

                    asyncio.create_task(_fire_seq(tarefas), name=f"confirmed_{alvo_hh_mm}")

    # -------------------------------------------------------------------------
    # _main_loop — polling de 1 segundo
    # -------------------------------------------------------------------------

    async def _main_loop(self) -> None:
        """Loop principal de monitoramento (polling ~0.9s)."""
        logger.info("[SNIPER] Loop de monitoramento ativo.")
        while True:
            await self._check_triggers()
            await asyncio.sleep(_LOOP_INTERVAL)

    # -------------------------------------------------------------------------
    # run — ponto de entrada público
    # -------------------------------------------------------------------------

    async def run(self) -> None:
        """
        Inicia o Sniper completo — loop de supervisão 24/7.

        Arquitetura:
          - epoch_task: WebSocket Deriv (reconexão automática já embutida)
          - loop_task:  Polling de agenda 0.9s/iteração (while True permanente)

        Supervisão:
          - Se qualquer task crashar (exceto CancelledError), loga o erro
            com traceback completo e reinicia a task.
          - NUNCA sai silenciosamente. Só para com Ctrl+C.
        """
        logger.info("[SNIPER] Iniciando... app_id=%s | slots=%d", self._app_id, len(self._agenda))
        logger.info("[SNIPER] Aguardando sincronização com Deriv WebSocket...")

        async def supervise_epoch() -> None:
            """Wrapper que reinicia epoch_sync em caso de crash inesperado."""
            backoff = 2.0
            while True:
                try:
                    await self._epoch_sync.run()
                    logger.warning("[SNIPER] epoch_sync terminou inesperadamente — reiniciando em 2s...")
                except asyncio.CancelledError:
                    logger.info("[SNIPER] epoch_sync cancelado.")
                    return
                except Exception as exc:
                    logger.error("[SNIPER] epoch_sync CRASH: %s — reiniciando em %.0fs", exc, backoff, exc_info=True)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60.0)

        async def supervise_loop() -> None:
            """Wrapper que reinicia o main_loop em caso de crash inesperado."""
            backoff = 1.0
            while True:
                try:
                    await self._main_loop()
                    logger.warning("[SNIPER] main_loop terminou inesperadamente — reiniciando em 1s...")
                except asyncio.CancelledError:
                    logger.info("[SNIPER] main_loop cancelado.")
                    return
                except Exception as exc:
                    logger.error("[SNIPER] main_loop CRASH: %s — reiniciando em %.0fs", exc, backoff, exc_info=True)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30.0)

        # Lança as duas tasks supervisionadas
        epoch_task = asyncio.create_task(supervise_epoch(), name="epoch_sync")
        loop_task  = asyncio.create_task(supervise_loop(), name="sniper_loop")

        # Aguarda sincronização inicial com a Deriv (timeout 30s)
        ok = await self._epoch_sync.wait_ready(timeout=30.0)
        if ok:
            logger.info("[SNIPER] ✅ Epoch sincronizado. Loop de monitoramento iniciado!")
        else:
            logger.warning("[SNIPER] ⚠️  Timeout na sincronização com Deriv. Continuando em modo degradado.")

        # Supervisor principal: aguarda qualquer task terminar (não deveria)
        try:
            done, _pending = await asyncio.wait(
                {epoch_task, loop_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in done:
                try:
                    exc = task.exception()
                    if exc:
                        logger.critical("[SNIPER] Task '%s' encerrou com exceção: %s", task.get_name(), exc, exc_info=True)
                except asyncio.CancelledError:
                    logger.info("[SNIPER] Task '%s' foi cancelada.", task.get_name())

        except asyncio.CancelledError:
            logger.info("[SNIPER] Encerrado pelo operador (CancelledError).")
        finally:
            logger.info("[SNIPER] Encerrando tasks...")
            for task in [epoch_task, loop_task]:
                if not task.done():
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass
            logger.info("[SNIPER] Todas as tasks encerradas. Sniper offline.")



# ─────────────────────────────────────────────────────────────────────────────
# 5. AUXILIAR: SupabaseManager (se não houver core/database.py)
# ─────────────────────────────────────────────────────────────────────────────

class SupabaseManager:
    """
    Wrapper mínimo do cliente Supabase.
    Compatível com o import em run_sniper.py:
        from core.database import SupabaseManager
    """

    def __init__(self, url: str, key: str) -> None:
        self.client: Client = create_client(url, key)
        logger.info("[DB] Supabase conectado: %s", url[:40])
