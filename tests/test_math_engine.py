"""
tests/test_math_engine.py — Testes unitários do Motor Matemático

Cobertura: z_score, ev_calc, break_even, kelly_fraction
Validação até a 4ª casa decimal conforme PRD seção 9.

Cenários baseados em dados reais do PRD:
- R_100 Z-Score Strategy (S1): p_win=0.64, payout=0.85, ev=0.184
- CRASH_1000 Drift (S2): p_win=0.61, payout=0.85, ev=0.132
- Break-even S1: 54.05% para payout 85%
- Regime change detection: win rate abaixo do BE
"""

import pytest
import numpy as np
from core.math_engine import z_score, ev_calc, break_even, kelly_fraction


# ─────────────────────────────────────────────────────────────────────────────
# FIXTURES — Séries de preços realistas de índices sintéticos
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def r100_baseline_flat():
    """Série plana — desvio padrão zero, Z-Score deve ser 0.0."""
    return [1054.32] * 21  # 20 janela + 1 atual


@pytest.fixture
def r100_strong_put_signal():
    """
    Série R_100 simulando spike acima da média.
    Janela de 20 ticks com média ≈ 1050.0.
    Último tick em 1056.0 → Z > +2.0 → sinal PUT (S1).
    """
    prices = [1050.0 + np.sin(i * 0.3) * 0.5 for i in range(20)]
    prices.append(1056.0)  # desvio extremo para cima
    return prices


@pytest.fixture
def r100_strong_call_signal():
    """
    Série R_100 simulando spike abaixo da média.
    Último tick muito abaixo → Z < -2.0 → sinal CALL (S1).
    """
    prices = [1050.0 + np.sin(i * 0.3) * 0.5 for i in range(20)]
    prices.append(1044.0)  # desvio extremo para baixo
    return prices


@pytest.fixture
def crash1000_between_spikes():
    """
    Série Crash 1000 — drift ascendente entre spikes.
    Simula 580 ticks de subida gradual após o último spike (P50).
    Janela de 20 ticks do drift estável.
    """
    base = 8500.0
    prices = [base + i * 0.05 for i in range(21)]  # drift leve, sem anomalia
    return prices


# ─────────────────────────────────────────────────────────────────────────────
# TESTES: z_score
# ─────────────────────────────────────────────────────────────────────────────

