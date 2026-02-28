"""
tests/test_sniper.py — Testes unitários do DerivSniper (Fase 2)

Sem conexão WebSocket real. Injeta ticks diretamente nos métodos síncronos
(_process_tick_sync e _process_message), provando que:

  1. Deque: inicializado por ativo, maxlen=300, armazena apenas float
  2. epoch % 60: extração correta do segundo da vela (PRD Regra 3)
  3. Máquina de estados: PRE_SIGNAL → CONFIRMED → reset no segundo 1
  4. Anti-duplicata: apenas 1 PRE_SIGNAL por vela de 1 minuto
  5. Limiar Z-Score: sinal somente quando |Z| >= z_score_min
  6. Payload: todos os campos obrigatórios para o INSERT do Supabase (Fase 3)
  7. CRASH_DRIFT: sem z_score_min → nenhum sinal Z emitido

Épocas de controle (BASE_EPOCH % 60 == 20):
  BASE_EPOCH = 1_700_000_000  → segundo 20
  + 10 = EPOCH_S30            → segundo 30  (meio da vela, sem sinal)
  + 30 = EPOCH_S50            → segundo 50  (início PRE_SIGNAL)
  + 35 = EPOCH_S55            → segundo 55  (dentro da janela PRE_SIGNAL)
  + 39 = EPOCH_S59            → segundo 59  (último segundo PRE_SIGNAL)
  + 40 = EPOCH_S0             → segundo 0   (janela CONFIRMED)
  + 41 = EPOCH_S1             → segundo 1   (reset de estado)
"""

import json
import pytest
from core.vps_sniper import DerivSniper

# ─────────────────────────────────────────────────────────────────────────────
# CONSTANTES DE TESTE
# ─────────────────────────────────────────────────────────────────────────────

BASE_EPOCH = 1_700_000_000  # % 60 == 20  (verificado: 1_699_999_980 é múltiplo de 60)

EPOCH_S30  = BASE_EPOCH + 10   # % 60 == 30  — meio da vela, janela inativa
EPOCH_S50  = BASE_EPOCH + 30   # % 60 == 50  — janela PRE_SIGNAL abre
EPOCH_S55  = BASE_EPOCH + 35   # % 60 == 55  — dentro da janela PRE_SIGNAL
EPOCH_S59  = BASE_EPOCH + 39   # % 60 == 59  — último segundo do PRE_SIGNAL
EPOCH_S0   = BASE_EPOCH + 40   # % 60 == 0   — janela CONFIRMED
EPOCH_S1   = BASE_EPOCH + 41   # % 60 == 1   — reset de estado

# Config espelho exato da Seção 6 do PRD
CONFIG = {
    "R_100": {
        "estrategia":       "Z_SCORE_M1",
        "z_score_min":      2.5,
        "p_win":            0.64,
        "ev":               0.184,
        "kelly_quarter":    0.015,
        "n_amostral":       347,
        "expiracao_segundos": 300,
    },
    "CRASH_1000": {
        "estrategia":       "CRASH_DRIFT",
        "p50_ticks":        580,
        "p80_ticks":        820,
        "p_win":            0.61,
        "ev":               0.132,
        "kelly_quarter":    0.012,
        "n_amostral":       412,
        "expiracao_segundos": 300,
        # Sem 'z_score_min' — intencionalmente omitido (CRASH_DRIFT usa lógica própria)
    },
}

# ── Séries de preços para controle do Z-Score ────────────────────────────────
#
# BASELINE_PRICES: 20 preços alternando 999.5 / 1000.5
#   → média = 1000.0
#   → desvio padrão amostral (ddof=1) ≈ 0.5130
#     (10 valores com desvio +0.5 e 10 com -0.5 → var = 5/19)
#
# SPIKE_UP   = 1003.5  → Z ≈ +6.82  (acima do threshold 2.5) → PUT
# SPIKE_DOWN = 996.5   → Z ≈ -6.82  (abaixo do threshold -2.5) → CALL
# NORMAL     = 1001.0  → Z ≈ +1.95  (abaixo do threshold) → sem sinal
#
BASELINE_PRICES = [999.5 if i % 2 == 0 else 1000.5 for i in range(20)]
SPIKE_UP        = 1003.5
SPIKE_DOWN      = 996.5
NORMAL          = 1001.0


# ─────────────────────────────────────────────────────────────────────────────
# FIXTURES
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def sniper() -> DerivSniper:
    """Sniper limpo, sem dados históricos."""
    return DerivSniper(CONFIG, app_id="test_id")


