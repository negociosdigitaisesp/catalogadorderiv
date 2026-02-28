"""
agente/tests/test_strategy_writer.py
=======================================
Testes automatizados para StrategyWriter — Grade Horaria de Elite

Cenarios obrigatorios (PRD):
  1. generate_strategy_id segue formato T{HHMM}_{DIA}_{ATIVO}_G2
  2. build_config_entry contem todos os campos obrigatorios do novo schema
  3. update_config_json usa secao 'grade_horaria' (nao 'estrategias')
  4. update_config_json faz upsert (nao duplica)
  5. update_config_json remove entradas Z-Score antigas (sem hh_mm)
  6. write_strategy_report contem campos do novo schema de Grade Horaria
  7. write_all retorna resumo correto com AsyncMock do Supabase
"""

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from agente.core.strategy_writer import StrategyWriter, _90_DIAS_SEGUNDOS


# ─────────────────────────────────────────────────────────────────────────────
# FIXTURES E HELPERS
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def writer() -> StrategyWriter:
    return StrategyWriter()


def _make_validated_result(
    status: str = "APROVADO",
    ativo: str = "BOOM500",
    hh_mm: str = "14:30",
    dia_semana: int = 0,    # 0 = SEG
    direcao: str = "CALL",
    wr_gale2: float = 0.96,
    score: float = 0.93,
    ev_gale2: float = 0.55,
    n_total: int = 100,
    n_1a: int = 75,
    n_g1: int = 15,
    n_g2: int = 6,
    n_hit: int = 4,
    stake: float = 1.0,
    kelly_quarter: float = 0.25,
) -> dict:
    """Constroi validated_result compativel com StrategyWriter.build_config_entry()."""
    return {
        "status":           status,
        "stake_multiplier": stake,
        "kelly_quarter":    kelly_quarter,
        "win_1a_rate":      n_1a / n_total,
        "win_gale1_rate":   n_g1 / n_total,
        "win_gale2_rate":   n_g2 / n_total,
        "hit_rate":         n_hit / n_total,
        "ev_gale2":         ev_gale2,
        "sharpe":           0.0,
        "p_value":          1.0 - n_hit / n_total,
        "criterios_aprovados": 3 if status == "APROVADO" else 2 if status == "CONDICIONAL" else 0,
        "mined_result": {
            "hypothesis": {
                "ativo":    ativo,
                "contexto": {"hh_mm": hh_mm, "dia_semana": dia_semana},
                "direcao":  direcao,
            },
            "win_rate_final":  wr_gale2,
            "ev_final":        ev_gale2,
            "n_test":          n_total,
            "score_ponderado": score,
            "p_1a":            n_1a / n_total,
            "p_gale1":         n_g1 / n_total,
            "p_gale2":         n_g2 / n_total,
            "p_hit":           n_hit / n_total,
            "variacao":        "V1",
            "n_total":         n_total,
            "n_win_1a":        n_1a,
            "n_win_g1":        n_g1,
            "n_win_g2":        n_g2,
            "n_hit":           n_hit,
        },
    }


def _make_supabase_mock() -> MagicMock:
    """Cria mock do cliente Supabase com suporte a method chaining."""
    mock_sb = MagicMock()
    mock_sb.table.return_value.upsert.return_value.execute.return_value = {
        "data": [], "error": None
    }
    return mock_sb


# ─────────────────────────────────────────────────────────────────────────────
# 1. GENERATE_STRATEGY_ID — FORMATO T{HHMM}_{DIA}_{ATIVO}_G2
# ─────────────────────────────────────────────────────────────────────────────

class TestGenerateStrategyId:

    def test_formato_seg_boom500(self, writer: StrategyWriter) -> None:
        """hh_mm='14:30', dia_semana=0 (SEG), ativo='BOOM500' -> 'T1430_SEG_BOOM500_G2'."""
        sid = writer.generate_strategy_id("BOOM500", {"hh_mm": "14:30", "dia_semana": 0})
        assert sid == "T1430_SEG_BOOM500_G2", f"ID incorreto: {sid!r}"

    def test_formato_sex_r75(self, writer: StrategyWriter) -> None:
        """hh_mm='09:05', dia_semana=4 (SEX), ativo='R_75' -> 'T0905_SEX_R75_G2'."""
        sid = writer.generate_strategy_id("R_75", {"hh_mm": "09:05", "dia_semana": 4})
        assert sid == "T0905_SEX_R75_G2", f"ID incorreto: {sid!r}"

    def test_termina_sempre_em_g2(self, writer: StrategyWriter) -> None:
        """Todos os IDs devem terminar com '_G2'."""
        for ativo, hh_mm, dia in [("CRASH500", "10:00", 1), ("R_100", "22:30", 6)]:
            sid = writer.generate_strategy_id(ativo, {"hh_mm": hh_mm, "dia_semana": dia})
            assert sid.endswith("_G2"), f"ID {sid!r} nao termina em '_G2'"

    def test_ids_diferentes_para_contextos_diferentes(self, writer: StrategyWriter) -> None:
        """Dois contextos distintos devem gerar IDs diferentes."""
        sid1 = writer.generate_strategy_id("R_10", {"hh_mm": "10:00", "dia_semana": 0})
        sid2 = writer.generate_strategy_id("R_10", {"hh_mm": "20:00", "dia_semana": 3})
        assert sid1 != sid2, f"IDs iguais para contextos distintos: {sid1!r}"

    def test_ativo_com_underscore_removido(self, writer: StrategyWriter) -> None:
        """Ativo 'R_50' deve virar 'R50' no ID (sem underscore)."""
        sid = writer.generate_strategy_id("R_50", {"hh_mm": "13:00", "dia_semana": 2})
        assert "R50" in sid, f"'R50' nao encontrado em {sid!r}"
        assert "R_50" not in sid, f"'R_50' (com underscore) nao deve aparecer em {sid!r}"