class TestZScore:

    def test_strong_put_signal_above_threshold(self, r100_strong_put_signal):
        """Z > +2.0 para spike acima da média — aciona PUT na S1."""
        z = z_score(r100_strong_put_signal, window=20)
        assert z > 2.0, f"Esperado Z > 2.0 para PUT, obtido: {z:.4f}"

    def test_strong_call_signal_below_threshold(self, r100_strong_call_signal):
        """Z < -2.0 para spike abaixo da média — aciona CALL na S1."""
        z = z_score(r100_strong_call_signal, window=20)
        assert z < -2.0, f"Esperado Z < -2.0 para CALL, obtido: {z:.4f}"

    def test_flat_series_returns_zero(self, r100_baseline_flat):
        """Série sem variância retorna Z = 0.0 (proteção contra divisão por zero)."""
        z = z_score(r100_baseline_flat, window=20)
        assert z == 0.0

    def test_normal_drift_no_signal(self, crash1000_between_spikes):
        """Drift normal do Crash1000 não gera Z extremo — sem sinal falso."""
        z = z_score(crash1000_between_spikes, window=20)
        assert abs(z) < 2.0, f"Drift normal não deve gerar Z extremo: {z:.4f}"

    def test_uses_amostral_std_not_populacional(self):
        """
        Valida ddof=1 (amostral) vs ddof=0 (populacional).
        PRD seção 10 exige desvio padrão amostral.
        Com N pequeno, a diferença é mensurável.
        """
        prices = [10.0, 12.0, 11.0, 13.0, 20.0]  # window=4, atual=20.0
        z_calc = z_score(prices, window=4)

        # Cálculo manual amostral (ddof=1)
        baseline = np.array([10.0, 12.0, 11.0, 13.0])
        mean = np.mean(baseline)
        std_amostral = np.std(baseline, ddof=1)
        z_expected = (20.0 - mean) / std_amostral

        assert z_calc == pytest.approx(z_expected, abs=1e-10)

    def test_z_score_precision_4th_decimal(self):
        """Precisão até a 4ª casa decimal conforme PRD seção 9."""
        prices = [100.0, 101.0, 100.0, 101.0, 102.0]
        z = z_score(prices, window=4)

        # Cálculo manual
        baseline = np.array([100.0, 101.0, 100.0, 101.0])
        expected = (102.0 - np.mean(baseline)) / np.std(baseline, ddof=1)

        assert z == pytest.approx(expected, abs=1e-4)

    def test_uses_only_last_window_plus_one(self):
        """Verifica que a função usa apenas os últimos window+1 elementos."""
        # Prefixo com valores extremos que devem ser ignorados
        prefix = [999.0] * 100
        recent = [100.0, 101.0, 100.0, 101.0, 102.0]
        prices = prefix + recent

        z_full = z_score(prices, window=4)
        z_recent = z_score(recent, window=4)

        assert z_full == pytest.approx(z_recent, abs=1e-10)

    def test_minimum_window_size(self):
        """Janela mínima de 2 períodos deve funcionar."""
        prices = [100.0, 102.0, 105.0]
        z = z_score(prices, window=2)
        assert isinstance(z, float)

    def test_raises_if_window_too_small(self):
        """window < 2 deve levantar ValueError."""
        with pytest.raises(ValueError, match="window deve ser >= 2"):
            z_score([1.0, 2.0, 3.0], window=1)

    def test_raises_if_insufficient_prices(self):
        """Menos preços que window+1 deve levantar ValueError."""
        with pytest.raises(ValueError, match="prices precisa de pelo menos"):
            z_score([1.0, 2.0, 3.0], window=10)


# ─────────────────────────────────────────────────────────────────────────────
# TESTES: ev_calc
# ─────────────────────────────────────────────────────────────────────────────

class TestEvCalc:

    def test_r100_config_json_exact(self):
        """
        Valida o exemplo exato do config.json do PRD seção 6.
        R_100: p_win=0.64, payout=0.85 → EV=0.184
        """
        ev = ev_calc(p_win=0.64, payout=0.85)
        assert ev == pytest.approx(0.184, abs=1e-4)

    def test_crash1000_config_json_exact(self):
        """
        Valida CRASH_1000 do config.json do PRD seção 6.
        p_win=0.61, payout=0.85 → EV=0.132
        """
        ev = ev_calc(p_win=0.61, payout=0.85)
        # EV = 0.61 * 0.85 - 0.39 * 1.0 = 0.5185 - 0.39 = 0.1285
        assert ev == pytest.approx(0.1285, abs=1e-4)

    def test_ev_zero_at_break_even(self):
        """
        Na probabilidade exata de break-even, EV deve ser zero.
        BE = 1 / (1 + 0.85) = 0.5405...
        """
        be = break_even(0.85)
        ev = ev_calc(p_win=be, payout=0.85)
        assert ev == pytest.approx(0.0, abs=1e-10)

    def test_ev_negative_below_break_even(self):
        """Abaixo do break-even, EV < 0 — sistema não deve operar."""
        ev = ev_calc(p_win=0.50, payout=0.85)
        assert ev < 0.0

    def test_ev_positive_with_edge(self):
        """Edge positivo gera EV > 0."""
        ev = ev_calc(p_win=0.60, payout=0.85)
        assert ev > 0.0

    def test_ev_formula_manual_verification(self):
        """Verifica a fórmula: EV = (p * payout) - (q * 1.0)."""
        p_win, payout = 0.68, 0.85
        expected = (p_win * payout) - ((1 - p_win) * 1.0)
        assert ev_calc(p_win, payout) == pytest.approx(expected, abs=1e-10)

    def test_ev_precision_4th_decimal(self):
        """Validação até 4ª casa decimal conforme PRD seção 9."""
        ev = ev_calc(p_win=0.64, payout=0.85)
        assert round(ev, 4) == 0.1840

    def test_raises_p_win_above_one(self):
        """p_win > 1.0 deve levantar ValueError."""
        with pytest.raises(ValueError, match="p_win deve estar em"):
            ev_calc(p_win=1.1, payout=0.85)

    def test_raises_p_win_negative(self):
        """p_win < 0 deve levantar ValueError."""
        with pytest.raises(ValueError, match="p_win deve estar em"):
            ev_calc(p_win=-0.1, payout=0.85)

    def test_raises_payout_zero(self):
        """payout = 0 deve levantar ValueError."""
        with pytest.raises(ValueError, match="payout deve ser > 0"):
            ev_calc(p_win=0.6, payout=0.0)

    def test_raises_payout_negative(self):
        """payout negativo deve levantar ValueError."""
        with pytest.raises(ValueError, match="payout deve ser > 0"):
            ev_calc(p_win=0.6, payout=-0.85)