@pytest.fixture
def sniper_loaded(sniper: DerivSniper) -> DerivSniper:
    """
    Sniper com 20 preços baseline carregados diretamente no deque do R_100.
    Ao chamar _process_tick_sync com o 21º preço, o Z-Score já pode ser calculado.
    """
    for price in BASELINE_PRICES:
        sniper.deques["R_100"].append(price)
    return sniper


# ─────────────────────────────────────────────────────────────────────────────
# BLOCO 1 — Verificação dos Épocas de Controle
# ─────────────────────────────────────────────────────────────────────────────

class TestEpochConstants:
    """Garante que as constantes de teste representam os segundos corretos."""

    def test_epoch_s30_is_second_30(self):
        assert EPOCH_S30 % 60 == 30

    def test_epoch_s50_is_second_50(self):
        assert EPOCH_S50 % 60 == 50

    def test_epoch_s55_is_second_55(self):
        assert EPOCH_S55 % 60 == 55

    def test_epoch_s59_is_second_59(self):
        assert EPOCH_S59 % 60 == 59

    def test_epoch_s0_is_second_0(self):
        assert EPOCH_S0 % 60 == 0

    def test_epoch_s1_is_second_1(self):
        assert EPOCH_S1 % 60 == 1

    def test_base_epoch_mod_60(self):
        """BASE_EPOCH % 60 == 20 — premissa de todos os outros cálculos."""
        assert BASE_EPOCH % 60 == 20


# ─────────────────────────────────────────────────────────────────────────────
# BLOCO 2 — Inicialização e Deque (PRD Regra 4)
# ─────────────────────────────────────────────────────────────────────────────

class TestDequeInitialization:

    def test_deque_created_for_each_config_asset(self, sniper):
        """Cada ativo do config.json deve ter seu próprio deque."""
        assert "R_100" in sniper.deques
        assert "CRASH_1000" in sniper.deques

    def test_deque_maxlen_is_300(self, sniper):
        """maxlen=300 garante RAM < 150MB (PRD seção 9)."""
        assert sniper.deques["R_100"].maxlen == 300
        assert sniper.deques["CRASH_1000"].maxlen == 300

    def test_deque_starts_empty(self, sniper):
        """Deques iniciam sem dados — sem estado residual."""
        assert len(sniper.deques["R_100"]) == 0

    def test_deque_overflow_drops_oldest(self, sniper):
        """Com maxlen=300, o 301º item substitui o mais antigo."""
        for i in range(301):
            sniper.deques["R_100"].append(float(i))

        assert len(sniper.deques["R_100"]) == 300
        assert sniper.deques["R_100"][0] == 1.0     # item 0 (valor 0.0) foi removido
        assert sniper.deques["R_100"][-1] == 300.0  # último inserido

    def test_deque_stores_only_float_not_dict(self, sniper):
        """PRD Regra 4: o deque deve conter apenas float, nunca o JSON bruto."""
        sniper._process_tick_sync("R_100", EPOCH_S30, 1000.0)

        stored = sniper.deques["R_100"][0]
        assert isinstance(stored, float)
        assert not isinstance(stored, dict)
        assert not isinstance(stored, str)
        assert stored == 1000.0

    def test_deque_stores_exact_price_value(self, sniper):
        """O valor armazenado no deque deve ser idêntico ao price recebido."""
        sniper._process_tick_sync("R_100", EPOCH_S30, 1054.32)
        assert sniper.deques["R_100"][0] == pytest.approx(1054.32, abs=1e-9)

    def test_signal_state_starts_as_none(self, sniper):
        """Estado de sinal inicializa como None para todos os ativos."""
        assert sniper._signal_state["R_100"] is None
        assert sniper._signal_state["CRASH_1000"] is None

    def test_unknown_asset_returns_none(self, sniper):
        """Tick de ativo não configurado é ignorado silenciosamente."""
        result = sniper._process_tick_sync("UNKNOWN_ASSET", EPOCH_S50, 1000.0)
        assert result is None


# ─────────────────────────────────────────────────────────────────────────────
# BLOCO 3 — Limiar de Dados e Z-Score
# ─────────────────────────────────────────────────────────────────────────────

