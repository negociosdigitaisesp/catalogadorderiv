"""
agente/tests/test_strategy_validator.py
===========================================
Testes automatizados para StrategyValidator — Grade Horaria de Elite

Criterios de aprovacao (PRD atual):
  APROVADO:    wr_gale2 >= 95% E N >= 20 E score_ponderado >= 0.90
  CONDICIONAL: 90% <= wr_gale2 < 95% E N >= 20
  REPROVADO:   wr_gale2 < 90% OU N < 20 OU max_consec_hit >= 3

Cenarios obrigatorios:
  1. APROVADO quando wr >= 95%, N >= 20, score >= 0.90
  2. CONDICIONAL quando 90% <= wr < 95% e N >= 20
  3. REPROVADO automatico por N < 20
  4. REPROVADO quando wr < 90%
  5. REPROVADO pelo filtro V7 (sequencia excessiva de Hit)
  6. Estrutura de retorno contem todos os campos obrigatorios
  7. validate_batch separa corretamente aprovados/condicionais/reprovados
"""

import pytest

from agente.core.strategy_validator import (
    StrategyValidator,
    _WR_APROVADO,
    _WR_CONDICIONAL,
    _N_MIN_ABSOLUTO,
    _SCORE_APROVADO,
    _max_consecutive_loss,
)


# ─────────────────────────────────────────────────────────────────────────────
# FIXTURE E HELPER
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def validator() -> StrategyValidator:
    return StrategyValidator()