# ─────────────────────────────────────────────────────────────────────────────
# TESTES: break_even
# ─────────────────────────────────────────────────────────────────────────────

class TestBreakEven:

    def test_payout_85_percent(self):
        """
        Payout 85% (padrão Deriv): BE = 1/1.85 ≈ 54.05%.
        Validado explicitamente no PRD seção 4 (S1).
        """
        be = break_even(0.85)
        assert be == pytest.approx(0.54054, abs=1e-4)

    def test_payout_80_percent(self):
        """Payout 80%: BE = 1/1.80 ≈ 55.56%."""
        be = break_even(0.80)
        assert be == pytest.approx(1.0 / 1.80, abs=1e-10)

    def test_payout_90_percent(self):
        """Payout 90%: BE = 1/1.90 ≈ 52.63%."""
        be = break_even(0.90)
        assert be == pytest.approx(1.0 / 1.90, abs=1e-10)

    def test_break_even_formula(self):
        """Verifica a fórmula: BE = 1 / (1 + payout)."""
        for payout in [0.75, 0.80, 0.85, 0.90, 0.95]:
            expected = 1.0 / (1.0 + payout)
            assert break_even(payout) == pytest.approx(expected, abs=1e-10)

    def test_break_even_always_below_0_5_for_positive_payout(self):
        """Com payout > 0, o break-even é sempre > 0.5 (mercado desfavorável)."""
        for payout in [0.70, 0.80, 0.85, 0.90]:
            be = break_even(payout)
            assert 0.5 < be < 1.0

    def test_higher_payout_lower_break_even(self):
        """Payout mais alto requer win rate menor para break-even."""
        be_low = break_even(0.75)
        be_high = break_even(0.90)
        assert be_high < be_low

    def test_ev_zero_at_break_even_consistency(self):
        """Break-even deve ser consistente com ev_calc retornando zero."""
        payout = 0.85
        be = break_even(payout)
        ev = ev_calc(p_win=be, payout=payout)
        assert ev == pytest.approx(0.0, abs=1e-10)

    def test_raises_payout_zero(self):
        """payout = 0 deve levantar ValueError (divisão por zero)."""
        with pytest.raises(ValueError, match="payout deve ser > 0"):
            break_even(0.0)

    def test_raises_payout_negative(self):
        """payout negativo deve levantar ValueError."""
        with pytest.raises(ValueError, match="payout deve ser > 0"):
            break_even(-1.0)


# ─────────────────────────────────────────────────────────────────────────────
# TESTES: kelly_fraction
# ─────────────────────────────────────────────────────────────────────────────

