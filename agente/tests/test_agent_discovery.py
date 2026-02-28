"""
agente/tests/test_agent_discovery.py
===========================================
Testes automatizados para DataLoader v2 + AgentDiscovery

Schema v2 "Ciclo de Horario":
  timestamp, ativo, hh_mm, hora_utc, dia_semana,
  cor_atual, mhi_seq, proxima_1, proxima_2, proxima_3,
  tendencia_m5, tendencia_m15, open, high, low, close

Cenarios obrigatorios (PRD):
  1. check_catalog_freshness detecta catalog fresco
  2. check_catalog_freshness detecta catalog desatualizado
  3. parse_candles_to_catalog: hh_mm tem formato correto (HH:MM)
  4. parse_candles_to_catalog: cor_atual = VERDE quando close > open
  5. parse_candles_to_catalog: cor_atual = VERMELHA quando close <= open
  6. parse_candles_to_catalog: ultima vela tem proxima_1 = '?'
  7. save_to_catalog nao duplica por INSERT OR IGNORE
  8. run_cycle chama todos os 5 modulos em ordem (fluxo completo mockado)
  9. run_cycle com 0 aprovadas termina sem erro e retorna estrategias_escritas=0
"""

import sqlite3
from pathlib import Path
from time import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from agente.core.data_loader import DataLoader, _CREATE_TABLE_SQL
from agente.core.agent_discovery import AgentDiscovery


# ─────────────────────────────────────────────────────────────────────────────
# FIXTURES E HELPERS
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def loader() -> DataLoader:
    return DataLoader()


def _create_catalog_db(db_path: str, timestamp: int, n: int = 1) -> None:
    """Cria um catalog.db minimo com n registros no schema v2."""
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute(_CREATE_TABLE_SQL)
        for i in range(n):
            conn.execute(
                """
                INSERT OR IGNORE INTO candles
                (timestamp, ativo, hh_mm, hora_utc, dia_semana,
                 cor_atual, mhi_seq, proxima_1, proxima_2, proxima_3,
                 tendencia_m5, tendencia_m15, open, high, low, close)
                VALUES (?, 'TEST', '10:00', 10, 0,
                        'VERDE', 'V-V-V', 'VERDE', 'VERDE', 'VERDE',
                        'ALTA', 'ALTA', 1.0, 1.1, 0.9, 1.05)
                """,
                (timestamp + i,),
            )


def _make_raw_candles(n: int = 25, base_epoch: int = 1_700_000_000) -> list[dict]:
    """Cria lista de candles raw simulando resposta da Deriv API."""
    candles = []
    for i in range(n):
        open_p  = 100.0 + i * 0.5
        close_p = open_p + (0.10 if i % 3 != 0 else -0.20)
        candles.append({
            "epoch": base_epoch + i * 60,
            "open":  open_p,
            "high":  open_p + 0.30,
            "low":   open_p - 0.15,
            "close": close_p,
        })
    return candles