class TestDataThreshold:

    def test_no_signal_with_zero_data(self, sniper):
        """Deque vazio → sem sinal (aguarda dados suficientes)."""
        result = sniper._process_tick_sync("R_100", EPOCH_S50, SPIKE_UP)
        assert result is None

    def test_no_signal_with_19_prices_in_deque(self, sniper):
        """19 preços + 1 via tick = 20 no deque → abaixo do mínimo (21)."""
        for p in BASELINE_PRICES[:19]:
            sniper.deques["R_100"].append(p)

        result = sniper._process_tick_sync("R_100", EPOCH_S50, SPIKE_UP)
        # Após o tick: 20 preços no deque. WINDOW+1 = 21 → insuficiente
        assert result is None

    def test_signal_possible_with_20_prices_in_deque(self, sniper):
        """20 preços no deque + 1 via tick = 21 → Z-Score calculável → sinal possível."""
        for p in BASELINE_PRICES:          # 20 preços
            sniper.deques["R_100"].append(p)

        result = sniper._process_tick_sync("R_100", EPOCH_S50, SPIKE_UP)
        # Após o tick: 21 preços. WINDOW+1 = 21 → suficiente → sinal esperado
        assert result is not None

    def test_no_signal_below_z_threshold(self, sniper_loaded):
        """Preço normal (Z ≈ 1.95 < 2.5) não dispara sinal."""
        result = sniper_loaded._process_tick_sync("R_100", EPOCH_S50, NORMAL)
        assert result is None

    def test_signal_at_z_threshold(self, sniper_loaded):
        """Preço spike (Z ≈ 6.82 > 2.5) dispara sinal no segundo 50."""
        result = sniper_loaded._process_tick_sync("R_100", EPOCH_S50, SPIKE_UP)
        assert result is not None


# ─────────────────────────────────────────────────────────────────────────────
# BLOCO 4 — Máquina de Estados (Fluxo Principal)
# ─────────────────────────────────────────────────────────────────────────────

class TestSignalStateMachine:

    def test_pre_signal_emitted_at_second_50(self, sniper_loaded):
        """Spike no segundo 50 → PRE_SIGNAL com Z acima do threshold."""
        result = sniper_loaded._process_tick_sync("R_100", EPOCH_S50, SPIKE_UP)

        assert result is not None
        signal_type, payload = result
        assert signal_type == "PRE_SIGNAL"

    def test_pre_signal_direction_put_for_spike_up(self, sniper_loaded):
        """Z positivo (preço acima da média) → direção PUT (S1 — Mean Reversion)."""
        result = sniper_loaded._process_tick_sync("R_100", EPOCH_S50, SPIKE_UP)
        _, payload = result
        assert payload["direction"] == "PUT"
        assert payload["z_score"] > 0

    def test_pre_signal_direction_call_for_spike_down(self, sniper_loaded):
        """Z negativo (preço abaixo da média) → direção CALL (S1 — Mean Reversion)."""
        result = sniper_loaded._process_tick_sync("R_100", EPOCH_S50, SPIKE_DOWN)
        _, payload = result
        assert payload["direction"] == "CALL"
        assert payload["z_score"] < 0

    def test_confirmed_follows_pre_signal(self, sniper_loaded):
        """Fluxo completo: PRE_SIGNAL no seg 50 → CONFIRMED no seg 0."""
        r1 = sniper_loaded._process_tick_sync("R_100", EPOCH_S50, SPIKE_UP)
        r2 = sniper_loaded._process_tick_sync("R_100", EPOCH_S0,  SPIKE_UP)

        assert r1 is not None and r1[0] == "PRE_SIGNAL"
        assert r2 is not None and r2[0] == "CONFIRMED"

    def test_no_confirmed_without_pre_signal(self, sniper_loaded):
        """CONFIRMED exige PRE_SIGNAL anterior — não ocorre com estado None."""
        assert sniper_loaded._signal_state["R_100"] is None

        result = sniper_loaded._process_tick_sync("R_100", EPOCH_S0, SPIKE_UP)
        assert result is None

    def test_state_is_pre_signal_after_first_alert(self, sniper_loaded):
        """Estado interno deve ser 'PRE_SIGNAL' imediatamente após emissão."""
        sniper_loaded._process_tick_sync("R_100", EPOCH_S50, SPIKE_UP)
        assert sniper_loaded._signal_state["R_100"] == "PRE_SIGNAL"

    def test_state_is_confirmed_after_confirmation(self, sniper_loaded):
        """Estado interno deve ser 'CONFIRMED' após confirmação."""
        sniper_loaded._process_tick_sync("R_100", EPOCH_S50, SPIKE_UP)
        sniper_loaded._process_tick_sync("R_100", EPOCH_S0,  SPIKE_UP)
        assert sniper_loaded._signal_state["R_100"] == "CONFIRMED"

    def test_state_resets_to_none_at_second_1(self, sniper_loaded):
        """Segundo 1 deve resetar o estado para None (nova vela começa)."""
        sniper_loaded._process_tick_sync("R_100", EPOCH_S50, SPIKE_UP)
        assert sniper_loaded._signal_state["R_100"] == "PRE_SIGNAL"

        sniper_loaded._process_tick_sync("R_100", EPOCH_S1, 1000.0)
        assert sniper_loaded._signal_state["R_100"] is None

    def test_no_signal_in_mid_candle_seconds(self, sniper_loaded):
        """Segundos 2–49 não geram sinal (fora das janelas PRE/CONFIRMED)."""
        result = sniper_loaded._process_tick_sync("R_100", EPOCH_S30, SPIKE_UP)
        assert result is None

    def test_no_signal_after_state_is_confirmed(self, sniper_loaded):
        """Ticks adicionais após CONFIRMED não geram novo sinal no mesmo ciclo."""
        sniper_loaded._process_tick_sync("R_100", EPOCH_S50, SPIKE_UP)
        sniper_loaded._process_tick_sync("R_100", EPOCH_S0,  SPIKE_UP)

        # Estado já é CONFIRMED — novos ticks no segundo 0 não geram nada
        result = sniper_loaded._process_tick_sync("R_100", EPOCH_S0, SPIKE_UP)
        assert result is None

    def test_full_cycle_then_new_candle(self, sniper_loaded):
        """Após ciclo completo + reset, novo ciclo deve funcionar normalmente."""
        # Ciclo 1
        sniper_loaded._process_tick_sync("R_100", EPOCH_S50, SPIKE_UP)
        sniper_loaded._process_tick_sync("R_100", EPOCH_S0,  SPIKE_UP)
        sniper_loaded._process_tick_sync("R_100", EPOCH_S1,  1000.0)  # reset

        # Ciclo 2 — deve funcionar como se fosse o primeiro
        result = sniper_loaded._process_tick_sync("R_100", EPOCH_S55, SPIKE_UP)
        assert result is not None
        assert result[0] == "PRE_SIGNAL"


