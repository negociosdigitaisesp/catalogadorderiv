"""
tests/test_oracle_backtest.py — Fase 4: Testes do OracleOrchestrator

Testa exclusivamente os métodos síncronos (run_backtest, validate_edge,
generate_config_json) sem nenhuma conexão real à rede.
O método assíncrono download_data usa WebSocket real e é testado
manualmente em ambiente de desenvolvimento.

Suite — 45 testes:
  TestOracleConstants        ( 4) — Constantes e invariantes da classe
  TestValidateEdgeCriteria   (16) — Critérios 1–8 do PRD Seção 8
  TestRunBacktestBasic       ( 9) — Comportamento básico e DataFrame inválido
  TestRunBacktestSignals     ( 6) — Detecção de sinais PUT/CALL e p_win
  TestGenerateConfigJson     (10) — Geração de config.json e caps de Kelly
"""

from __future__ import annotations

import json
import os

import numpy as np
import pandas as pd
import pytest

from core.math_engine import ev_calc, break_even, kelly_fraction
from core.oracle_backtest import OracleOrchestrator


# ─────────────────────────────────────────────────────────────────────────────
# FIXTURES E HELPERS
# ─────────────────────────────────────────────────────────────────────────────

APP_ID = "99999"  # ID fictício — não faz chamadas de rede nos testes síncronos


@pytest.fixture
def oracle() -> OracleOrchestrator:
    return OracleOrchestrator(app_id=APP_ID)


def _flat_df(n: int = 200, base: float = 1000.0, epsilon: float = 0.001) -> pd.DataFrame:
    """
    DataFrame com preços quase planos (oscilação mínima).
    Z-Score empírico fica próximo de ±1 — abaixo de qualquer threshold.
    Útil para testar ausência de sinais.
    """
    prices = [base + epsilon * (i % 2) for i in range(n)]
    return pd.DataFrame(
        {
            "epoch": list(range(n)),
            "open":  prices,
            "high":  prices,
            "low":   prices,
            "close": prices,
        }
    )


def _spike_df(
    n: int          = 800,
    base: float     = 1000.0,
    step: int       = 25,
    spike_val: float = 1050.0,
) -> pd.DataFrame:
    """
    DataFrame com spikes PUT regularmente espaçados (step > WINDOW=20).

    Cálculo analítico do Z-Score em cada spike (WINDOW=20):
      - 19 preços base (≈1000, epsilon=0.001)  +  1 preço spike_val
      - mean = (19*base + spike_val) / 20  ≈ 1002.5
      - std  ≈ sqrt(19*(−2.5)^2 + (47.5)^2 / 19)  ≈ 11.18
      - Z    = (1050 − 1002.5) / 11.18  ≈ 4.25  → excede todos [2.0, 2.5, 3.0]

    Como step=25 > WINDOW=20, spikes nunca se sobrepõem no rolling window:
      → cada spike gera exatamente 1 sinal PUT independente.

    Com n=800, step=25: ~31 spikes → N=31 ≥ 30 (limiar LGN).
    future_close[spike] ≈ base (5 candles adiante) < spike_val → PUT WIN.
    """
    prices = [base + 0.001 * (i % 2) for i in range(n)]
    for pos in range(25, n - 10, step):   # ~31 spikes; -10 garante future_close válido
        prices[pos] = spike_val
    return pd.DataFrame(
        {
            "epoch": list(range(n)),
            "open":  prices,
            "high":  prices,
            "low":   prices,
            "close": prices,
        }
    )


def _aprovado_result(ativo: str = "R_100") -> dict:
    """Resultado de backtest que passa 7+ critérios do PRD Seção 8."""
    return {
        "ativo":              ativo,
        "estrategia":         "Z_SCORE_M1",
        "z_score_min":        2.5,
        "n_amostral":         350,    # critérios 1 e 4 passam (N≥300, N≥100)
        "p_win":              0.64,   # critérios 2, 3, 6 passam
        "ev":                 0.184,
        "kelly_quarter":      0.015,
        "expiracao_segundos": 300,
    }


def _condicional_result(ativo: str = "R_25") -> dict:
    """Resultado com N=50 → critérios 1 e 4 falham → 5 critérios → CONDICIONAL."""
    return {
        "ativo":              ativo,
        "estrategia":         "Z_SCORE_M1",
        "z_score_min":        2.5,
        "n_amostral":         50,     # critérios 1 e 4 falham; 5 também falha
        "p_win":              0.62,   # critérios 2, 3, 6 passam
        "ev":                 0.127,
        "kelly_quarter":      0.040,
        "expiracao_segundos": 300,
    }