# ─────────────────────────────────────────────────────────────────────────────
# 2. BUILD_CONFIG_ENTRY — SCHEMA COMPLETO
# ─────────────────────────────────────────────────────────────────────────────

class TestBuildConfigEntry:

    _CAMPOS_OBRIGATORIOS = [
        "strategy_id", "ativo", "hh_mm", "dia_semana", "dia_nome",
        "direcao", "win_rate_g2", "score_30_7", "ev_gale2", "max_gale",
        "status", "stake", "kelly_quarter",
        "win_1a_rate", "win_gale1_rate", "win_gale2_rate", "hit_rate",
        "n_total", "n_win_1a", "n_win_g1", "n_win_g2", "n_hit",
        "variacao", "descoberta_em", "valid_until",
    ]

    def test_schema_completo(self, writer: StrategyWriter, tmp_path: Path) -> None:
        """Todos os campos obrigatorios do Grade Horaria devem estar presentes."""
        validated = _make_validated_result()
        entry = writer.build_config_entry(validated, str(tmp_path / "config.json"))

        for campo in self._CAMPOS_OBRIGATORIOS:
            assert campo in entry, f"Campo obrigatorio '{campo}' ausente na entrada."

    def test_strategy_id_formato_correto(self, writer: StrategyWriter, tmp_path: Path) -> None:
        """strategy_id deve seguir o formato T{HHMM}_{DIA}_{ATIVO}_G2."""
        validated = _make_validated_result(ativo="BOOM500", hh_mm="14:30", dia_semana=0)
        entry = writer.build_config_entry(validated, str(tmp_path / "config.json"))

        assert entry["strategy_id"] == "T1430_SEG_BOOM500_G2", (
            f"strategy_id incorreto: {entry['strategy_id']!r}"
        )

    def test_valid_until_90_dias(self, writer: StrategyWriter, tmp_path: Path) -> None:
        """valid_until deve ser exatamente descoberta_em + 90 dias em segundos."""
        validated = _make_validated_result()
        entry = writer.build_config_entry(validated, str(tmp_path / "config.json"))

        diff = entry["valid_until"] - entry["descoberta_em"]
        assert diff == _90_DIAS_SEGUNDOS, (
            f"Diferenca={diff}s != {_90_DIAS_SEGUNDOS}s (90 dias)"
        )

    def test_contagens_reais_preservadas(self, writer: StrategyWriter, tmp_path: Path) -> None:
        """n_total, n_win_1a, n_win_g1, n_win_g2, n_hit devem refletir os valores reais."""
        validated = _make_validated_result(
            n_total=100, n_1a=75, n_g1=15, n_g2=6, n_hit=4
        )
        entry = writer.build_config_entry(validated, str(tmp_path / "config.json"))

        assert entry["n_total"]  == 100
        assert entry["n_win_1a"] == 75
        assert entry["n_win_g1"] == 15
        assert entry["n_win_g2"] == 6
        assert entry["n_hit"]    == 4

    def test_stake_condicional(self, writer: StrategyWriter, tmp_path: Path) -> None:
        """Estrategia CONDICIONAL deve ter stake = 0.5."""
        validated = _make_validated_result(status="CONDICIONAL", stake=0.5)
        entry = writer.build_config_entry(validated, str(tmp_path / "config.json"))
        assert entry["stake"] == pytest.approx(0.5)

    def test_stake_aprovado(self, writer: StrategyWriter, tmp_path: Path) -> None:
        """Estrategia APROVADO deve ter stake = 1.0."""
        validated = _make_validated_result(status="APROVADO", stake=1.0)
        entry = writer.build_config_entry(validated, str(tmp_path / "config.json"))
        assert entry["stake"] == pytest.approx(1.0)


