"""
worker.py — Worker por Cliente (Candle-Close + Gale Instantâneo)

Arquitetura:
  - ZERO polling de api.get_async_order(). Resultado via fechamento de vela.
  - Gale disparado em < 200ms após detectar LOSS pelo candle close.
  - iq_gale_state no Supabase é a FONTE DE VERDADE para retomada pós-crash.

Loop principal (state-driven):
  PRIORIDADE 1 — Checar iq_gale_state. Se loss_gN → disparar G(N+1).
  PRIORIDADE 2 — Buscar sinais novos CONFIRMED. Executar G0.
"""
import time


from iqoptionapi.stable_api import IQ_Option

from config import HEARTBEAT_INTERVAL_SEC, POLL_INTERVAL_SEC, IQ_PROXY, RISK_CONFIG_TTL_SEC
from logger import get_logger
from supabase_client import (
    claim_signal,
    delete_gale_state,
    get_any_pending_gale,
    get_confirmed_signals,
    get_session_config,
    get_session_pnl,
    get_signal_by_id,
    insert_trade_result,
    is_client_running,
    patch_signal,
    update_heartbeat,
    upsert_gale_state,
)

# ── Constantes de Gale ────────────────────────────────────────────────────────
GALE_MULTIPLIERS = {0: 1.0, 1: 2.0, 2: 4.0}
GALE_MAX_LEVEL   = 2


# ═══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def _mask_email(email: str) -> str:
    """Mascara email para logs: m***9@gmail.com"""
    try:
        local, domain = email.split("@", 1)
        if len(local) > 2:
            return f"{local[0]}{'*' * (len(local) - 2)}{local[-1]}@{domain}"
        return f"{local[0]}***@{domain}"
    except Exception:
        return "***@***"


def _get_entry_price(api: IQ_Option, ativo: str, log) -> float | None:
    """Obtém o preço atual (último close) via api.get_candles().
    Usado como preço de entrada logo após api.buy()."""
    try:
        candles = api.get_candles(ativo, 60, 1, time.time())
        if candles and len(candles) > 0:
            return float(candles[-1].get("close", 0))
    except Exception as exc:
        log.warning("[CANDLE] Erro ao obter preço de entrada: %s", exc)
    return None


def _wait_candle_close_and_check(
    api: IQ_Option,
    ativo: str,
    direcao: str,
    entry_price: float,
    order_id: int,
    stake_used: float,
    log,
) -> dict:
    """
    Aguarda o fechamento da vela (candle close) e determina win/loss localmente.
    Se detectar LOSS no candle, retorna instantaneamente.
    Tenta capturar o profit real com check_win_v3 como fallback seguro.
    """
    now = time.time()
    seconds_to_next_minute = 60 - (now % 60)
    sleep_time = max(seconds_to_next_minute - 1, 0)
    
    log.info(
        "[CANDLE] Aguardando %.1fs até candle close | ativo=%s",
        sleep_time, ativo,
    )
    time.sleep(sleep_time)
    time.sleep(2)  # delay para processamento da vela

    close_price = None
    try:
        candles = api.get_candles(ativo, 60, 2, time.time())
        if candles and len(candles) >= 2:
            close_price = float(candles[-2].get("close", 0))
            log.info(
                "[CANDLE] Close detectado: entry=%.6f | close=%.6f",
                entry_price, close_price,
            )
    except Exception as exc:
        log.warning("[CANDLE] Erro ao obter candle de fechamento: %s", exc)

    if close_price is not None and entry_price > 0:
        if direcao == "call":
            won = close_price > entry_price
        else:
            won = close_price < entry_price

        result_label = "WIN" if won else "LOSS"
        log.info("[CANDLE] Resultado por candle: %s", result_label)

        # LOSS → retorno INSTANTÂNEO para disparar Gale imediatamente
        if not won:
            return {"won": False, "profit": -stake_used}

        # WIN → tenta obter profit real via check_win_v3 (timeout curto)
        estimated_profit = 0.0
        try:
            deadline_profit = time.time() + 15
            while time.time() < deadline_profit:
                result = api.check_win_v3(order_id)
                if result is not None:
                    win_amount = float(result.get("win_amount", 0) or 0)
                    loss_amt = float(result.get("profit_amount", 0) or 0)
                    if win_amount == 0 and loss_amt == 0:
                        time.sleep(0.5)
                        continue
                    estimated_profit = win_amount if win_amount > 0 else -loss_amt
                    break
                time.sleep(0.5)
        except Exception:
            pass

        if estimated_profit == 0.0:
            estimated_profit = round(stake_used * 0.82, 2)
        return {"won": True, "profit": estimated_profit}

    # Fallback total caso candle não retorne dados
    log.warning("[CANDLE] Fallback para check_win_v3 (candle indisponível)")
    deadline = time.time() + 90
    while time.time() < deadline:
        try:
            result = api.check_win_v3(order_id)
            if result is not None:
                win_amount = float(result.get("win_amount", 0) or 0)
                loss_amt = float(result.get("profit_amount", 0) or 0)
                if win_amount == 0 and loss_amt == 0:
                    time.sleep(0.5)
                    continue
                won = win_amount > 0
                profit = win_amount if won else -loss_amt
                return {"won": won, "profit": profit}
        except Exception:
            pass
        time.sleep(0.5)

    log.error("[RESULT] Timeout 90s sem resultado — assumindo LOSS por segurança")
    return {"won": False, "profit": -stake_used}