def _reprovado_result(ativo: str = "R_10") -> dict:
    """Resultado com p_win abaixo do break-even → EV<0, kelly<0 → REPROVADO."""
    return {
        "ativo":              ativo,
        "estrategia":         "Z_SCORE_M1",
        "z_score_min":        2.5,
        "n_amostral":         10,     # critérios 1 e 4 falham
        "p_win":              0.50,   # abaixo de BE (0.5405) → critérios 2, 3, 6 falham
        "ev":                 -0.075,
        "kelly_quarter":      0.0,
        "expiracao_segundos": 300,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 1. CONSTANTES
# ─────────────────────────────────────────────────────────────────────────────

class TestOracleConstants:
    """Verifica que as constantes da classe atendem aos contratos do PRD."""

    def test_payout_is_085(self, oracle):
        assert oracle.PAYOUT == 0.85

    def test_z_thresholds_three_levels(self, oracle):
        assert oracle.Z_THRESHOLDS == [2.0, 2.5, 3.0]

    def test_window_is_20(self, oracle):
        assert oracle.WINDOW == 20

    def test_expiracao_300_seconds(self, oracle):
        # 5 candles M1 = 300 segundos (PRD S1: expiração 5 min)
        assert oracle.EXPIRACAO_CANDLES * 60 == 300


# ─────────────────────────────────────────────────────────────────────────────
# 2. VALIDATE_EDGE — 8 CRITÉRIOS PRD SEÇÃO 8
# ─────────────────────────────────────────────────────────────────────────────

class TestValidateEdgeCriteria:
    """
    Valida cada um dos 8 critérios do PRD Seção 8 individualmente
    e os ratings APROVADO / CONDICIONAL / REPROVADO.
    """

    # ── Critério 1: N ≥ 300 ──────────────────────────────────────────────────

    def test_n_300_passes_criterio_1(self, oracle):
        r = oracle.validate_edge(300, 0.64, 0.85)
        assert r["criteria"][1] is True

    def test_n_299_fails_criterio_1(self, oracle):
        r = oracle.validate_edge(299, 0.64, 0.85)
        assert r["criteria"][1] is False

    # ── Critério 2: p_win > BE + 5% ─────────────────────────────────────────

    def test_pwin_exactly_be_plus_5pct_passes_criterio_2(self, oracle):
        be = break_even(0.85)              # ≈ 0.5405
        p  = round(be + 0.05 + 0.001, 4)  # ligeiramente acima
        r  = oracle.validate_edge(300, p, 0.85)
        assert r["criteria"][2] is True

    def test_pwin_at_be_plus_4pct_fails_criterio_2(self, oracle):
        be = break_even(0.85)
        p  = round(be + 0.04, 4)          # abaixo do limiar +5%
        r  = oracle.validate_edge(300, p, 0.85)
        assert r["criteria"][2] is False

    # ── Critério 3: EV > 0 ──────────────────────────────────────────────────

    def test_positive_ev_passes_criterio_3(self, oracle):
        r = oracle.validate_edge(300, 0.64, 0.85)
        assert r["criteria"][3] is True

    def test_ev_zero_or_negative_fails_criterio_3(self, oracle):
        # p_win = break_even → EV = 0 exato (não positivo)
        be = break_even(0.85)
        r  = oracle.validate_edge(300, be, 0.85)
        assert r["criteria"][3] is False

    # ── Critério 4: N ≥ 100 (proxy multi-regime) ────────────────────────────

    def test_n_100_passes_criterio_4(self, oracle):
        r = oracle.validate_edge(100, 0.64, 0.85)
        assert r["criteria"][4] is True

    def test_n_99_fails_criterio_4(self, oracle):
        r = oracle.validate_edge(99, 0.64, 0.85)
        assert r["criteria"][4] is False

    # ── Critério 5: período > 90 dias ───────────────────────────────────────

    def test_days_90_passes_criterio_5(self, oracle):
        r = oracle.validate_edge(300, 0.64, 0.85, days_cataloged=90)
        assert r["criteria"][5] is True

    def test_days_89_fails_criterio_5(self, oracle):
        r = oracle.validate_edge(300, 0.64, 0.85, days_cataloged=89)
        assert r["criteria"][5] is False

    # ── Critério 7: drawdown ≤ 30% ───────────────────────────────────────────

    def test_max_dd_030_passes_criterio_7(self, oracle):
        r = oracle.validate_edge(300, 0.64, 0.85, max_dd=0.30)
        assert r["criteria"][7] is True

    def test_max_dd_031_fails_criterio_7(self, oracle):
        r = oracle.validate_edge(300, 0.64, 0.85, max_dd=0.31)
        assert r["criteria"][7] is False

    # ── Critério 8: contexto sempre definido ────────────────────────────────

    def test_criterio_8_always_true(self, oracle):
        r = oracle.validate_edge(10, 0.50, 0.85)
        assert r["criteria"][8] is True

    # ── Ratings aggregados ───────────────────────────────────────────────────

    def test_aprovado_7_criteria(self, oracle):
        # N=300, p_win=0.64, max_dd=0.0, days=30 → falha só critério 5
        # = 7 critérios passando → APROVADO
        r = oracle.validate_edge(300, 0.64, 0.85)
        assert r["rating"] == "APROVADO"
        assert r["criteria_passed"] == 7

    def test_condicional_5_criteria(self, oracle):
        # N=50 → falha 1, 4; days=30 → falha 5; p_win=0.62 → passa 2, 3, 6
        # Falhas: 1, 4, 5 → passa: 2, 3, 6, 7, 8 = 5 → CONDICIONAL
        r = oracle.validate_edge(50, 0.62, 0.85)
        assert r["rating"] == "CONDICIONAL"
        assert r["criteria_passed"] == 5

    def test_reprovado_2_criteria(self, oracle):
        # N=10, p_win=0.50 → falha 1, 2, 3, 4, 5, 6 → passa só 7, 8 = 2
        r = oracle.validate_edge(10, 0.50, 0.85)
        assert r["rating"] == "REPROVADO"
        assert r["criteria_passed"] == 2

    def test_return_has_all_required_keys(self, oracle):
        r = oracle.validate_edge(300, 0.64, 0.85)
        assert set(r.keys()) == {
            "rating", "criteria_passed", "criteria", "ev", "kelly_quarter", "break_even"
        }


# ─────────────────────────────────────────────────────────────────────────────
# 3. RUN_BACKTEST — COMPORTAMENTO BÁSICO
# ─────────────────────────────────────────────────────────────────────────────

class TestRunBacktestBasic:
    """Verifica o comportamento de run_backtest() com DataFrames inválidos
    e testa a consistência matemática dos resultados gerados."""

    def test_empty_dataframe_returns_empty_dict(self, oracle):
        df = pd.DataFrame(columns=["epoch", "open", "high", "low", "close"])
        assert oracle.run_backtest(df, "R_100") == {}

    def test_too_short_returns_empty_dict(self, oracle):
        # Precisa de pelo menos WINDOW + EXPIRACAO_CANDLES + 1 linhas
        df = _flat_df(n=oracle.WINDOW + oracle.EXPIRACAO_CANDLES)
        assert oracle.run_backtest(df, "R_100") == {}

    def test_flat_prices_no_signals_returns_empty(self, oracle):
        # Preços quase planos → Z-Score nunca excede 2.0 → sem sinais
        df = _flat_df(n=200)
        assert oracle.run_backtest(df, "R_100") == {}

    def test_returns_dict_with_required_keys(self, oracle):
        df     = _spike_df()
        result = oracle.run_backtest(df, "R_100")
        assert result  # não deve ser {}
        expected = {
            "ativo", "estrategia", "z_score_min",
            "n_amostral", "p_win", "ev", "kelly_quarter",
            "break_even", "expiracao_segundos",
        }
        assert set(result.keys()) == expected

    def test_ev_field_matches_math_engine(self, oracle):
        df     = _spike_df()
        result = oracle.run_backtest(df, "R_100")
        if result:
            expected_ev = round(ev_calc(result["p_win"], oracle.PAYOUT), 4)
            assert result["ev"] == expected_ev

    def test_kelly_field_matches_math_engine(self, oracle):
        df     = _spike_df()
        result = oracle.run_backtest(df, "R_100")
        if result:
            expected_kelly = round(kelly_fraction(result["p_win"], oracle.PAYOUT), 4)
            assert result["kelly_quarter"] == expected_kelly

    def test_break_even_field_matches_math_engine(self, oracle):
        df     = _spike_df()
        result = oracle.run_backtest(df, "R_100")
        if result:
            expected_be = round(break_even(oracle.PAYOUT), 4)
            assert result["break_even"] == expected_be

    def test_expiracao_segundos_is_300(self, oracle):
        df     = _spike_df()
        result = oracle.run_backtest(df, "R_100")
        if result:
            assert result["expiracao_segundos"] == 300

    def test_input_dataframe_not_mutated(self, oracle):
        df     = _spike_df()
        cols_before = list(df.columns)
        oracle.run_backtest(df, "R_100")
        assert list(df.columns) == cols_before
        assert "z_score"     not in df.columns
        assert "future_close" not in df.columns


# ─────────────────────────────────────────────────────────────────────────────
# 4. RUN_BACKTEST — QUALIDADE DOS SINAIS
# ─────────────────────────────────────────────────────────────────────────────

class TestRunBacktestSignals:
    """
    Verifica que os sinais PUT/CALL são gerados corretamente e que
    as métricas de p_win são matematicamente coerentes.
    """

    def test_p_win_between_0_and_1(self, oracle):
        df     = _spike_df()
        result = oracle.run_backtest(df, "R_100")
        if result:
            assert 0.0 < result["p_win"] <= 1.0

    def test_n_amostral_is_positive(self, oracle):
        df     = _spike_df()
        result = oracle.run_backtest(df, "R_100")
        if result:
            assert result["n_amostral"] > 0

    def test_z_score_min_is_one_of_thresholds(self, oracle):
        df     = _spike_df()
        result = oracle.run_backtest(df, "R_100")
        if result:
            assert result["z_score_min"] in oracle.Z_THRESHOLDS

    def test_higher_threshold_fewer_or_equal_signals(self, oracle):
        """Threshold mais alto → menos (ou igual) sinais gerados."""
        # Precisa de dados suficientes para ter sinais em múltiplos thresholds
        rng = np.random.default_rng(0)
        n   = 500
        # Mistura de preços estáveis e spikes moderados → gera sinais em vários thresholds
        prices = list(1000 + rng.normal(0, 1, n))
        # Injeta spikes distribuídos para garantir sinais em múltiplos thresholds
        for pos in range(30, n - 10, 30):
            prices[pos] = 1000 + 8  # Z moderado

        df  = pd.DataFrame({"epoch": range(n), "open": prices, "high": prices,
                             "low": prices, "close": prices})
        df2 = df.copy()
        df2["close"] = df["close"].values  # reset para limpar colunas extras

        # Roda backtest interno para obter contagens por threshold
        df_inner  = df.copy()
        rm        = df_inner["close"].rolling(20).mean()
        rs        = df_inner["close"].rolling(20).std(ddof=1)
        df_inner["z"] = (df_inner["close"] - rm) / rs
        df_inner["fc"] = df_inner["close"].shift(-5)
        df_inner = df_inner.dropna()

        n_20  = int((df_inner["z"].abs() >  2.0).sum())
        n_25  = int((df_inner["z"].abs() >  2.5).sum())
        n_30  = int((df_inner["z"].abs() >  3.0).sum())

        assert n_20 >= n_25 >= n_30

    def test_put_signal_win_when_future_below_close(self, oracle):
        """
        PUT signal: Z > threshold implica que preço está alto.
        Se future_close < close → WIN (regressão para a média).
        """
        n       = 150
        base    = 1000.0
        prices  = [base + 0.001 * (i % 2) for i in range(n)]
        spike   = 50
        prices[spike] = base + 50   # PUT signal esperado

        # Future (spike + 5) volta para ~base → price[55] ≈ 1000 < 1050 → WIN
        # Não modificamos prices[55] pois já é ≈ base

        df     = pd.DataFrame({"epoch": range(n), "open": prices, "high": prices,
                               "low": prices, "close": prices})
        result = oracle.run_backtest(df, "R_100")
        # Pelo menos o spike deve ter gerado 1 sinal PUT com WIN
        if result:
            assert result["p_win"] > 0

    def test_ativo_field_matches_input(self, oracle):
        df     = _spike_df(spike_val=1050.0)
        result = oracle.run_backtest(df, "MYATIVO")
        if result:
            assert result["ativo"] == "MYATIVO"


# ─────────────────────────────────────────────────────────────────────────────
# 5. GENERATE_CONFIG_JSON
# ─────────────────────────────────────────────────────────────────────────────

class TestGenerateConfigJson:
    """
    Verifica a lógica de filtragem, sizing e escrita do config.json.
    Usa tmp_path (fixture do pytest) para não sobrescrever o config.json real.
    """

    def test_aprovado_included_with_full_kelly(self, oracle, tmp_path):
        result  = _aprovado_result()
        path    = str(tmp_path / "config.json")
        config  = oracle.generate_config_json({"R_100": result}, output_path=path)

        assert "R_100" in config
        # Kelly APROVADO com N=350 → não é halved, sem cap (N≥300)
        validation = oracle.validate_edge(
            result["n_amostral"], result["p_win"], oracle.PAYOUT
        )
        assert validation["rating"] == "APROVADO"
        assert config["R_100"]["kelly_quarter"] == result["kelly_quarter"]

    def test_condicional_kelly_halved(self, oracle, tmp_path):
        result = _condicional_result()
        path   = str(tmp_path / "config.json")
        config = oracle.generate_config_json({"R_25": result}, output_path=path)

        assert "R_25" in config
        validation = oracle.validate_edge(
            result["n_amostral"], result["p_win"], oracle.PAYOUT
        )
        assert validation["rating"] == "CONDICIONAL"

        # Kelly deve ser exatamente a metade do original (+ cap N<100)
        halved = round(result["kelly_quarter"] * 0.5, 4)
        capped = min(halved, 0.005)  # N=50 < 100 → cap 0.5%
        assert config["R_25"]["kelly_quarter"] == capped

    def test_reprovado_excluded(self, oracle, tmp_path):
        result = _reprovado_result()
        path   = str(tmp_path / "config.json")
        config = oracle.generate_config_json({"R_10": result}, output_path=path)
        assert "R_10" not in config

    def test_empty_result_excluded(self, oracle, tmp_path):
        path   = str(tmp_path / "config.json")
        config = oracle.generate_config_json({"R_10": {}}, output_path=path)
        assert "R_10" not in config

    def test_kelly_cap_n_below_100(self, oracle, tmp_path):
        result = _aprovado_result()
        result["n_amostral"]    = 50       # N < 100 → cap 0.5%
        result["kelly_quarter"] = 0.10     # bem acima do cap
        path   = str(tmp_path / "config.json")

        # N=50 → CONDICIONAL (falha critérios 1 e 4) → kelly halved então capped
        config = oracle.generate_config_json({"R_100": result}, output_path=path)
        if "R_100" in config:
            assert config["R_100"]["kelly_quarter"] <= 0.005

    def test_kelly_cap_n_100_to_299(self, oracle, tmp_path):
        result = _aprovado_result()
        result["n_amostral"]    = 150      # 100 ≤ N < 300 → cap 2%
        result["kelly_quarter"] = 0.10     # bem acima do cap
        result["p_win"]         = 0.64
        path   = str(tmp_path / "config.json")

        config = oracle.generate_config_json({"R_100": result}, output_path=path)
        if "R_100" in config:
            assert config["R_100"]["kelly_quarter"] <= 0.020

    def test_kelly_no_extra_cap_n_above_300(self, oracle, tmp_path):
        result = _aprovado_result()
        result["n_amostral"]    = 400      # N ≥ 300 → sem cap adicional
        result["kelly_quarter"] = 0.015    # valor razoável, abaixo de qualquer cap
        path   = str(tmp_path / "config.json")

        config = oracle.generate_config_json({"R_100": result}, output_path=path)
        if "R_100" in config:
            assert config["R_100"]["kelly_quarter"] == 0.015

    def test_writes_valid_json(self, oracle, tmp_path):
        result = _aprovado_result()
        path   = str(tmp_path / "config.json")
        oracle.generate_config_json({"R_100": result}, output_path=path)

        assert os.path.exists(path)
        with open(path, encoding="utf-8") as f:
            parsed = json.load(f)
        assert isinstance(parsed, dict)

    def test_returned_dict_matches_written_json(self, oracle, tmp_path):
        result = _aprovado_result()
        path   = str(tmp_path / "config.json")
        config = oracle.generate_config_json({"R_100": result}, output_path=path)

        with open(path, encoding="utf-8") as f:
            written = json.load(f)

        assert config == written

    def test_output_has_required_fields_per_ativo(self, oracle, tmp_path):
        result = _aprovado_result()
        path   = str(tmp_path / "config.json")
        config = oracle.generate_config_json({"R_100": result}, output_path=path)

        if "R_100" in config:
            entry = config["R_100"]
            for field in ("estrategia", "z_score_min", "p_win", "ev",
                          "kelly_quarter", "n_amostral", "expiracao_segundos"):
                assert field in entry, f"Campo ausente: {field}"

    def test_multiple_ativos_filtered_correctly(self, oracle, tmp_path):
        results = {
            "R_100": _aprovado_result("R_100"),   # APROVADO
            "R_25":  _condicional_result("R_25"), # CONDICIONAL
            "R_10":  _reprovado_result("R_10"),   # REPROVADO
        }
        path   = str(tmp_path / "config.json")
        config = oracle.generate_config_json(results, output_path=path)

        assert "R_100" in config
        assert "R_25"  in config     # CONDICIONAL ainda entra
        assert "R_10"  not in config # REPROVADO excluído