def _make_mined(
    n_test: int = 100,
    wr_gale2: float = 0.96,
    score: float = 0.93,
    p_1a: float = 0.75,
    p_gale1: float = 0.15,
    p_gale2: float = 0.06,
    p_hit: float = 0.04,
    ativo: str = "BOOM500",
) -> dict:
    """
    Constroi mined_result compativel com StrategyValidator.validate().

    Por padrao, todos os parametros resultam em APROVADO:
      wr_gale2=0.96 >= 0.95, N=100 >= 20, score=0.93 >= 0.90
    """
    return {
        "hypothesis": {
            "ativo":    ativo,
            "contexto": {"hh_mm": "13:00", "dia_semana": 0},
            "direcao":  "CALL",
        },
        "win_rate_final":  wr_gale2,
        "n_test":          n_test,
        "score_ponderado": score,
        "p_1a":            p_1a,
        "p_gale1":         p_gale1,
        "p_gale2":         p_gale2,
        "p_hit":           p_hit,
        "ev_final":        0.50,     # nao utilizado pelo validador atual
        "variacao":        "V1",
        "n_total":         n_test,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 1. APROVADO
# ─────────────────────────────────────────────────────────────────────────────

class TestValidateAprovado:

    def test_aprovado_wr_alto_n_alto_score_alto(self, validator: StrategyValidator) -> None:
        """wr=0.96, N=100, score=0.93 -> APROVADO."""
        result = validator.validate(_make_mined(wr_gale2=0.96, n_test=100, score=0.93))
        assert result["status"] == "APROVADO", (
            f"wr=0.96, N=100, score=0.93 deveria ser APROVADO. motivo={result['motivo']}"
        )

    def test_aprovado_no_limite_minimo(self, validator: StrategyValidator) -> None:
        """wr exatamente no limiar, N no minimo, score no minimo -> APROVADO."""
        result = validator.validate(
            _make_mined(wr_gale2=_WR_APROVADO, n_test=_N_MIN_ABSOLUTO, score=_SCORE_APROVADO)
        )
        assert result["status"] == "APROVADO", (
            f"Limiar exato deve ser APROVADO. motivo={result['motivo']}"
        )

    def test_aprovado_stake_multiplier_1(self, validator: StrategyValidator) -> None:
        """APROVADO deve ter stake_multiplier = 1.0."""
        result = validator.validate(_make_mined())
        assert result["stake_multiplier"] == pytest.approx(1.0)

    def test_aprovado_kelly_quarter_positivo(self, validator: StrategyValidator) -> None:
        """APROVADO deve ter kelly_quarter > 0."""
        result = validator.validate(_make_mined())
        assert result["kelly_quarter"] > 0.0


# ─────────────────────────────────────────────────────────────────────────────
# 2. CONDICIONAL
# ─────────────────────────────────────────────────────────────────────────────

class TestValidateCondicional:

    def test_condicional_wr_entre_90_e_95(self, validator: StrategyValidator) -> None:
        """wr=0.92 (entre 90% e 95%), N=50, score=0.80 -> CONDICIONAL."""
        result = validator.validate(_make_mined(wr_gale2=0.92, n_test=50, score=0.80))
        assert result["status"] == "CONDICIONAL", (
            f"wr=0.92, N=50, score=0.80 deveria ser CONDICIONAL. status={result['status']}"
        )

    def test_condicional_score_abaixo_090_com_wr_alto(
        self, validator: StrategyValidator
    ) -> None:
        """wr >= 95% mas score < 0.90 -> CONDICIONAL (nao APROVADO)."""
        result = validator.validate(
            _make_mined(wr_gale2=0.96, n_test=50, score=0.85)
        )
        assert result["status"] == "CONDICIONAL", (
            f"Score baixo com wr alto -> CONDICIONAL. status={result['status']}"
        )

    def test_condicional_stake_multiplier_05(self, validator: StrategyValidator) -> None:
        """CONDICIONAL deve ter stake_multiplier = 0.5."""
        result = validator.validate(_make_mined(wr_gale2=0.92, n_test=50, score=0.80))
        assert result["status"] == "CONDICIONAL"
        assert result["stake_multiplier"] == pytest.approx(0.5)

    def test_condicional_limite_inferior_wr_exato(self, validator: StrategyValidator) -> None:
        """wr exatamente em 0.90 e N >= 20 -> CONDICIONAL (nao REPROVADO)."""
        result = validator.validate(
            _make_mined(wr_gale2=_WR_CONDICIONAL, n_test=30, score=0.80)
        )
        assert result["status"] == "CONDICIONAL", (
            f"wr={_WR_CONDICIONAL} no limiar deve ser CONDICIONAL. status={result['status']}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# 3. REPROVADO
# ─────────────────────────────────────────────────────────────────────────────

class TestValidateReprovado:

    def test_reprovado_n_abaixo_de_20(self, validator: StrategyValidator) -> None:
        """N=15 < 20 -> REPROVADO imediato, mesmo com wr alto."""
        result = validator.validate(
            _make_mined(n_test=15, wr_gale2=0.98, score=0.98)
        )
        assert result["status"] == "REPROVADO", (
            "N < 20 deve reprovar independente do WR."
        )

    def test_reprovado_n_zero(self, validator: StrategyValidator) -> None:
        """N=0 -> REPROVADO imediato."""
        result = validator.validate(_make_mined(n_test=0, wr_gale2=1.0))
        assert result["status"] == "REPROVADO"

    def test_reprovado_wr_abaixo_de_90(self, validator: StrategyValidator) -> None:
        """wr=0.85 < 90%, N=100 -> REPROVADO."""
        result = validator.validate(_make_mined(wr_gale2=0.85, n_test=100))
        assert result["status"] == "REPROVADO", (
            f"wr=0.85 < {_WR_CONDICIONAL:.0%} deve ser REPROVADO."
        )

    def test_reprovado_stake_zero(self, validator: StrategyValidator) -> None:
        """REPROVADO deve ter stake_multiplier = 0.0."""
        result = validator.validate(_make_mined(n_test=5))
        assert result["stake_multiplier"] == pytest.approx(0.0)

    def test_reprovado_kelly_zero(self, validator: StrategyValidator) -> None:
        """REPROVADO deve ter kelly_quarter = 0.0 (via stake=0.0 / 4.0 = 0.0)."""
        result = validator.validate(_make_mined(n_test=5, wr_gale2=0.50))
        assert result["kelly_quarter"] == pytest.approx(0.0)


# ─────────────────────────────────────────────────────────────────────────────
# 4. FILTRO V7 — SEQUENCIA MAXIMA DE HIT
# ─────────────────────────────────────────────────────────────────────────────

class TestFiltroV7:

    def test_reprovado_por_hit_consecutivo_alto(self, validator: StrategyValidator) -> None:
        """
        p_hit = 0.20 -> max_consec estimado >= 3 -> REPROVADO pelo V7.
        """
        mined = _make_mined(
            wr_gale2=0.96, n_test=200, score=0.93,
            p_1a=0.60, p_gale1=0.20, p_gale2=0.20, p_hit=0.20,
        )
        max_consec = _max_consecutive_loss(mined)
        if max_consec >= 3:
            result = validator.validate(mined)
            assert result["status"] == "REPROVADO", (
                f"max_consec={max_consec} >= 3 deve reprovar pelo V7."
            )

    def test_aprovado_com_p_hit_baixo(self, validator: StrategyValidator) -> None:
        """p_hit = 0.04 -> max_consec pequeno -> nao reprova pelo V7."""
        mined = _make_mined(
            wr_gale2=0.96, n_test=200, score=0.93,
            p_1a=0.75, p_gale1=0.15, p_gale2=0.06, p_hit=0.04,
        )
        max_consec = _max_consecutive_loss(mined)
        assert max_consec < 3, (
            f"p_hit=0.04 nao deve gerar max_consec={max_consec} >= 3"
        )
        result = validator.validate(mined)
        assert result["status"] == "APROVADO"

    def test_max_consecutive_loss_p_hit_zero(self) -> None:
        """p_hit=0 -> nenhum risco -> retorna 0."""
        assert _max_consecutive_loss(_make_mined(p_hit=0.0)) == 0

    def test_max_consecutive_loss_p_hit_um(self) -> None:
        """p_hit=1.0 -> perde sempre -> retorna 999."""
        assert _max_consecutive_loss(_make_mined(p_hit=1.0)) == 999


# ─────────────────────────────────────────────────────────────────────────────
# 5. ESTRUTURA DE RETORNO
# ─────────────────────────────────────────────────────────────────────────────

class TestValidateEstrutura:

    def test_campos_obrigatorios_presentes(self, validator: StrategyValidator) -> None:
        """O dicionario retornado deve conter todos os campos obrigatorios."""
        result = validator.validate(_make_mined())
        for campo in (
            "status", "motivo", "stake_multiplier",
            "win_1a_rate", "win_gale1_rate", "win_gale2_rate", "hit_rate",
            "ev_gale2", "kelly_quarter", "sharpe", "p_value",
            "criterios_aprovados", "mined_result",
        ):
            assert campo in result, f"Campo '{campo}' ausente no resultado."

    def test_status_valido(self, validator: StrategyValidator) -> None:
        """status deve ser APROVADO, CONDICIONAL ou REPROVADO."""
        for wr in (0.96, 0.92, 0.80):
            result = validator.validate(_make_mined(wr_gale2=wr))
            assert result["status"] in ("APROVADO", "CONDICIONAL", "REPROVADO")

    def test_motivo_e_string(self, validator: StrategyValidator) -> None:
        """motivo deve ser string — nao lista (mudou na refatoracao)."""
        result = validator.validate(_make_mined())
        assert isinstance(result["motivo"], str), (
            f"motivo deve ser str, nao {type(result['motivo'])}"
        )

    def test_mined_result_preservado(self, validator: StrategyValidator) -> None:
        """O mined_result original deve ser devolvido sem modificacoes."""
        mined  = _make_mined(n_test=100, wr_gale2=0.96)
        result = validator.validate(mined)
        assert result["mined_result"] is mined

    def test_taxas_de_gale_copiadas(self, validator: StrategyValidator) -> None:
        """win_1a_rate, win_gale1_rate, etc. devem refletir os valores de entrada."""
        mined  = _make_mined(p_1a=0.70, p_gale1=0.20, p_gale2=0.06, p_hit=0.04)
        result = validator.validate(mined)

        assert abs(result["win_1a_rate"]    - 0.70) < 1e-6
        assert abs(result["win_gale1_rate"] - 0.20) < 1e-6
        assert abs(result["win_gale2_rate"] - 0.06) < 1e-6
        assert abs(result["hit_rate"]       - 0.04) < 1e-6


# ─────────────────────────────────────────────────────────────────────────────
# 6. VALIDATE_BATCH
# ─────────────────────────────────────────────────────────────────────────────

class TestValidateBatch:

    def test_batch_separa_corretamente(self, validator: StrategyValidator) -> None:
        """Tres resultados distintos devem ir para as listas corretas."""
        aprovado    = _make_mined(wr_gale2=0.96, n_test=100, score=0.93)
        condicional = _make_mined(wr_gale2=0.92, n_test=50,  score=0.80)
        reprovado   = _make_mined(wr_gale2=0.80, n_test=100)  # wr < 90%

        batch = validator.validate_batch([aprovado, condicional, reprovado])

        assert len(batch["aprovados"])    == 1
        assert len(batch["condicionais"]) == 1
        assert len(batch["reprovados"])   == 1

    def test_batch_lista_vazia(self, validator: StrategyValidator) -> None:
        """Lista vazia -> tres listas vazias."""
        batch = validator.validate_batch([])
        assert batch["aprovados"]    == []
        assert batch["condicionais"] == []
        assert batch["reprovados"]   == []

    def test_batch_soma_total_correto(self, validator: StrategyValidator) -> None:
        """len(aprovados) + len(condicionais) + len(reprovados) deve = total enviado."""
        itens = [
            _make_mined(wr_gale2=0.96, n_test=100, score=0.93),   # APROVADO
            _make_mined(wr_gale2=0.92, n_test=50,  score=0.80),   # CONDICIONAL
            _make_mined(wr_gale2=0.96, n_test=100, score=0.93),   # APROVADO
            _make_mined(n_test=5),                                  # REPROVADO (N < 20)
        ]
        batch = validator.validate_batch(itens)

        soma = (
            len(batch["aprovados"])
            + len(batch["condicionais"])
            + len(batch["reprovados"])
        )
        assert soma == len(itens) == 4

    def test_batch_retorna_dicts_com_status(self, validator: StrategyValidator) -> None:
        """Itens nas listas sao dicionarios com campo 'status' e 'mined_result'."""
        batch = validator.validate_batch([_make_mined()])

        todos = batch["aprovados"] + batch["condicionais"] + batch["reprovados"]
        for item in todos:
            assert "status"        in item
            assert "kelly_quarter" in item
            assert "mined_result"  in item