# ─────────────────────────────────────────────────────────────────────────────
# 3 & 4. UPDATE_CONFIG_JSON — SECAO 'grade_horaria'
# ─────────────────────────────────────────────────────────────────────────────

class TestUpdateConfigJson:

    def _make_entry(self, strategy_id: str = "T1430_SEG_BOOM500_G2") -> dict:
        """Entrada minima compativel com update_config_json."""
        return {
            "strategy_id":   strategy_id,
            "ativo":         "BOOM500",
            "hh_mm":         "14:30",
            "dia_semana":    0,
            "dia_nome":      "SEG",
            "direcao":       "CALL",
            "win_rate_g2":   0.96,
            "score_30_7":    0.93,
            "ev_gale2":      0.55,
            "max_gale":      2,
            "status":        "APROVADO",
            "stake":         1.0,
            "kelly_quarter": 0.25,
            "win_1a_rate":   0.75,
            "win_gale1_rate": 0.15,
            "win_gale2_rate": 0.06,
            "hit_rate":      0.04,
            "n_total":       100,
            "n_win_1a":      75,
            "n_win_g1":      15,
            "n_win_g2":      6,
            "n_hit":         4,
            "variacao":      "V1",
            "descoberta_em": 1_770_000_000,
            "valid_until":   1_770_000_000 + _90_DIAS_SEGUNDOS,
        }

    def test_adiciona_em_grade_horaria(self, writer: StrategyWriter, tmp_path: Path) -> None:
        """Config vazio -> estrategia fica em 'grade_horaria', nao em 'estrategias'."""
        config_path = str(tmp_path / "config.json")
        entry = self._make_entry()
        writer.update_config_json(entry, config_path)

        with open(config_path, encoding="utf-8") as f:
            config = json.load(f)

        assert "grade_horaria" in config, "Chave 'grade_horaria' deve existir."
        assert "estrategias" not in config, "Chave legada 'estrategias' NAO deve existir."
        assert len(config["grade_horaria"]) == 1

    def test_upsert_nao_duplica(self, writer: StrategyWriter, tmp_path: Path) -> None:
        """Mesma strategy_id inserida duas vezes -> apenas 1 entrada no config."""
        config_path = str(tmp_path / "config.json")
        entry_v1 = {**self._make_entry(), "win_rate_g2": 0.94}
        entry_v2 = {**self._make_entry(), "win_rate_g2": 0.97}

        writer.update_config_json(entry_v1, config_path)
        writer.update_config_json(entry_v2, config_path)

        with open(config_path, encoding="utf-8") as f:
            config = json.load(f)

        grade = config.get("grade_horaria", [])
        assert len(grade) == 1, f"Deve ter 1 entrada, encontrou {len(grade)}"
        assert abs(grade[0]["win_rate_g2"] - 0.97) < 1e-6, "Upsert deve manter valor recente."

    def test_multiplas_estrategias_distintas(self, writer: StrategyWriter, tmp_path: Path) -> None:
        """Dois strategy_ids distintos -> duas entradas no config.json."""
        config_path = str(tmp_path / "config.json")
        entry_a = self._make_entry("T1430_SEG_BOOM500_G2")
        entry_b = {**self._make_entry("T1000_TER_CRASH500_G2"), "ativo": "CRASH500"}

        writer.update_config_json(entry_a, config_path)
        writer.update_config_json(entry_b, config_path)

        with open(config_path, encoding="utf-8") as f:
            config = json.load(f)

        assert len(config.get("grade_horaria", [])) == 2

    def test_limpa_entradas_zscore_antigas(self, writer: StrategyWriter, tmp_path: Path) -> None:
        """
        Entradas Z-Score antigas (sem 'hh_mm') devem ser removidas automaticamente.
        """
        config_path = str(tmp_path / "config.json")

        # Pre-carrega config com uma entrada Z-Score (sem hh_mm)
        config_inicial = {
            "grade_horaria": [
                {"strategy_id": "S1_BOOM500_ABC123", "ativo": "BOOM500",
                 "p_win": 0.70, "ev": 0.295}  # sem hh_mm -> sera removida
            ]
        }
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config_inicial, f)

        # Adiciona entrada nova (com hh_mm)
        entry = self._make_entry()
        writer.update_config_json(entry, config_path)

        with open(config_path, encoding="utf-8") as f:
            config = json.load(f)

        grade = config.get("grade_horaria", [])
        # Apenas a nova entrada (com hh_mm) deve permanecer
        assert len(grade) == 1
        assert grade[0]["strategy_id"] == entry["strategy_id"], (
            "Entrada Z-Score antiga deveria ter sido removida."
        )


# ─────────────────────────────────────────────────────────────────────────────
# 5. WRITE_STRATEGY_REPORT — NOVO SCHEMA
# ─────────────────────────────────────────────────────────────────────────────