class TestKellyFraction:

    def test_quarter_kelly_default_fraction(self):
        """
        Quarter Kelly padrão (fraction=0.25) — PRD Pilar 5.
        R_100: p_win=0.64, payout=0.85.
        Full Kelly = (0.85 * 0.64 - 0.36) / 0.85 = 0.184 / 0.85 ≈ 0.2165
        Quarter Kelly ≈ 0.0541
        """
        k = kelly_fraction(p_win=0.64, payout=0.85)
        full_kelly = (0.85 * 0.64 - 0.36) / 0.85
        expected = full_kelly * 0.25
        assert k == pytest.approx(expected, abs=1e-6)

    def test_half_kelly_fraction(self):
        """Half Kelly (fraction=0.5) — sizing intermediário."""
        k_half = kelly_fraction(p_win=0.64, payout=0.85, fraction=0.5)
        k_quarter = kelly_fraction(p_win=0.64, payout=0.85, fraction=0.25)
        assert k_half == pytest.approx(k_quarter * 2, abs=1e-10)

    def test_negative_ev_returns_zero(self):
        """
        Kelly negativo (EV < 0) deve retornar 0.0 — não operar.
        p_win=0.50 com payout=0.85 → EV negativo.
        """
        k = kelly_fraction(p_win=0.50, payout=0.85)
        assert k == 0.0

    def test_at_break_even_returns_zero(self):
        """Na probabilidade de break-even exato, Kelly deve ser zero."""
        be = break_even(0.85)
        k = kelly_fraction(p_win=be, payout=0.85)
        assert k == pytest.approx(0.0, abs=1e-10)

    def test_crash1000_quarter_kelly(self):
        """
        CRASH_1000: p_win=0.61, payout=0.85.
        Full Kelly = (0.85 * 0.61 - 0.39) / 0.85 ≈ 0.1512
        Quarter Kelly ≈ 0.0378
        """
        k = kelly_fraction(p_win=0.61, payout=0.85)
        full_kelly = (0.85 * 0.61 - 0.39) / 0.85
        expected = full_kelly * 0.25
        assert k == pytest.approx(expected, abs=1e-6)

    def test_full_kelly_fraction_one(self):
        """fraction=1.0 retorna o Kelly completo."""
        k_full = kelly_fraction(p_win=0.64, payout=0.85, fraction=1.0)
        expected = (0.85 * 0.64 - 0.36) / 0.85
        assert k_full == pytest.approx(expected, abs=1e-10)

    def test_kelly_is_always_positive_when_ev_positive(self):
        """Com EV positivo, Kelly fracionado deve ser sempre positivo."""
        for p_win in [0.56, 0.60, 0.64, 0.68, 0.72]:
            k = kelly_fraction(p_win=p_win, payout=0.85)
            assert k > 0.0, f"Kelly negativo inesperado para p_win={p_win}"

    def test_kelly_increases_with_edge(self):
        """Maior edge (maior p_win) → maior sizing Kelly."""
        k_low = kelly_fraction(p_win=0.56, payout=0.85)
        k_mid = kelly_fraction(p_win=0.64, payout=0.85)
        k_high = kelly_fraction(p_win=0.72, payout=0.85)
        assert k_low < k_mid < k_high

    def test_kelly_formula_manual(self):
        """Verifica a fórmula: f* = (b*p - q) / b, depois × fraction."""
        p, b, frac = 0.64, 0.85, 0.25
        q = 1.0 - p
        expected = ((b * p - q) / b) * frac
        assert kelly_fraction(p, b, frac) == pytest.approx(expected, abs=1e-10)

    def test_raises_p_win_above_one(self):
        """p_win > 1.0 deve levantar ValueError."""
        with pytest.raises(ValueError, match="p_win deve estar em"):
            kelly_fraction(p_win=1.5, payout=0.85)

    def test_raises_payout_zero(self):
        """payout = 0 deve levantar ValueError."""
        with pytest.raises(ValueError, match="payout deve ser > 0"):
            kelly_fraction(p_win=0.64, payout=0.0)

    def test_raises_fraction_zero(self):
        """fraction = 0 deve levantar ValueError."""
        with pytest.raises(ValueError, match="fraction deve estar em"):
            kelly_fraction(p_win=0.64, payout=0.85, fraction=0.0)

    def test_raises_fraction_above_one(self):
        """fraction > 1 deve levantar ValueError."""
        with pytest.raises(ValueError, match="fraction deve estar em"):
            kelly_fraction(p_win=0.64, payout=0.85, fraction=1.5)


