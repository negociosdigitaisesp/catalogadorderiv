"""
agente/tests/test_hypothesis_generator.py
==========================================
Testes automatizados para HypothesisGenerator

Schema v2: coluna de resultado = 'proxima_1' (valores: 'VERDE'/'VERMELHA')
Campos contextuais: hh_mm, dia_semana, cor_atual, mhi_seq, tendencia_m5, tendencia_m15

Cenarios obrigatorios (PRD):
  1. N insuficiente (< 100) -> hipotese deve ser filtrada
  2. Edge insuficiente (< min_edge) -> hipotese deve ser filtrada
  3. Caso valido -> retorna hipotese com estrutura correta
  4. Ordenacao por prioridade -> maior prioridade primeiro
  5. Maximo 200 hipoteses retornadas
"""

import json
import sqlite3
import tempfile
from pathlib import Path

import pandas as pd
import pytest

from agente.core.hypothesis_generator import HypothesisGenerator


# ─────────────────────────────────────────────────────────────────────────────
# FIXTURES
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def gen() -> HypothesisGenerator:
    """Instancia do gerador de hipoteses."""
    return HypothesisGenerator()


def _make_df(
    n_win: int,
    n_loss: int,
    ativo: str = "TEST",
    hh_mm: str = "10:00",
    dia_semana: int = 0,
) -> pd.DataFrame:
    """Cria um DataFrame minimo em memoria para testes (schema v2)."""
    rows = (
        [{"ativo": ativo, "proxima_1": "VERDE",    "hh_mm": hh_mm, "dia_semana": dia_semana}] * n_win
        + [{"ativo": ativo, "proxima_1": "VERMELHA", "hh_mm": hh_mm, "dia_semana": dia_semana}] * n_loss
    )
    return pd.DataFrame(rows)


def _make_db_with_df(df: pd.DataFrame) -> str:
    """Cria um SQLite temporario com a tabela 'candles' e retorna o path."""
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    with sqlite3.connect(tmp.name) as conn:
        df.to_sql("candles", conn, if_exists="replace", index=False)
    return tmp.name


# ─────────────────────────────────────────────────────────────────────────────
# TESTES: load_catalog
# ─────────────────────────────────────────────────────────────────────────────

class TestLoadCatalog:
    def test_loads_successfully(self, gen: HypothesisGenerator) -> None:
        """Deve retornar um DataFrame com o mesmo numero de linhas."""
        df_orig = _make_df(150, 50)
        path = _make_db_with_df(df_orig)
        df = gen.load_catalog(path)
        assert isinstance(df, pd.DataFrame)
        assert len(df) == 200

    def test_raises_if_file_not_found(self, gen: HypothesisGenerator) -> None:
        """Deve levantar FileNotFoundError para path invalido."""
        with pytest.raises(FileNotFoundError):
            gen.load_catalog("/tmp/nao_existe_xyz_abc.db")


# ─────────────────────────────────────────────────────────────────────────────
# TESTES: compute_base_frequencies
# ─────────────────────────────────────────────────────────────────────────────

class TestBaseFrequencies:
    def test_p_win_correct(self, gen: HypothesisGenerator) -> None:
        """P(VERDE) deve ser 0.75 com 150 wins e 50 losses."""
        df = _make_df(150, 50)
        base = gen.compute_base_frequencies(df)
        assert abs(base["p_win_global"] - 0.75) < 1e-9

    def test_p_win_plus_p_loss_equals_one(self, gen: HypothesisGenerator) -> None:
        """P(WIN) + P(LOSS) deve ser exatamente 1."""
        df = _make_df(80, 120)
        base = gen.compute_base_frequencies(df)
        assert abs(base["p_win_global"] + base["p_loss_global"] - 1.0) < 1e-9

    def test_n_total_correct(self, gen: HypothesisGenerator) -> None:
        """n_total deve bater com o tamanho do DataFrame."""
        df = _make_df(90, 40)
        base = gen.compute_base_frequencies(df)
        assert base["n_total"] == 130

    def test_raises_missing_outcome_col(self, gen: HypothesisGenerator) -> None:
        """Deve levantar ValueError se coluna 'proxima_1' estiver ausente."""
        df = pd.DataFrame({"ativo": ["X"] * 10})
        with pytest.raises(ValueError, match="proxima_1"):
            gen.compute_base_frequencies(df)


# ─────────────────────────────────────────────────────────────────────────────
# TESTES: generate_hypotheses — Filtros PRD
# ─────────────────────────────────────────────────────────────────────────────