def _wait_for_candle_open(log) -> float:
    """Sincroniza a entrada com a abertura de nova vela de 1 minuto.

    Garante que api.buy() seja chamado dentro dos primeiros 2-3 segundos
    após a abertura da vela, evitando entradas no meio ou fim da vela.

    Retorna: segundos_decorridos desde a abertura da vela atual.
    """
    seconds_in_minute = time.time() % 60

    if seconds_in_minute <= 3.0:
        log.info("[SYNC] Entrando na vela | segundos_desde_abertura=%.1f", seconds_in_minute)
        return seconds_in_minute

    wait_time = (60 - seconds_in_minute) - 0.5
    if wait_time <= 0:
        log.info("[SYNC] Entrando na vela | segundos_desde_abertura=%.1f", seconds_in_minute)
        return seconds_in_minute

    log.info(
        "[SYNC] Aguardando próxima vela | segundos_desde_abertura=%.1f | wait=%.1fs",
        seconds_in_minute, wait_time,
    )
    time.sleep(wait_time)

    seconds_after = time.time() % 60
    log.info("[SYNC] Entrando na vela | segundos_desde_abertura=%.1f", seconds_after)
    return seconds_after


def _execute_order(
    api:         IQ_Option,
    signal:      dict,
    gale_level:  int,
    client_id:   str,
    base_stake:  float,
    estrategia:  str,
    log,
) -> bool:
    """
    Executa uma ordem e determina resultado via candle close.
    Se LOSS → persiste em iq_gale_state para Gale imediato no próximo ciclo.

    Logs:
        [EXEC] Ativo: X | Direcao: Y | Tentativa: G0/G1/G2 | Stake: Z
    """
    sig_id  = signal.get("id")
    ativo   = signal.get("ativo", "EURUSD")
    direcao = signal.get("direcao", "CALL").lower()
    duracao = 1

    stake_used = round(base_stake * GALE_MULTIPLIERS.get(gale_level, 1.0), 2)

    log.info(
        "[EXEC] Ativo: %s | Direcao: %s | Tentativa: G%d | Stake: $%.2f",
        ativo, direcao.upper(), gale_level, stake_used,
    )

    # LOCK ATOMICO: salva 'pending' ANTES do buy para impedir execucao duplicada
    # por dois workers concorrentes. O segundo worker ve 'pending' e aguarda.
    # PATCH preserva created_at (timer de 90s) — FIX do timer reset.
    upsert_gale_state(client_id, str(sig_id), "pending")
    patch_signal(sig_id, {"status": "executing"})

    # Sincroniza com a borda de minuto — entra nos primeiros 2-3s da vela
    _wait_for_candle_open(log)

    try:
        check, order_id = api.buy(stake_used, ativo, direcao, duracao)

        if not check:
            log.error("[EXEC] Ordem REJEITADA | order_id=%s | G%d", order_id, gale_level)
            # Libera o lock atomico — buy nunca foi executado
            delete_gale_state(client_id, str(sig_id))
            patch_signal(sig_id, {"status": "executed", "resultado": "rejected"})
            return False

        log.info("[EXEC] Ordem ACEITA | order_id=%s | G%d", order_id, gale_level)

        # Atualiza pending com order_id real (PATCH — preserva created_at para recovery)
        upsert_gale_state(client_id, str(sig_id), "pending", order_id=order_id, gale_level=gale_level)

        # Captura preço de entrada imediatamente após o buy
        entry_price = _get_entry_price(api, ativo, log)
        if entry_price:
            log.info("[EXEC] Preço de entrada: %.6f", entry_price)
        else:
            log.warning("[EXEC] Preço de entrada indisponível — fallback para polling")

        # ── CANDLE CLOSE: aguarda e determina resultado ──────────────────
        result = _wait_candle_close_and_check(
            api, ativo, direcao, entry_price or 0, order_id, stake_used, log,
        )

        won          = result.get("won", False)
        profit       = result.get("profit", 0)
        status_final = "win" if won else "loss"

        log.info(
            "[EXEC] Resultado G%d: %s | profit=%.2f",
            gale_level, status_final.upper(), profit,
        )

        # Persiste trade result
        insert_trade_result({
            "client_id":     client_id,
            "signal_id":     sig_id,
            "ativo":         ativo,
            "direcao":       direcao.upper(),
            "stake":         stake_used,
            "gale_level":    gale_level,
            "resultado":     status_final,
            "profit":        profit,
            "estrategia_id": estrategia or "",
        })

        if won:
            log.info("[EXEC] ✅ WIN G%d — ciclo encerrado para sinal %s", gale_level, sig_id)
            delete_gale_state(client_id, str(sig_id))
            patch_signal(sig_id, {"status": "executed", "resultado": status_final})
        else:
            if gale_level < GALE_MAX_LEVEL:
                # Gale: persiste loss_gN → próximo ciclo do while detecta e dispara G(N+1) IMEDIATAMENTE
                upsert_gale_state(client_id, str(sig_id), f"loss_g{gale_level}")
                log.info(
                    "[EXEC] 🔁 LOSS G%d — Gale G%d será disparado IMEDIATAMENTE",
                    gale_level, gale_level + 1,
                )
            else:
                log.warning("[EXEC] 🛑 LOSS G%d — Gale ESGOTADO para sinal %s", gale_level, sig_id)
                delete_gale_state(client_id, str(sig_id))
            patch_signal(sig_id, {"status": "executed", "resultado": status_final})

        return True

    except Exception as exc:
        log.error("[EXEC] Exceção G%d: %s", gale_level, exc)
        upsert_gale_state(client_id, str(sig_id), f"loss_g{gale_level}")
        patch_signal(sig_id, {"status": "executed"})
        return False