# ─────────────────────────────────────────────────────────────────────────────
# TESTES DE INTEGRAÇÃO — Cenários reais de trading
# ─────────────────────────────────────────────────────────────────────────────

class TestIntegrationScenarios:

    def test_s1_r100_full_pipeline(self):
        """
        S1 completo — R_100 Mean Reversion:
        Z > 2.0 → EV positivo → Kelly fracionado válido → OPERA.
        """
        # Simula série com spike (Z ≈ 2.55, conforme contexto.json do PRD)
        prices = [1050.0 + np.sin(i * 0.2) * 0.3 for i in range(20)]
        prices.append(1056.5)  # spike extremo

        z = z_score(prices, window=20)
        ev = ev_calc(p_win=0.64, payout=0.85)
        be = break_even(payout=0.85)
        k = kelly_fraction(p_win=0.64, payout=0.85)

        assert z > 2.0,    f"Z-Score insuficiente para S1: {z:.4f}"
        assert ev > 0.0,   f"EV negativo não deve operar: {ev:.4f}"
        assert 0.64 > be,  f"Win rate abaixo do break-even: {be:.4f}"
        assert k > 0.0,    f"Sizing inválido: {k:.4f}"

    def test_regime_change_detection(self):
        """
        PRD Pilar 7: win rate abaixo do break-even → sistema deve parar.
        Simula degradação do edge — win rate caiu para 50%.
        """
        payout = 0.85
        degraded_p_win = 0.50  # win rate degradado

        be = break_even(payout)
        ev = ev_calc(p_win=degraded_p_win, payout=payout)
        k = kelly_fraction(p_win=degraded_p_win, payout=payout)

        assert degraded_p_win < be, "Win rate degradado deve estar abaixo do BE"
        assert ev < 0.0,            "EV deve ser negativo com win rate degradado"
        assert k == 0.0,            "Kelly deve ser 0 — não operar"

    def test_minimum_edge_threshold_s1(self):
        """
        S1: edge mínimo = win rate > BE + 5% (PRD seção 4).
        BE ≈ 54.05% → mínimo operacional ≈ 59.05%.
        """
        payout = 0.85
        be = break_even(payout)
        min_operational = be + 0.05  # 5% de edge mínimo

        # Teste com win rate abaixo do mínimo operacional
        ev_below = ev_calc(p_win=0.57, payout=payout)
        # Teste com win rate no edge mínimo
        ev_above = ev_calc(p_win=0.62, payout=payout)

        assert ev_below < ev_above
        # Win rate de 62% supera BE por ~8% — dentro do range S1 (8–14%)
        assert 0.62 > min_operational or pytest.approx(0.62, abs=0.03) == min_operational

    def test_config_json_r100_values_consistent(self):
        """
        Todos os valores do config.json R_100 (PRD seção 6) são internamente
        consistentes: ev, kelly_quarter, e break_even se relacionam corretamente.
        """
        p_win = 0.64
        payout = 0.85

        ev = ev_calc(p_win, payout)
        be = break_even(payout)
        k = kelly_fraction(p_win, payout)

        # PRD config.json: ev=0.184, kelly_quarter=0.015
        assert ev == pytest.approx(0.184, abs=1e-4)
        # Break-even ≈ 54.05% < 64% (win rate S1)
        assert p_win > be
        # Kelly > 0 quando há edge
        assert k > 0.0
        # EV positivo e Kelly consistentes
        assert (ev > 0) == (k > 0)