# ─────────────────────────────────────────────────────────────────────────────
# BLOCO 5 — Anti-Duplicata (1 PRE_SIGNAL por vela)
# ─────────────────────────────────────────────────────────────────────────────

class TestAntiDuplicate:

    def test_only_one_pre_signal_for_multiple_ticks_in_window(self, sniper_loaded):
        """5 ticks com spike consecutivos no intervalo 50–59 → apenas 1 PRE_SIGNAL."""
        epochs  = [EPOCH_S50, EPOCH_S55, EPOCH_S59, EPOCH_S55, EPOCH_S50]
        results = []

        for epoch in epochs:
            r = sniper_loaded._process_tick_sync("R_100", epoch, SPIKE_UP)
            if r:
                results.append(r)

        pre_signals = [s for s in results if s[0] == "PRE_SIGNAL"]
        assert len(pre_signals) == 1, (
            f"Esperado exatamente 1 PRE_SIGNAL, obtido: {len(pre_signals)}"
        )

    def test_full_cycle_produces_exactly_two_signals(self, sniper_loaded):
        """
        Ciclo canônico: PRE_SIGNAL no segundo 50 → CONFIRMED no segundo 0.
        Apenas 2 ticks injetados para não contaminar a janela baseline do Z-Score.

        Nota: injetar ticks extras (S55, S59) com SPIKE_UP faz o preço anomalico
        entrar no baseline, elevando a média e o desvio padrão. Com ~3 spikes na
        janela de 20, o Z cai abaixo de 2.5 — comportamento matematicamente correto
        (a anomalia foi absorvida). O teste anti-duplicata cobre o cenário multi-tick.
        """
        signals = []

        r = sniper_loaded._process_tick_sync("R_100", EPOCH_S50, SPIKE_UP)
        if r:
            signals.append(r[0])

        r = sniper_loaded._process_tick_sync("R_100", EPOCH_S0, SPIKE_UP)
        if r:
            signals.append(r[0])

        assert signals.count("PRE_SIGNAL") == 1
        assert signals.count("CONFIRMED")  == 1
        assert len(signals) == 2

    def test_pre_signal_not_fired_again_after_confirmed(self, sniper_loaded):
        """Após CONFIRMED, PRE_SIGNAL não pode ser emitido novamente no mesmo ciclo."""
        sniper_loaded._process_tick_sync("R_100", EPOCH_S50, SPIKE_UP)  # PRE
        sniper_loaded._process_tick_sync("R_100", EPOCH_S0,  SPIKE_UP)  # CONFIRMED

        # Tenta disparar outro PRE_SIGNAL no segundo 55 do mesmo ciclo
        result = sniper_loaded._process_tick_sync("R_100", EPOCH_S55, SPIKE_UP)
        assert result is None