# ═══════════════════════════════════════════════════════════════════════════════
# PROCESSO PRINCIPAL
# ═══════════════════════════════════════════════════════════════════════════════

def run_client_worker(client: dict) -> None:
    """
    Processo isolado para um único cliente IQ Option.

    Loop principal (state-driven, candle-close):
      1. Checa is_client_running (heartbeat, circuit breaker).
      2. PRIORIDADE 1: Verifica iq_gale_state → executa Gale se pendente.
      3. PRIORIDADE 2: Busca sinais CONFIRMED → executa como G0.
    """
    client_id    = client["client_id"]
    email        = client["iq_email"]
    password     = client["iq_password"]
    balance_type = client.get("balance_type", "PRACTICE")
    estrategia   = client.get("estrategia_ativa") or ""

    log = get_logger(f"WORKER:{client_id}")
    log.info("Worker iniciado | email=%s | balance=%s", _mask_email(email), balance_type)

    # ── 1. Conectar ────────────────────────────────────────────────────────────
    if IQ_PROXY:
        import os
        os.environ["HTTP_PROXY"]  = IQ_PROXY
        os.environ["HTTPS_PROXY"] = IQ_PROXY
        log.info("Usando proxy para IQ Option: %s", IQ_PROXY)

    api = IQ_Option(email, password)

    MAX_CONNECT_ATTEMPTS = 3
    connect_attempts = 0

    while connect_attempts < MAX_CONNECT_ATTEMPTS:
        try:
            connected, reason = api.connect()
        except Exception as e:
            log.error("Exceção no connect (tentativa %d): %s", connect_attempts + 1, e)
            connect_attempts += 1
            if connect_attempts < MAX_CONNECT_ATTEMPTS:
                time.sleep(30 * connect_attempts)
            continue

        if connected:
            log.info("Conectado à IQ Option ✅")
            break
        else:
            log.error("Falha na conexão (tentativa %d): %s", connect_attempts + 1, reason)
            connect_attempts += 1
            if connect_attempts < MAX_CONNECT_ATTEMPTS:
                time.sleep(30 * connect_attempts)

    if connect_attempts >= MAX_CONNECT_ATTEMPTS:
        log.error("❌ Circuit breaker de conexão — desativando cliente no Supabase.")
        try:
            import httpx
            from config import SUPABASE_HFT_URL, SUPABASE_HFT_KEY
            httpx.patch(
                f"{SUPABASE_HFT_URL}/rest/v1/bot_clients?client_id=eq.{client_id}",
                json={"is_running": False},
                headers={
                    "apikey": SUPABASE_HFT_KEY,
                    "Authorization": f"Bearer {SUPABASE_HFT_KEY}",
                    "Content-Type": "application/json",
                },
                timeout=5,
            )
        except Exception as e:
            log.error("Erro ao desligar no Supabase: %s", e)
        return

    api.change_balance(balance_type)
    log.info("Balance definido: %s", balance_type)

    last_heartbeat_ts = time.time()
    executed_signals: set = set()  # idempotência para sinais novos (G0)
    executed_signals_ts: dict = {}  # timestamp de inserção para limpeza
    reconnect_count  = 0
    EXECUTED_TTL_SEC = 600  # limpa sinais executados há mais de 10 min

    # Cache de configuração de risco (TTL curto para refletir stake/stop em poucos segundos)
    _config_cache: dict = {}
    _config_cache_ts: float = 0.0

    # Circuit breaker Supabase
    MAX_SUPABASE_FAILURES = 10
    consecutive_supabase_failures = 0

    # ── 2. Loop principal (State-Driven, Candle-Close) ─────────────────────────
    while True:

        # a) Verifica se cliente ainda está ativo
        try:
            if not is_client_running(client_id):
                log.info("Cliente desativado no Supabase. Encerrando worker.")
                break
            consecutive_supabase_failures = 0
        except Exception as exc:
            consecutive_supabase_failures += 1
            log.warning(
                "Falha ao checar is_client_running (%d/%d): %s",
                consecutive_supabase_failures, MAX_SUPABASE_FAILURES, exc,
            )
            if consecutive_supabase_failures >= MAX_SUPABASE_FAILURES:
                log.error("❌ Circuit breaker Supabase: %d falhas. Encerrando.", MAX_SUPABASE_FAILURES)
                break
            time.sleep(5)
            continue

        # b) Heartbeat periódico
        now = time.time()
        if now - last_heartbeat_ts >= HEARTBEAT_INTERVAL_SEC:
            update_heartbeat(client_id)
            last_heartbeat_ts = now

        # c) Verifica conexão WebSocket
        if not api.check_connect():
            _delay = min(2 ** reconnect_count, 30)
            log.warning("WebSocket desconectado. Aguardando %ds (tentativa %d)...", _delay, reconnect_count + 1)
            time.sleep(_delay)
            reconnect_count += 1
            api.connect()
            continue
        reconnect_count = 0

        # d) Carrega config de risco (TTL curto para evitar stake desatualizado)
        if time.time() - _config_cache_ts > RISK_CONFIG_TTL_SEC:
            _config_cache    = get_session_config(client_id)
            _config_cache_ts = time.time()
        config     = _config_cache
        base_stake = float(config.get("stake", 1.0))
        stop_win   = float(config.get("stop_win", 50.0))
        stop_loss  = float(config.get("stop_loss", 25.0))

        # e) Verifica Stop Win / Stop Loss
        current_pnl = get_session_pnl(client_id)
        if current_pnl >= stop_win:
            log.info("🏆 STOP WIN atingido ($%.2f >= $%.2f) — pausando", current_pnl, stop_win)
            time.sleep(max(POLL_INTERVAL_SEC, 5))
            continue
        if current_pnl <= -stop_loss:
            log.info("🛑 STOP LOSS atingido ($%.2f <= -$%.2f) — pausando", current_pnl, stop_loss)
            time.sleep(max(POLL_INTERVAL_SEC, 5))
            continue

        # ── PRIORIDADE 1: Checar iq_gale_state ────────────────────────────────
        # O Gale é resolvido ANTES de buscar sinais novos.
        # Se o worker crashou e voltou, ele retoma o ciclo aqui.
        gale_entry = get_any_pending_gale(client_id)

        if gale_entry:
            last_result = gale_entry.get("last_result", "")
            sig_id_str  = str(gale_entry.get("signal_id"))

            if last_result == "pending":
                from datetime import datetime, timezone

                order_id_pending  = gale_entry.get("order_id")
                gale_level_pending = int(gale_entry.get("gale_level") or 0)
                created_str       = gale_entry.get("created_at", "")
                elapsed           = 9999.0

                try:
                    if created_str:
                        created_dt = datetime.fromisoformat(created_str.replace("Z", "+00:00"))
                        elapsed = (datetime.now(timezone.utc) - created_dt).total_seconds()
                except Exception as e:
                    log.warning("[RECOVERY] Erro ao calcular elapsed: %s", e)

                if elapsed < 90:
                    log.debug(
                        "[STATE] Ordem em voo para sinal %s (elapsed=%.0fs) — aguardando...",
                        sig_id_str, elapsed,
                    )
                    time.sleep(5)
                    continue

                # elapsed >= 90 — investigar resultado real via check_win_v3
                if order_id_pending:
                    log.warning(
                        "[RECOVERY] pending há %.0fs | order_id=%s — investigando via check_win_v3",
                        elapsed, order_id_pending,
                    )
                    try:
                        result = api.check_win_v3(order_id_pending)
                        if result is not None:
                            win_amount = float(result.get("win_amount", 0) or 0)
                            if win_amount > 0:
                                log.info(
                                    "[RECOVERY] ✅ WIN confirmado via check_win_v3 | sinal %s",
                                    sig_id_str,
                                )
                                delete_gale_state(client_id, sig_id_str)
                                continue
                            else:
                                log.warning(
                                    "[RECOVERY] LOSS confirmado via check_win_v3 | sinal %s → ativando G%d",
                                    sig_id_str, gale_level_pending,
                                )
                                upsert_gale_state(client_id, sig_id_str, f"loss_g{gale_level_pending}")
                                continue
                        else:
                            log.warning(
                                "[RECOVERY] check_win_v3 inconclusivo | sinal %s → assumindo LOSS G%d",
                                sig_id_str, gale_level_pending,
                            )
                            upsert_gale_state(client_id, sig_id_str, f"loss_g{gale_level_pending}")
                            continue
                    except Exception as exc:
                        log.error(
                            "[RECOVERY] Erro em check_win_v3: %s → assumindo LOSS G%d",
                            exc, gale_level_pending,
                        )
                        upsert_gale_state(client_id, sig_id_str, f"loss_g{gale_level_pending}")
                        continue
                else:
                    # Sem order_id — o buy NUNCA foi confirmado (rejected ou falha de rede)
                    # NAO escalar para LOSS — nao houve operacao real na corretora
                    # Limpar state orfao e seguir
                    log.warning(
                        "[RECOVERY] pending sem order_id | sinal %s → buy nao confirmado, limpando (sem Gale)",
                        sig_id_str,
                    )
                    delete_gale_state(client_id, sig_id_str)
                    continue

            elif last_result.startswith("loss_g"):
                try:
                    gale_done = int(last_result.replace("loss_g", ""))
                except ValueError:
                    gale_done = 0

                next_gale = gale_done + 1

                if next_gale > GALE_MAX_LEVEL:
                    log.warning("[STATE] G%d loss — Gale esgotado. Limpando sinal %s.", gale_done, sig_id_str)
                    delete_gale_state(client_id, sig_id_str)
                    time.sleep(1)
                    continue

                log.info(
                    "[STATE] 🔁 Detectado loss_g%d → disparando G%d IMEDIATAMENTE para sinal %s",
                    gale_done, next_gale, sig_id_str,
                )

                signal = get_signal_by_id(sig_id_str)
                if signal is None:
                    log.error("[STATE] Sinal %s não encontrado — limpando Gale.", sig_id_str)
                    delete_gale_state(client_id, sig_id_str)
                    continue

                # 🚀 GALE INSTANTÂNEO — sem sleep intermediário
                _execute_order(api, signal, next_gale, client_id, base_stake, estrategia, log)
                continue  # volta ao topo para checar se tem mais Gale

            else:
                log.warning("[STATE] Estado inesperado '%s' — limpando sinal %s.", last_result, sig_id_str)
                delete_gale_state(client_id, sig_id_str)

        # ── PRIORIDADE 2: Buscar sinais novos CONFIRMED ────────────────────────
        try:
            signals = get_confirmed_signals(client_id, estrategia if estrategia else None)
        except Exception as exc:
            log.error("Erro ao buscar sinais: %s", exc)
            time.sleep(max(POLL_INTERVAL_SEC, 5))
            continue

        # Limpeza periódica de sinais antigos (anti-memory-leak)
        now_ts = time.time()
        stale = [sid for sid, ts in executed_signals_ts.items()
                 if now_ts - ts > EXECUTED_TTL_SEC]
        for sid in stale:
            executed_signals.discard(sid)
            del executed_signals_ts[sid]

        for signal in signals:
            sig_id = signal.get("id")

            if sig_id in executed_signals:
                continue

            # Claim atômico: PATCH condicional só funciona se status=CONFIRMED.
            # Se dois workers concorrerem, apenas UM recebe a linha de volta.
            # Evita execuções duplicadas mesmo em caso de crash+restart ou múltiplos clientes.
            if not claim_signal(sig_id):
                executed_signals.add(sig_id)
                executed_signals_ts[sig_id] = time.time()
                continue

            executed_signals.add(sig_id)
            executed_signals_ts[sig_id] = time.time()
            log.info("[STATE] Novo sinal %s detectado → executando G0", sig_id)
            _execute_order(api, signal, gale_level=0, client_id=client_id,
                           base_stake=base_stake, estrategia=estrategia, log=log)
            break  # 1 ativo por vez

        # Anti-spam APENAS quando não executou nada neste ciclo
        # Se executou ordem (G0 ou Gale), volta imediatamente para checar estado
        time.sleep(1)