class TestWriteStrategyReport:

    def test_campos_obrigatorios_no_relatorio(
        self, writer: StrategyWriter, tmp_path: Path
    ) -> None:
        """Relatorio deve conter campos do schema de Grade Horaria."""
        validated   = _make_validated_result()
        report_path = str(tmp_path / "reports")
        filepath    = writer.write_strategy_report(validated, report_path)

        assert Path(filepath).exists(), "Arquivo de relatorio nao foi criado."

        content = Path(filepath).read_text(encoding="utf-8")

        # Campos obrigatorios do novo schema
        assert "GRADE HORARIA" in content,   "Secao 'GRADE HORARIA' ausente."
        assert "Win de 1a"     in content,   "Campo 'Win de 1a' ausente."
        assert "Win Rate G2"   in content,   "Campo 'Win Rate G2' ausente."
        assert "EV Gale 2"     in content,   "Campo 'EV Gale 2' ausente."
        assert "Score 30/7"    in content,   "Campo 'Score 30/7' ausente."
        assert "Valida ate"    in content,   "Campo 'Valida ate' ausente."
        assert "Stake Base"    in content,   "Campo 'Stake Base' ausente."

    def test_arquivo_nomeado_com_strategy_id(
        self, writer: StrategyWriter, tmp_path: Path
    ) -> None:
        """Nome do arquivo deve ser report_{strategy_id}.txt."""
        validated   = _make_validated_result()
        report_path = str(tmp_path / "reports")
        filepath    = writer.write_strategy_report(validated, report_path)

        nome = Path(filepath).name
        assert nome.startswith("report_"), f"Nome incorreto: {nome}"
        assert nome.endswith(".txt"),       f"Extensao incorreta: {nome}"
        assert "T1430_SEG_BOOM500_G2" in nome, (
            f"strategy_id 'T1430_SEG_BOOM500_G2' ausente no nome: {nome}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# 6. WRITE_ALL (async)
# ─────────────────────────────────────────────────────────────────────────────

class TestWriteAll:

    @pytest.mark.asyncio
    async def test_write_all_retorna_resumo_correto(
        self, writer: StrategyWriter, tmp_path: Path
    ) -> None:
        """Batch com 2 aprovadas e 1 condicional -> escritas=3, aprovadas=2, condicionais=1."""
        mock_sb = _make_supabase_mock()

        validated_batch = {
            "aprovados": [
                _make_validated_result(status="APROVADO", ativo="BOOM500",
                                       hh_mm="14:30", dia_semana=0),
                _make_validated_result(status="APROVADO", ativo="CRASH500",
                                       hh_mm="10:00", dia_semana=2),
            ],
            "condicionais": [
                _make_validated_result(status="CONDICIONAL", ativo="R_10",
                                       hh_mm="18:00", dia_semana=4, stake=0.5),
            ],
            "reprovados": [],
        }

        config_path = str(tmp_path / "config.json")
        report_path = str(tmp_path / "reports")

        resultado = await writer.write_all(validated_batch, mock_sb, config_path, report_path)

        assert resultado["estrategias_escritas"] == 3
        assert resultado["aprovadas"]            == 2
        assert resultado["condicionais"]         == 1
        assert resultado["config_atualizado"]    is True
        assert resultado["supabase_notificado"]  is True
        assert len(resultado["reports_gerados"]) == 3

    @pytest.mark.asyncio
    async def test_write_all_batch_vazio(
        self, writer: StrategyWriter, tmp_path: Path
    ) -> None:
        """Batch sem aprovados nem condicionais -> escritas=0."""
        mock_sb = _make_supabase_mock()
        validated_batch = {"aprovados": [], "condicionais": [], "reprovados": []}

        resultado = await writer.write_all(
            validated_batch, mock_sb,
            str(tmp_path / "config.json"),
            str(tmp_path / "reports"),
        )

        assert resultado["estrategias_escritas"] == 0
        assert resultado["config_atualizado"]    is False
        assert resultado["supabase_notificado"]  is False

    @pytest.mark.asyncio
    async def test_write_all_chama_supabase_uma_vez(
        self, writer: StrategyWriter, tmp_path: Path
    ) -> None:
        """O cliente Supabase deve ser chamado exatamente uma vez por estrategia."""
        mock_sb = _make_supabase_mock()
        validated_batch = {
            "aprovados": [_make_validated_result(status="APROVADO")],
            "condicionais": [],
            "reprovados": [],
        }

        await writer.write_all(
            validated_batch, mock_sb,
            str(tmp_path / "config.json"),
            str(tmp_path / "reports"),
        )

        assert mock_sb.table.call_count == 1, (
            f"table() foi chamado {mock_sb.table.call_count}x, esperado 1."
        )