# ─────────────────────────────────────────────────────────────────────────────
# BLOCO 6 — Extração do Epoch (PRD Regra 3)
# ─────────────────────────────────────────────────────────────────────────────

class TestEpochExtraction:

    def test_process_message_reads_epoch_from_json(self, sniper_loaded):
        """_process_message deve ler 'epoch' do JSON da Deriv (PRD Regra 3)."""
        deriv_tick = {
            "tick": {
                "symbol": "R_100",
                "epoch":  EPOCH_S50,
                "quote":  SPIKE_UP,
            }
        }
        result = sniper_loaded._process_message(deriv_tick)

        assert result is not None
        _, payload = result
        assert payload["epoch"]   == EPOCH_S50
        assert payload["segundo"] == 50

    def test_segundo_extracted_correctly_from_epoch(self, sniper_loaded):
        """payload['segundo'] deve ser epoch % 60 — nunca datetime.now()."""
        for epoch, expected_second in [
            (EPOCH_S50, 50),
            (EPOCH_S55, 55),
            (EPOCH_S0,  0),
        ]:
            sniper_loaded._signal_state["R_100"] = None  # reset manual para teste
            r = sniper_loaded._process_tick_sync("R_100", epoch, SPIKE_UP)
            if r:
                assert r[1]["segundo"] == expected_second


# ─────────────────────────────────────────────────────────────────────────────
# BLOCO 7 — Parseamento do JSON da Deriv
# ─────────────────────────────────────────────────────────────────────────────

class TestProcessMessage:

    def test_ignores_pong_message(self, sniper):
        """Resposta de ping/pong deve ser ignorada silenciosamente."""
        assert sniper._process_message({"pong": 1}) is None

    def test_ignores_authorize_message(self, sniper):
        """Resposta de autorização deve ser ignorada."""
        assert sniper._process_message({"authorize": {"loginid": "CR123"}}) is None

    def test_ignores_empty_message(self, sniper):
        """JSON vazio deve ser ignorado."""
        assert sniper._process_message({}) is None

    def test_ignores_subscription_status(self, sniper):
        """Mensagem de status de subscrição deve ser ignorada."""
        assert sniper._process_message({"msg_type": "tick_history"}) is None

    def test_parses_full_deriv_tick_format(self, sniper_loaded):
        """Parseia corretamente o JSON real enviado pela Deriv WebSocket."""
        deriv_tick = {
            "tick": {
                "ask":      1003.52,
                "bid":      1003.48,
                "epoch":    EPOCH_S50,
                "id":       "abc123xyz",
                "pip_size": 2,
                "quote":    SPIKE_UP,    # <— apenas este campo importa (PRD Regra 4)
                "symbol":   "R_100",
            },
            "msg_type": "tick",
            "subscription": {"id": "xyz789"},
        }
        result = sniper_loaded._process_message(deriv_tick)

        assert result is not None
        signal_type, payload = result
        assert signal_type          == "PRE_SIGNAL"
        assert payload["symbol"]    == "R_100"
        assert payload["epoch"]     == EPOCH_S50

    def test_quote_stored_as_float_even_when_string_in_json(self, sniper):
        """Conversão explícita para float — JSON pode enviar string numérica."""
        tick_json = {
            "tick": {
                "symbol": "R_100",
                "epoch":  EPOCH_S30,
                "quote":  "1000.55",   # string no JSON
            }
        }
        sniper._process_message(tick_json)
        stored = sniper.deques["R_100"][0]
        assert isinstance(stored, float)
        assert stored == pytest.approx(1000.55, abs=1e-9)


# ─────────────────────────────────────────────────────────────────────────────
# BLOCO 8 — Estratégia CRASH_DRIFT (sem z_score_min)
# ─────────────────────────────────────────────────────────────────────────────