def _make_fake_df(n: int = 1000):
    """Cria DataFrame fake com schema v2 para mockar o DataLoader."""
    import pandas as pd
    rows = []
    for i in range(n):
        rows.append({
            "timestamp":    1_700_000_000 + i * 60,
            "ativo":        "BOOM500",
            "hh_mm":        f"{(i // 60) % 24:02d}:{i % 60:02d}",
            "hora_utc":     (i // 60) % 24,
            "dia_semana":   (i // 1440) % 7,
            "cor_atual":    "VERDE" if i % 3 != 0 else "VERMELHA",
            "mhi_seq":      "V-V-V" if i >= 3 else "?-?-?",
            "proxima_1":    "VERDE",
            "proxima_2":    "VERDE",
            "proxima_3":    "VERDE",
            "tendencia_m5":  "ALTA",
            "tendencia_m15": "ALTA",
            "open":  100.0,
            "high":  101.0,
            "low":    99.0,
            "close": 100.5,
        })
    return pd.DataFrame(rows)


# ─────────────────────────────────────────────────────────────────────────────
# 1 & 2. CHECK_CATALOG_FRESHNESS
# ─────────────────────────────────────────────────────────────────────────────

class TestCheckCatalogFreshness:

    def test_fresco(self, loader: DataLoader, tmp_path: Path) -> None:
        """Timestamp = agora -> deve retornar True (fresco)."""
        db_path   = str(tmp_path / "catalog.db")
        now_epoch = int(time())
        _create_catalog_db(db_path, now_epoch)

        result = loader.check_catalog_freshness(db_path, max_age_hours=24)
        assert result is True, "Catalog com dados de agora deveria ser fresco."

    def test_desatualizado(self, loader: DataLoader, tmp_path: Path) -> None:
        """Timestamp = 48h atras -> deve retornar False."""
        db_path         = str(tmp_path / "catalog.db")
        epoch_48h_atras = int(time()) - (48 * 3600)
        _create_catalog_db(db_path, epoch_48h_atras)

        result = loader.check_catalog_freshness(db_path, max_age_hours=24)
        assert result is False, "Catalog com 48h de idade deveria estar desatualizado."

    def test_db_inexistente_retorna_false(self, loader: DataLoader, tmp_path: Path) -> None:
        """DB nao existe -> deve retornar False."""
        result = loader.check_catalog_freshness(str(tmp_path / "nao_existe.db"))
        assert result is False

    def test_db_vazio_retorna_false(self, loader: DataLoader, tmp_path: Path) -> None:
        """DB vazio (sem registros) -> deve retornar False."""
        db_path = str(tmp_path / "catalog.db")
        with sqlite3.connect(db_path) as conn:
            conn.execute(_CREATE_TABLE_SQL)

        result = loader.check_catalog_freshness(db_path)
        assert result is False, "Catalog vazio deveria retornar False."


# ─────────────────────────────────────────────────────────────────────────────
# 3-6. PARSE_CANDLES_TO_CATALOG — SCHEMA v2
# ─────────────────────────────────────────────────────────────────────────────

class TestParseCandles:

    def test_hh_mm_formato_correto(self, loader: DataLoader) -> None:
        """
        Candle com epoch = 10:00 UTC (36000 sec) -> hh_mm deve ser '10:00'.
        """
        candles = [{
            "epoch": 36000,
            "open": 100.0, "high": 100.5, "low": 99.8, "close": 100.3,
        }]
        registros = loader.parse_candles_to_catalog(candles, "R_10")
        assert len(registros) == 1
        assert registros[0]["hh_mm"] == "10:00", (
            f"hh_mm={registros[0]['hh_mm']!r} para epoch 36000 (10:00 UTC) deve ser '10:00'"
        )

    def test_cor_atual_verde_close_maior_open(self, loader: DataLoader) -> None:
        """close > open -> cor_atual = 'VERDE'."""
        candles = [{"epoch": 36000, "open": 100.0, "high": 101.0, "low": 99.5, "close": 100.8}]
        registros = loader.parse_candles_to_catalog(candles, "R_25")
        assert registros[0]["cor_atual"] == "VERDE", (
            f"close>open deveria ser 'VERDE', foi '{registros[0]['cor_atual']}'"
        )

    def test_cor_atual_vermelha_close_menor_open(self, loader: DataLoader) -> None:
        """close <= open -> cor_atual = 'VERMELHA'."""
        candles = [{"epoch": 36000, "open": 100.0, "high": 100.5, "low": 99.0, "close": 99.5}]
        registros = loader.parse_candles_to_catalog(candles, "R_25")
        assert registros[0]["cor_atual"] == "VERMELHA"

    def test_proxima_1_ultima_vela_e_interrogacao(self, loader: DataLoader) -> None:
        """A ultima vela nao tem proxima_1 disponivel -> deve ser '?'."""
        candles = [
            {"epoch": 36000 + i * 60, "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5}
            for i in range(5)
        ]
        registros = loader.parse_candles_to_catalog(candles, "BOOM500")
        assert registros[-1]["proxima_1"] == "?", (
            "Ultima vela nao tem proxima_1 -> deve ser '?'"
        )

    def test_proxima_3_ultimas_tres_velas_sao_interrogacao(self, loader: DataLoader) -> None:
        """As ultimas 3 velas devem ter proxima_3 = '?'."""
        candles = [
            {"epoch": 36000 + i * 60, "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5}
            for i in range(5)
        ]
        registros = loader.parse_candles_to_catalog(candles, "BOOM500")
        assert registros[-1]["proxima_3"] == "?"
        assert registros[-2]["proxima_3"] == "?"
        assert registros[-3]["proxima_3"] == "?"

    def test_lista_vazia_retorna_lista_vazia(self, loader: DataLoader) -> None:
        """Sem candles -> retorna lista vazia."""
        assert loader.parse_candles_to_catalog([], "R_10") == []


# ─────────────────────────────────────────────────────────────────────────────
# 7. SAVE_TO_CATALOG (INSERT OR IGNORE)
# ─────────────────────────────────────────────────────────────────────────────

class TestSaveToCatalog:

    def test_sem_duplicatas(self, loader: DataLoader, tmp_path: Path) -> None:
        """
        100 registros inseridos -> mesmos 100 inseridos novamente
        -> banco deve ter APENAS 100 registros (INSERT OR IGNORE).
        """
        db_path  = str(tmp_path / "catalog.db")
        raw      = _make_raw_candles(n=100)
        parsed   = loader.parse_candles_to_catalog(raw, "BOOM500")

        n1 = loader.save_to_catalog(parsed, db_path)
        n2 = loader.save_to_catalog(parsed, db_path)  # duplicata

        with sqlite3.connect(db_path) as conn:
            count = conn.execute("SELECT COUNT(*) FROM candles").fetchone()[0]

        assert count == 100, f"Banco deveria ter 100 registros, tem {count}"
        assert n1 == 100,    f"Primeira insercao deveria retornar 100, retornou {n1}"
        assert n2 == 0,      f"Segunda insercao (duplicata) deveria retornar 0, retornou {n2}"

    def test_registros_vazios_retorna_zero(self, loader: DataLoader, tmp_path: Path) -> None:
        """Lista vazia -> retorna 0 insercoes."""
        n = loader.save_to_catalog([], str(tmp_path / "catalog.db"))
        assert n == 0


# ─────────────────────────────────────────────────────────────────────────────
# 8 & 9. RUN_CYCLE (Integracao com mocks)
# ─────────────────────────────────────────────────────────────────────────────

class TestRunCycle:

    def _make_agent_with_mocks(self, tmp_path: Path) -> tuple[AgentDiscovery, dict]:
        """Cria AgentDiscovery com todos os modulos mockados."""
        agent = AgentDiscovery(
            config_path=str(tmp_path / "config.json"),
            db_path=str(tmp_path / "catalog" / "catalog.db"),
            app_id="test_app_id",
            supabase_url="",
            supabase_key="",
        )
        mocks: dict = {}

        # DataLoader mock
        mock_loader = MagicMock(spec=DataLoader)
        mock_loader.load_or_fetch = AsyncMock(return_value=_make_fake_df(1000))
        agent.loader = mock_loader
        mocks["loader"] = mock_loader

        # HypothesisGenerator mock
        mock_gen  = MagicMock()
        mock_hyps = [{
            "ativo":             "BOOM500",
            "contexto":          {"hh_mm": "13:00", "dia_semana": 0},
            "direcao":           "CALL",
            "p_win_condicional": 0.96,
            "prioridade":        1.0,
            "n_amostras":        200,
            "p_win_global":      0.96,
            "edge_bruto":        0.42,
        }]
        mock_gen.generate_hypotheses.return_value = mock_hyps
        agent.generator = mock_gen
        mocks["generator"] = mock_gen

        # PatternMiner mock — formato adaptado para pipeline v2
        mock_miner = MagicMock()
        mock_mined = [{
            "hypothesis":      mock_hyps[0],
            "win_rate_final":  0.96,
            "ev_final":        0.55,
            "edge_final":      0.42,
            "n_test":          200,
            "n_total":         200,
            "score_ponderado": 0.93,
            "p_1a":            0.75,
            "p_gale1":         0.15,
            "p_gale2":         0.06,
            "p_hit":           0.04,
            "oos_flag":        "OUT_OF_SAMPLE_OK",
            "variacao":        "V1",
            "n_win_1a":        150,
            "n_win_g1":        30,
            "n_win_g2":        12,
            "n_hit":           8,
        }]
        mock_miner.mine_all.return_value = mock_mined
        agent.miner = mock_miner
        mocks["miner"] = mock_miner

        return agent, mocks

    @pytest.mark.asyncio
    async def test_run_cycle_fluxo_completo(self, tmp_path: Path) -> None:
        """
        Mocka todos os 5 modulos.
        Garante que run_cycle os chama em ordem e retorna resumo completo.
        """
        agent, mocks = self._make_agent_with_mocks(tmp_path)

        from agente.core.strategy_validator import StrategyValidator
        from agente.core.strategy_writer import StrategyWriter

        # Validator mock — nova API: apenas aprovados/condicionais/reprovados
        mock_validator = MagicMock(spec=StrategyValidator)
        mock_validator.validate_batch.return_value = {
            "aprovados": [{
                "status":            "APROVADO",
                "stake_multiplier":  1.0,
                "kelly_quarter":     0.25,
                "win_1a_rate":       0.75,
                "win_gale1_rate":    0.15,
                "win_gale2_rate":    0.06,
                "hit_rate":          0.04,
                "ev_gale2":          0.55,
                "sharpe":            0.0,
                "p_value":           0.96,
                "criterios_aprovados": 3,
                "motivo":            "Aprovado por recorrencia alta",
                "mined_result":      mocks["miner"].mine_all.return_value[0],
            }],
            "condicionais": [],
            "reprovados":   [],
        }
        agent.validator = mock_validator

        # Writer mock
        mock_writer = MagicMock(spec=StrategyWriter)
        mock_writer.write_all = AsyncMock(return_value={
            "estrategias_escritas": 1,
            "aprovadas":            1,
            "condicionais":         0,
            "config_atualizado":    True,
            "supabase_notificado":  False,
            "reports_gerados":      ["catalog/reports/report_T1300_SEG_BOOM500_G2.txt"],
        })
        agent.writer = mock_writer

        result = await agent.run_cycle(ativos=["BOOM500"])

        # Todos os 5 modulos chamados
        mocks["loader"].load_or_fetch.assert_called_once()
        mocks["generator"].generate_hypotheses.assert_called_once()
        mocks["miner"].mine_all.assert_called_once()
        mock_validator.validate_batch.assert_called_once()
        mock_writer.write_all.assert_called_once()

        # Estrutura do resultado
        campos = [
            "registros_carregados", "hipoteses_geradas", "padroes_minerados",
            "aprovadas", "condicionais", "reprovadas", "estrategias_escritas",
            "config_atualizado", "supabase_notificado", "duracao_segundos",
        ]
        for campo in campos:
            assert campo in result, f"Campo '{campo}' ausente no resultado do ciclo."

        assert result["registros_carregados"] == 1000
        assert result["hipoteses_geradas"]    == 1
        assert result["padroes_minerados"]    == 1
        assert result["aprovadas"]            == 1
        assert result["estrategias_escritas"] == 1

    @pytest.mark.asyncio
    async def test_run_cycle_sem_aprovadas(self, tmp_path: Path) -> None:
        """
        Validator retorna 0 aprovadas -> agente termina sem erro
        e estrategias_escritas = 0.
        """
        agent, mocks = self._make_agent_with_mocks(tmp_path)

        from agente.core.strategy_validator import StrategyValidator
        mock_validator = MagicMock(spec=StrategyValidator)
        mock_validator.validate_batch.return_value = {
            "aprovados":    [],
            "condicionais": [],
            "reprovados":   [{"status": "REPROVADO"}],
        }
        agent.validator = mock_validator

        from agente.core.strategy_writer import StrategyWriter
        mock_writer = MagicMock(spec=StrategyWriter)
        mock_writer.write_all = AsyncMock(return_value={
            "estrategias_escritas": 0,
            "aprovadas":            0,
            "condicionais":         0,
            "config_atualizado":    False,
            "supabase_notificado":  False,
            "reports_gerados":      [],
        })
        agent.writer = mock_writer

        result = await agent.run_cycle(ativos=["BOOM500"])

        assert result["estrategias_escritas"] == 0, (
            f"Sem aprovadas -> escritas deve ser 0, foi {result['estrategias_escritas']}"
        )
        assert result["aprovadas"]    == 0
        assert result["condicionais"] == 0