class TestGenerateHypotheses:

    def _df_with_two_contexts(
        self,
        n_valid: int,
        n_win_valid: int,
        n_small: int,
        n_win_small: int,
    ) -> pd.DataFrame:
        """
        Constroi um DataFrame com dois contextos (schema v2):
          - Contexto A: hh_mm=10:00, dia_semana=0 -- contexto "valido" (N configuravel)
          - Contexto B: hh_mm=20:00, dia_semana=4 -- contexto "pequeno" (N configuravel)
        """
        rows = []
        # Contexto A
        rows += [{"ativo": "R_50", "proxima_1": "VERDE",    "hh_mm": "10:00", "dia_semana": 0}] * n_win_valid
        rows += [{"ativo": "R_50", "proxima_1": "VERMELHA", "hh_mm": "10:00", "dia_semana": 0}] * (n_valid - n_win_valid)
        # Contexto B (pequeno)
        rows += [{"ativo": "R_50", "proxima_1": "VERDE",    "hh_mm": "20:00", "dia_semana": 4}] * n_win_small
        rows += [{"ativo": "R_50", "proxima_1": "VERMELHA", "hh_mm": "20:00", "dia_semana": 4}] * (n_small - n_win_small)
        return pd.DataFrame(rows)

    # ── Caso 1: N insuficiente ────────────────────────────────────────────────

    def test_filters_insufficient_n(self, gen: HypothesisGenerator) -> None:
        """Contexto com N < 100 deve ser filtrado mesmo com alto edge."""
        # Contexto A: apenas 50 amostras com 100% VERDE
        # Contexto B: 200 amostras neutras (50/50), dia_semana diferente -> sem edge
        rows = (
            [{"ativo": "R_50", "proxima_1": "VERDE",    "hh_mm": "10:00", "dia_semana": 0}] * 50
            + [{"ativo": "R_50", "proxima_1": "VERMELHA", "hh_mm": "10:00", "dia_semana": 1}] * 200
        )
        df = pd.DataFrame(rows)
        hipoteses = gen.generate_hypotheses(df, min_edge=0.05, min_n=100)

        # O unico contexto com 50 amostras deve ser descartado
        for h in hipoteses:
            assert h["n_amostras"] >= 100, (
                f"Hipotese com N={h['n_amostras']} nao deveria ter sido retornada."
            )

    # ── Caso 2: Edge insuficiente ─────────────────────────────────────────────

    def test_filters_insufficient_edge(self, gen: HypothesisGenerator) -> None:
        """Contexto com edge < min_edge deve ser filtrado mesmo com N alto."""
        # Dois contextos com o mesmo win rate de 55% -> edge relativo a si mesmo = 0
        n = 200
        rows = (
            [{"ativo": "R_50", "proxima_1": "VERDE",    "hh_mm": "10:00", "dia_semana": 0}] * int(n * 0.55)
            + [{"ativo": "R_50", "proxima_1": "VERMELHA", "hh_mm": "10:00", "dia_semana": 0}] * int(n * 0.45)
            + [{"ativo": "R_50", "proxima_1": "VERDE",    "hh_mm": "20:00", "dia_semana": 1}] * int(n * 0.55)
            + [{"ativo": "R_50", "proxima_1": "VERMELHA", "hh_mm": "20:00", "dia_semana": 1}] * int(n * 0.45)
        )
        df = pd.DataFrame(rows)
        hipoteses = gen.generate_hypotheses(df, min_edge=0.05, min_n=100)

        # Nenhuma hipotese deve ter edge < 0.05
        for h in hipoteses:
            assert h["edge_bruto"] >= 0.05, (
                f"Edge {h['edge_bruto']:.4f} abaixo do minimo de 0.05"
            )

    # ── Caso 3: Hipotese valida ───────────────────────────────────────────────

    def test_valid_hypothesis_structure(self, gen: HypothesisGenerator) -> None:
        """Hipotese valida deve conter todos os campos obrigatorios com tipos corretos."""
        # Contexto alto edge: 90% VERDE, N=150 (hh_mm=13:00, dia_semana=0)
        # Baseline neutro: 50% VERDE, N=200 (hh_mm=09:00, dia_semana=2)
        rows = (
            [{"ativo": "BOOM500", "proxima_1": "VERDE",    "hh_mm": "13:00", "dia_semana": 0}] * 135
            + [{"ativo": "BOOM500", "proxima_1": "VERMELHA", "hh_mm": "13:00", "dia_semana": 0}] * 15
            + [{"ativo": "BOOM500", "proxima_1": "VERDE",    "hh_mm": "09:00", "dia_semana": 2}] * 100
            + [{"ativo": "BOOM500", "proxima_1": "VERMELHA", "hh_mm": "09:00", "dia_semana": 2}] * 100
        )
        df = pd.DataFrame(rows)
        hipoteses = gen.generate_hypotheses(df, min_edge=0.05, min_n=100)

        assert len(hipoteses) > 0, "Ao menos 1 hipotese valida deve ter sido gerada."

        # Valida a estrutura do primeiro elemento (maior prioridade)
        h = hipoteses[0]
        assert isinstance(h["ativo"], str)
        assert isinstance(h["contexto"], dict)
        assert h["direcao"] in ("CALL", "PUT")
        assert 0.0 <= h["p_win_condicional"] <= 1.0
        assert 0.0 <= h["p_win_global"] <= 1.0
        assert h["edge_bruto"] >= 0.05
        assert h["n_amostras"] >= 100
        assert h["prioridade"] > 0.0

    # ── Caso 4: Ordenacao por prioridade ──────────────────────────────────────

    def test_sorted_by_priority_descending(self, gen: HypothesisGenerator) -> None:
        """As hipoteses devem estar ordenadas por prioridade decrescente."""
        # Contexto alto edge: 90% VERDE, N=200 (hh_mm=13:00, dia_semana=0)
        # Contexto medio edge: 75% VERDE, N=200 (hh_mm=10:00, dia_semana=3)
        # Baseline: 50% VERDE, N=200 (hh_mm=09:00, dia_semana=2)
        rows = (
            [{"ativo": "CRASH500", "proxima_1": "VERDE",    "hh_mm": "13:00", "dia_semana": 0}] * 180
            + [{"ativo": "CRASH500", "proxima_1": "VERMELHA", "hh_mm": "13:00", "dia_semana": 0}] * 20
            + [{"ativo": "CRASH500", "proxima_1": "VERDE",    "hh_mm": "10:00", "dia_semana": 3}] * 150
            + [{"ativo": "CRASH500", "proxima_1": "VERMELHA", "hh_mm": "10:00", "dia_semana": 3}] * 50
            + [{"ativo": "CRASH500", "proxima_1": "VERDE",    "hh_mm": "09:00", "dia_semana": 2}] * 100
            + [{"ativo": "CRASH500", "proxima_1": "VERMELHA", "hh_mm": "09:00", "dia_semana": 2}] * 100
        )
        df = pd.DataFrame(rows)
        hipoteses = gen.generate_hypotheses(df, min_edge=0.05, min_n=100)

        assert len(hipoteses) >= 2, "Deve haver pelo menos 2 hipoteses geradas."

        prioridades = [h["prioridade"] for h in hipoteses]
        assert prioridades == sorted(prioridades, reverse=True), (
            "Hipoteses nao estao ordenadas por prioridade decrescente!"
        )

    # ── Caso 5: Limite de 200 hipoteses ──────────────────────────────────────

    def test_max_200_hypotheses(self, gen: HypothesisGenerator) -> None:
        """Nunca deve retornar mais de 200 hipoteses."""
        # Cria muitas combinacoes unicas (hh_mm x dia_semana)
        rows = []
        dias = [0, 1, 2, 3, 4]
        for h in range(24):
            hh_mm = f"{h:02d}:00"
            for dia in dias:
                # 120 amostras por contexto, 75% VERDE
                rows += [{"ativo": "R_10", "proxima_1": "VERDE",    "hh_mm": hh_mm, "dia_semana": dia}] * 90
                rows += [{"ativo": "R_10", "proxima_1": "VERMELHA", "hh_mm": hh_mm, "dia_semana": dia}] * 30
        df = pd.DataFrame(rows)
        hipoteses = gen.generate_hypotheses(df, min_edge=0.0, min_n=100, max_hypotheses=200)
        assert len(hipoteses) <= 200, f"Retornou {len(hipoteses)} hipoteses, maximo e 200."