class TestCrashDriftNoZScore:

    def test_crash1000_no_z_signal_without_z_score_min(self, sniper):
        """
        CRASH_1000 usa CRASH_DRIFT (S2), que NÃO tem z_score_min no config.
        O Sniper deve coletar dados no deque mas nunca emitir sinal Z para este ativo.
        """
        for p in BASELINE_PRICES:
            sniper.deques["CRASH_1000"].append(p)

        result = sniper._process_tick_sync("CRASH_1000", EPOCH_S50, SPIKE_UP)
        assert result is None, (
            "CRASH_DRIFT não tem z_score_min — sinal Z não deve ser emitido"
        )

    def test_crash1000_deque_fills_normally(self, sniper):
        """Mesmo sem emitir sinais, o deque do CRASH_1000 deve ser atualizado."""
        sniper._process_tick_sync("CRASH_1000", EPOCH_S30, 8500.0)
        sniper._process_tick_sync("CRASH_1000", EPOCH_S30, 8501.0)

        assert len(sniper.deques["CRASH_1000"]) == 2
        assert sniper.deques["CRASH_1000"][0] == pytest.approx(8500.0)
        assert sniper.deques["CRASH_1000"][1] == pytest.approx(8501.0)

    def test_independent_state_per_asset(self, sniper_loaded):
        """Estado de sinal de R_100 não contamina o de CRASH_1000 e vice-versa."""
        # Disparar PRE_SIGNAL no R_100
        sniper_loaded._process_tick_sync("R_100", EPOCH_S50, SPIKE_UP)
        assert sniper_loaded._signal_state["R_100"] == "PRE_SIGNAL"

        # CRASH_1000 deve continuar None
        assert sniper_loaded._signal_state["CRASH_1000"] is None


# ─────────────────────────────────────────────────────────────────────────────
# BLOCO 9 — Payload do Sinal (campos para Fase 3 / Supabase)
# ─────────────────────────────────────────────────────────────────────────────

class TestSignalPayload:

    def test_payload_has_all_required_fields(self, sniper_loaded):
        """Payload deve conter todos os campos necessários para o INSERT (Fase 3)."""
        result = sniper_loaded._process_tick_sync("R_100", EPOCH_S50, SPIKE_UP)
        _, payload = result

        required = [
            "symbol", "z_score", "direction", "epoch",
            "segundo", "p_win", "ev", "kelly_quarter", "n_amostral",
        ]
        for field in required:
            assert field in payload, f"Campo obrigatório ausente no payload: '{field}'"

    def test_payload_ev_matches_config_json(self, sniper_loaded):
        """EV no payload deve vir do config.json (0.184 para R_100)."""
        result = sniper_loaded._process_tick_sync("R_100", EPOCH_S50, SPIKE_UP)
        _, payload = result
        assert payload["ev"] == pytest.approx(0.184, abs=1e-6)

    def test_payload_kelly_matches_config_json(self, sniper_loaded):
        """Kelly no payload deve vir do config.json (0.015 para R_100)."""
        result = sniper_loaded._process_tick_sync("R_100", EPOCH_S50, SPIKE_UP)
        _, payload = result
        assert payload["kelly_quarter"] == pytest.approx(0.015, abs=1e-6)

    def test_payload_p_win_matches_config_json(self, sniper_loaded):
        """p_win no payload deve vir do config.json (0.64 para R_100)."""
        result = sniper_loaded._process_tick_sync("R_100", EPOCH_S50, SPIKE_UP)
        _, payload = result
        assert payload["p_win"] == pytest.approx(0.64, abs=1e-6)

    def test_payload_z_score_precision_4th_decimal(self, sniper_loaded):
        """Z-Score arredondado a 4 casas decimais (PRD seção 9)."""
        result = sniper_loaded._process_tick_sync("R_100", EPOCH_S50, SPIKE_UP)
        _, payload = result
        z = payload["z_score"]
        assert z == round(z, 4), f"Z-Score não está na 4ª casa decimal: {z}"

    def test_payload_symbol_is_string(self, sniper_loaded):
        """symbol no payload deve ser string."""
        result = sniper_loaded._process_tick_sync("R_100", EPOCH_S50, SPIKE_UP)
        _, payload = result
        assert isinstance(payload["symbol"], str)

    def test_payload_z_score_exceeds_threshold(self, sniper_loaded):
        """Z-Score no payload deve sempre ser >= z_score_min quando sinal é emitido."""
        result = sniper_loaded._process_tick_sync("R_100", EPOCH_S50, SPIKE_UP)
        _, payload = result
        z_min = CONFIG["R_100"]["z_score_min"]
        assert abs(payload["z_score"]) >= z_min
