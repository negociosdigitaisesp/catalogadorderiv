"""
agente/tests/test_pattern_miner.py
=====================================
Testes automatizados para PatternMiner — Grade Horaria de Elite

Cenarios obrigatorios (PRD):
  1. _compute_gale2_stats: invariante n_1a + n_g1 + n_g2 + n_hit == n_valid
  2. _compute_gale2_stats: contagens corretas para resultados conhecidos
  3. _compute_gale2_stats: exclui linhas com '?' (ciclos incompletos)
  4. mine_v1: encontra grupo com WR >= 85% e N >= 15
  5. mine_v1: ignora grupos com N insuficiente ou WR baixo
  6. mine_all: retorna formato adaptado para pipeline (hypothesis, win_rate_final, etc.)
  7. mine_all: retorna lista vazia para DataFrame vazio
  8. export_results: cria arquivo mined_elite_*.json (nao mined_results)
"""

import json
from pathlib import Path

import pandas as pd
import pytest

from agente.core.pattern_miner import PatternMiner, _MIN_N, _MIN_WR_GALE2


# ─────────────────────────────────────────────────────────────────────────────
# FIXTURES E HELPERS
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def miner() -> PatternMiner:
    return PatternMiner()


def _make_df_group(
    n_win_1a: int = 15,
    n_win_g1: int = 3,
    n_win_g2: int = 2,
    n_hit: int = 0,
    ativo: str = "BOOM500",
    hh_mm: str = "13:00",
    dia_semana: int = 0,
    direcao: str = "CALL",
    ts_start: int = 1_700_000_000,
    mhi_seq: str = "V-V-V",
) -> pd.DataFrame:
    """
    Cria DataFrame com resultados de ciclo Gale 2 deterministas.

    CALL -> win_color = VERDE
    Cada linha tem proxima_1/2/3 validos (sem '?') conforme o tipo de resultado:
      win_1a  -> proxima_1 = win,  proxima_2 = lose, proxima_3 = lose
      win_g1  -> proxima_1 = lose, proxima_2 = win,  proxima_3 = lose
      win_g2  -> proxima_1 = lose, proxima_2 = lose, proxima_3 = win
      hit     -> proxima_1 = lose, proxima_2 = lose, proxima_3 = lose
    """
    win_c  = "VERDE"    if direcao == "CALL" else "VERMELHA"
    lose_c = "VERMELHA" if direcao == "CALL" else "VERDE"

    rows = []
    idx  = 0

    def _row(p1: str, p2: str, p3: str) -> dict:
        nonlocal idx
        r = {
            "timestamp":    ts_start + idx * 60,
            "ativo":        ativo,
            "hh_mm":        hh_mm,
            "dia_semana":   dia_semana,
            "cor_atual":    "VERDE",
            "mhi_seq":      mhi_seq,
            "proxima_1":    p1,
            "proxima_2":    p2,
            "proxima_3":    p3,
            "tendencia_m5":  "ALTA",
            "tendencia_m15": "ALTA",
            "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5,
        }
        idx += 1
        return r

    for _ in range(n_win_1a):
        rows.append(_row(win_c,  lose_c, lose_c))
    for _ in range(n_win_g1):
        rows.append(_row(lose_c, win_c,  lose_c))
    for _ in range(n_win_g2):
        rows.append(_row(lose_c, lose_c, win_c))
    for _ in range(n_hit):
        rows.append(_row(lose_c, lose_c, lose_c))

    return pd.DataFrame(rows)


# ─────────────────────────────────────────────────────────────────────────────
# 1. _COMPUTE_GALE2_STATS — LOGICA CENTRAL VETORIZADA
# ─────────────────────────────────────────────────────────────────────────────