# ─────────────────────────────────────────────────────────────────────────────
# TESTES: export_hypotheses
# ─────────────────────────────────────────────────────────────────────────────

class TestExportHypotheses:
    def test_exports_json_file(self, gen: HypothesisGenerator, tmp_path: Path) -> None:
        """Deve criar um arquivo hypotheses_*.json no diretorio especificado."""
        hipoteses = [{"ativo": "TEST", "prioridade": 1.0, "edge_bruto": 0.10}]
        gen.export_hypotheses(hipoteses, str(tmp_path))

        arquivos = list(tmp_path.glob("hypotheses_*.json"))
        assert len(arquivos) == 1, "Exatamente um arquivo JSON deve ser criado."

    def test_exported_content_matches(self, gen: HypothesisGenerator, tmp_path: Path) -> None:
        """O conteudo exportado deve ser identico a lista de entrada."""
        hipoteses = [
            {"ativo": "BOOM500", "prioridade": 2.5, "edge_bruto": 0.15},
            {"ativo": "CRASH500", "prioridade": 1.8, "edge_bruto": 0.12},
        ]
        gen.export_hypotheses(hipoteses, str(tmp_path))

        arquivo = next(tmp_path.glob("hypotheses_*.json"))
        with open(arquivo, encoding="utf-8") as fp:
            loaded = json.load(fp)

        assert loaded == hipoteses