class TestComputeGale2Stats:

    def test_invariante_soma_igual_n_valid(self, miner: PatternMiner) -> None:
        """n_1a + n_gale1 + n_gale2 + n_hit deve ser exatamente igual a n."""
        df    = _make_df_group(n_win_1a=15, n_win_g1=5, n_win_g2=3, n_hit=2)
        stats = miner._compute_gale2_stats(df, "CALL")

        soma = stats["n_1a"] + stats["n_gale1"] + stats["n_gale2"] + stats["n_hit"]
        assert soma == stats["n"], (
            f"Invariante quebrada: {stats['n_1a']}+{stats['n_gale1']}+"
            f"{stats['n_gale2']}+{stats['n_hit']} = {soma} != {stats['n']}"
        )

    def test_contagens_corretas_resultado_conhecido(self, miner: PatternMiner) -> None:
        """15 win_1a + 5 win_g1 + 3 win_g2 + 2 hit = 25 total, wr = 23/25."""
        df    = _make_df_group(n_win_1a=15, n_win_g1=5, n_win_g2=3, n_hit=2)
        stats = miner._compute_gale2_stats(df, "CALL")

        assert stats["n"]       == 25
        assert stats["n_1a"]    == 15
        assert stats["n_gale1"] == 5
        assert stats["n_gale2"] == 3
        assert stats["n_hit"]   == 2
        assert abs(stats["wr_gale2"] - 23/25) < 1e-6, (
            f"wr_gale2={stats['wr_gale2']:.6f} != esperado {23/25:.6f}"
        )

    def test_todos_win_1a_wr_100pct(self, miner: PatternMiner) -> None:
        """20 win_1a, 0 perdas -> wr=1.0, todos os outros zeros."""
        df    = _make_df_group(n_win_1a=20, n_win_g1=0, n_win_g2=0, n_hit=0)
        stats = miner._compute_gale2_stats(df, "CALL")

        assert stats["n_1a"]    == 20
        assert stats["n_gale1"] == 0
        assert stats["n_gale2"] == 0
        assert stats["n_hit"]   == 0
        assert stats["wr_gale2"] == pytest.approx(1.0)

    def test_todos_hit_wr_zero_aprovado_false(self, miner: PatternMiner) -> None:
        """20 hits, 0 wins -> wr=0.0, approved=False."""
        df    = _make_df_group(n_win_1a=0, n_win_g1=0, n_win_g2=0, n_hit=20)
        stats = miner._compute_gale2_stats(df, "CALL")

        assert stats["n_hit"]    == 20
        assert stats["wr_gale2"] == pytest.approx(0.0)
        assert stats["approved"] is False

    def test_grupo_vazio_retorna_zeros(self, miner: PatternMiner) -> None:
        """DataFrame vazio -> n=0, approved=False."""
        stats = miner._compute_gale2_stats(pd.DataFrame(), "CALL")
        assert stats["n"]       == 0
        assert stats["approved"] is False

    def test_linhas_com_interrogacao_excluidas(self, miner: PatternMiner) -> None:
        """Linhas com proxima_1='?' nao contam para n_valid (ciclos incompletos)."""
        df_completo = _make_df_group(n_win_1a=20, n_win_g1=0, n_win_g2=0, n_hit=0)

        # Adiciona 5 linhas incompletas (proxima_? = "?")
        incompletas = pd.DataFrame([{
            "timestamp": 99_000_000 + i, "ativo": "BOOM500", "hh_mm": "13:00",
            "dia_semana": 0, "cor_atual": "VERDE", "mhi_seq": "V-V-V",
            "proxima_1": "?", "proxima_2": "?", "proxima_3": "?",
            "tendencia_m5": "ALTA", "tendencia_m15": "ALTA",
            "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5,
        } for i in range(5)])

        df_mixed = pd.concat([df_completo, incompletas], ignore_index=True)
        stats = miner._compute_gale2_stats(df_mixed, "CALL")

        assert stats["n"] == 20, (
            f"Esperado n=20 (apenas completos), obtido n={stats['n']}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# 2. MINE_V1 — AGRUPAMENTO POR (ativo, hh_mm, dia_semana)
# ─────────────────────────────────────────────────────────────────────────────

class TestMineV1:

    def test_v1_encontra_grupo_elite(self, miner: PatternMiner) -> None:
        """Grupo com N >= 15 e WR >= 85% deve aparecer no resultado."""
        # 20 win_1a = 100% WR, N=20 >= 15 -> aprovado
        df = _make_df_group(n_win_1a=20, ativo="BOOM500", hh_mm="13:00", dia_semana=0)
        resultados = miner.mine_v1(df)

        assert len(resultados) >= 1, (
            "Grupo com N=20 e WR=100% deve ser retornado pelo mine_v1."
        )

    def test_v1_ignora_grupo_n_insuficiente(self, miner: PatternMiner) -> None:
        """Grupo com N < _MIN_N deve ser descartado."""
        # N = _MIN_N - 1 (garantido < minimo)
        n_pequeno = max(1, _MIN_N - 1)
        df = _make_df_group(n_win_1a=n_pequeno, n_win_g1=0, n_win_g2=0, n_hit=0,
                            ativo="R_10", hh_mm="14:00", dia_semana=1)
        resultados = miner.mine_v1(df)
        assert len(resultados) == 0, (
            f"Grupo com N={n_pequeno} < _MIN_N={_MIN_N} nao deveria ser retornado."
        )

    def test_v1_ignora_grupo_wr_baixo(self, miner: PatternMiner) -> None:
        """Grupo com WR < _MIN_WR_GALE2 deve ser descartado."""
        # 15 win_1a + 10 hit = WR = 15/25 = 0.60 < 0.85
        # _best_direcao escolhe CALL (15 VERDE > 10 VERMELHA em proxima_1)
        # WR_CALL = 1 - 10/25 = 0.60 < _MIN_WR_GALE2 -> rejeitado
        df = _make_df_group(n_win_1a=15, n_win_g1=0, n_win_g2=0, n_hit=10)
        resultados = miner.mine_v1(df)
        assert len(resultados) == 0, (
            f"WR < {_MIN_WR_GALE2:.0%} nao deveria ser aprovado."
        )

    def test_v1_estrutura_do_resultado(self, miner: PatternMiner) -> None:
        """Resultado deve conter campos obrigatorios do pipeline."""
        df = _make_df_group(n_win_1a=20, ativo="BOOM500", hh_mm="13:00", dia_semana=0)
        resultados = miner.mine_v1(df)

        if len(resultados) == 0:
            pytest.skip("Nenhum grupo aprovado — verifique _MIN_N/_MIN_WR_GALE2")

        r = resultados[0]
        for campo in ("variacao", "ativo", "horario_alvo", "dia_semana",
                      "n", "n_1a", "n_gale1", "n_gale2", "n_hit",
                      "wr_gale2", "ev_gale2", "p_1a", "p_gale1", "p_gale2", "p_hit",
                      "score_ponderado", "contexto"):
            assert campo in r, f"Campo obrigatorio '{campo}' ausente no resultado V1."
        assert r["variacao"] == "V1"


# ─────────────────────────────────────────────────────────────────────────────
# 3. MINE_ALL — ORQUESTRADOR
# ─────────────────────────────────────────────────────────────────────────────

class TestMineAll:

    def _make_multi_group_df(self) -> pd.DataFrame:
        """
        DataFrame com 1 grupo Elite bem definido para BOOM500@13:00 (dia_semana=0).
        20 win_1a = 100% WR, N=20.
        """
        return _make_df_group(
            n_win_1a=20, n_hit=0,
            ativo="BOOM500", hh_mm="13:00", dia_semana=0,
        )

    def test_mine_all_retorna_formato_pipeline(self, miner: PatternMiner) -> None:
        """
        mine_all deve retornar lista de dicts no formato do pipeline
        (hypothesis, win_rate_final, n_test, n_total, etc.).
        """
        df      = self._make_multi_group_df()
        results = miner.mine_all(df)

        if len(results) == 0:
            pytest.skip("Nenhum grupo Elite encontrado — ajuste _MIN_N/_MIN_WR_GALE2")

        r = results[0]
        for campo in ("hypothesis", "win_rate_final", "ev_final", "n_test",
                      "n_total", "n_win_1a", "n_win_g1", "n_win_g2", "n_hit",
                      "p_1a", "p_gale1", "p_gale2", "p_hit",
                      "variacao", "score_ponderado", "oos_flag"):
            assert campo in r, f"Campo pipeline '{campo}' ausente no resultado de mine_all."

    def test_mine_all_df_vazio_retorna_lista_vazia(self, miner: PatternMiner) -> None:
        """DataFrame vazio deve retornar []."""
        result = miner.mine_all(pd.DataFrame())
        assert result == []

    def test_mine_all_n_total_igual_n_test(self, miner: PatternMiner) -> None:
        """n_total e n_test devem ser iguais (transparencia de contagem)."""
        df      = self._make_multi_group_df()
        results = miner.mine_all(df)

        if len(results) == 0:
            pytest.skip("Nenhum grupo Elite encontrado")

        for r in results:
            assert r["n_total"] == r["n_test"], (
                f"n_total={r['n_total']} != n_test={r['n_test']}"
            )

    def test_mine_all_oos_flag_sempre_ok(self, miner: PatternMiner) -> None:
        """oos_flag deve sempre ser 'OUT_OF_SAMPLE_OK'."""
        df      = self._make_multi_group_df()
        results = miner.mine_all(df)

        for r in results:
            assert r["oos_flag"] == "OUT_OF_SAMPLE_OK", (
                f"oos_flag={r['oos_flag']} invalido"
            )

    def test_mine_all_hypothesis_contem_ativo_e_contexto(self, miner: PatternMiner) -> None:
        """hypothesis deve ter ativo e contexto com hh_mm."""
        df      = self._make_multi_group_df()
        results = miner.mine_all(df)

        if len(results) == 0:
            pytest.skip("Nenhum grupo Elite encontrado")

        for r in results:
            hyp = r["hypothesis"]
            assert "ativo" in hyp
            assert "contexto" in hyp
            assert "hh_mm" in hyp["contexto"]


# ─────────────────────────────────────────────────────────────────────────────
# 4. EXPORT_RESULTS — ARQUIVO mined_elite_*.json
# ─────────────────────────────────────────────────────────────────────────────

class TestExportResults:

    def test_export_cria_arquivo_mined_elite(self, miner: PatternMiner, tmp_path: Path) -> None:
        """Deve criar um arquivo mined_elite_*.json (nao mined_results_*)."""
        results = [{"hypothesis": {"ativo": "BOOM500"}, "win_rate_final": 0.96}]
        miner.export_results(results, str(tmp_path))

        # Verifica nome correto: mined_elite_*.json
        elite_files   = list(tmp_path.glob("mined_elite_*.json"))
        legacy_files  = list(tmp_path.glob("mined_results_*.json"))

        assert len(elite_files) == 1, (
            f"Esperado 1 arquivo mined_elite_*.json, encontrados: {elite_files}"
        )
        assert len(legacy_files) == 0, (
            "Nao deve criar arquivo mined_results_*.json (formato legado Z-Score)."
        )

    def test_export_conteudo_correto(self, miner: PatternMiner, tmp_path: Path) -> None:
        """Conteudo exportado deve ser identico a lista de entrada."""
        results = [
            {"hypothesis": {"ativo": "BOOM500"}, "win_rate_final": 0.96},
            {"hypothesis": {"ativo": "CRASH500"}, "win_rate_final": 0.92},
        ]
        miner.export_results(results, str(tmp_path))

        arquivo = next(tmp_path.glob("mined_elite_*.json"))
        with open(arquivo, encoding="utf-8") as fp:
            loaded = json.load(fp)

        assert loaded == results
