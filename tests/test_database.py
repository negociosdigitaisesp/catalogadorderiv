"""
tests/test_database.py — Testes da camada de persistência (Fase 3)

Cobertura:
  LocalCatalogManager (SQLite):
    - Inserção com os 10 campos obrigatórios do PRD Seção 7
    - Validação de campos obrigatórios ausentes
    - Recuperação por ativo (fetch_by_ativo)
    - Contagem de amostras para LGN (count_by_context, PRD Pilar 3)
    - Resultados "A" e "B" (PRD Seção 7)
    - Evento macro como booleano

  SupabaseManager (mocked — sem conexão real):
    - _build_signal_data: formato exato da tabela catalogo_estrategias (PRD Seção 6)
    - Campo contexto JSONB: z_score_atual, ev_calculado, kelly_sizing, n_amostral
    - save_signal: chama INSERT com dicionário correto
    - update_signal_status: chama UPDATE com id e status corretos
    - Retorno None quando Supabase retorna lista vazia

  Integração Sniper + DB:
    - _persist_signal PRE_SIGNAL → save_signal chamado
    - _persist_signal CONFIRMED → update_signal_status chamado com o ID do PRE
    - _persist_signal falha silenciosa (exceção não propaga)
    - _signal_ids é limpo após CONFIRMED
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
import aiosqlite

from core.database import SupabaseManager, LocalCatalogManager
from core.vps_sniper import DerivSniper

# ─────────────────────────────────────────────────────────────────────────────
# DADOS DE REFERÊNCIA
# ─────────────────────────────────────────────────────────────────────────────

# Candle com os 10 campos exatos do PRD Seção 7
SAMPLE_CANDLE = {
    "timestamp":               1_700_000_000,
    "ativo":                   "R_100",
    "sessao":                  "London",
    "contexto_temporal":       "Segunda-feira/meio_do_mes",
    "contexto_comportamental": "Expansao",
    "sequencia_recente":       3,
    "resultado":               "A",
    "magnitude":               "Dentro_do_range",
    "evento_macro":            False,
    "observacao":              "",
}

# Payload gerado por _process_tick_sync (estrutura real do Sniper)
SAMPLE_PAYLOAD = {
    "symbol":        "R_100",
    "z_score":       2.8234,
    "direction":     "PUT",
    "epoch":         1_700_000_030,
    "segundo":       50,
    "p_win":         0.64,
    "ev":            0.184,
    "kelly_quarter": 0.015,
    "n_amostral":    347,
}

CONFIG = {
    "R_100": {
        "estrategia":         "Z_SCORE_M1",
        "z_score_min":        2.5,
        "p_win":              0.64,
        "ev":                 0.184,
        "kelly_quarter":      0.015,
        "n_amostral":         347,
        "expiracao_segundos": 300,
    }
}

# Épocas de controle (BASE_EPOCH % 60 == 20)
BASE_EPOCH = 1_700_000_000
EPOCH_S50  = BASE_EPOCH + 30   # % 60 == 50
EPOCH_S0   = BASE_EPOCH + 40   # % 60 == 0
BASELINE_PRICES = [999.5 if i % 2 == 0 else 1000.5 for i in range(20)]
SPIKE_UP        = 1003.5


# ─────────────────────────────────────────────────────────────────────────────
# FIXTURES
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def temp_db(tmp_path) -> str:
    """Caminho para banco SQLite temporário — destruído após cada teste."""
    return str(tmp_path / "test_catalog.db")


@pytest.fixture
def local_mgr(temp_db) -> LocalCatalogManager:
    return LocalCatalogManager(db_path=temp_db)


@pytest.fixture
def supabase_mgr() -> SupabaseManager:
    """Manager com URL/key fictícias — cliente nunca será inicializado."""
    return SupabaseManager(url="https://test.supabase.co", key="test_key")


@pytest.fixture
def sniper_with_mock_db() -> tuple[DerivSniper, AsyncMock]:
    """Sniper + SupabaseManager mockado para testes de integração."""
    mock_db = AsyncMock(spec=SupabaseManager)
    mock_db.save_signal = AsyncMock(return_value=42)
    mock_db.update_signal_status = AsyncMock(return_value=True)
    sniper = DerivSniper(CONFIG, app_id="test_id", db=mock_db)
    for price in BASELINE_PRICES:
        sniper.deques["R_100"].append(price)
    return sniper, mock_db


# ─────────────────────────────────────────────────────────────────────────────
# BLOCO 1 — LocalCatalogManager: Inserção e Schema
# ─────────────────────────────────────────────────────────────────────────────

class TestLocalCatalogInsert:

    async def test_save_candle_returns_integer_id(self, local_mgr):
        """INSERT deve retornar um ID inteiro positivo."""
        record_id = await local_mgr.save_candle(SAMPLE_CANDLE)
        assert isinstance(record_id, int)
        assert record_id >= 1

    async def test_ids_auto_increment(self, local_mgr):
        """IDs devem incrementar a cada INSERT."""
        id1 = await local_mgr.save_candle(SAMPLE_CANDLE)
        id2 = await local_mgr.save_candle(SAMPLE_CANDLE)
        id3 = await local_mgr.save_candle(SAMPLE_CANDLE)
        assert id1 < id2 < id3

    async def test_all_10_fields_stored_correctly(self, local_mgr, temp_db):
        """Todos os 10 campos obrigatórios do PRD Seção 7 devem ser persistidos."""
        await local_mgr.save_candle(SAMPLE_CANDLE)

        async with aiosqlite.connect(temp_db) as conn:
            conn.row_factory = aiosqlite.Row
            cur = await conn.execute("SELECT * FROM catalogo_historico WHERE id = 1")
            row = dict(await cur.fetchone())

        assert row["timestamp"]               == 1_700_000_000
        assert row["ativo"]                   == "R_100"
        assert row["sessao"]                  == "London"
        assert row["contexto_temporal"]       == "Segunda-feira/meio_do_mes"
        assert row["contexto_comportamental"] == "Expansao"
        assert row["sequencia_recente"]       == 3
        assert row["resultado"]               == "A"
        assert row["magnitude"]               == "Dentro_do_range"
        assert row["evento_macro"]            == 0    # False → 0 no SQLite
        assert row["observacao"]              == ""

    async def test_resultado_a_stored(self, local_mgr):
        """Resultado 'A' (sobe) deve ser persistido — PRD Seção 7."""
        await local_mgr.save_candle({**SAMPLE_CANDLE, "resultado": "A"})
        rows = await local_mgr.fetch_by_ativo("R_100")
        assert rows[0]["resultado"] == "A"

    async def test_resultado_b_stored(self, local_mgr):
        """Resultado 'B' (cai) deve ser persistido — PRD Seção 7."""
        await local_mgr.save_candle({**SAMPLE_CANDLE, "resultado": "B"})
        rows = await local_mgr.fetch_by_ativo("R_100")
        assert rows[0]["resultado"] == "B"

    async def test_evento_macro_true_stored_as_1(self, local_mgr, temp_db):
        """evento_macro=True deve ser persistido como 1 no SQLite."""
        await local_mgr.save_candle({**SAMPLE_CANDLE, "evento_macro": True})

        async with aiosqlite.connect(temp_db) as conn:
            cur = await conn.execute(
                "SELECT evento_macro FROM catalogo_historico WHERE id = 1"
            )
            row = await cur.fetchone()
        assert row[0] == 1

    async def test_evento_macro_false_stored_as_0(self, local_mgr, temp_db):
        """evento_macro=False deve ser persistido como 0 no SQLite."""
        await local_mgr.save_candle({**SAMPLE_CANDLE, "evento_macro": False})

        async with aiosqlite.connect(temp_db) as conn:
            cur = await conn.execute(
                "SELECT evento_macro FROM catalogo_historico WHERE id = 1"
            )
            row = await cur.fetchone()
        assert row[0] == 0

    async def test_optional_fields_default_to_safe_values(self, local_mgr):
        """Campos opcionais ausentes devem usar defaults seguros, não levantar erro."""
        minimal = {
            "timestamp":               1_700_000_000,
            "ativo":                   "R_100",
            "sessao":                  "Asian",
            "contexto_temporal":       "Terca/inicio_do_mes",
            "contexto_comportamental": "Contracao",
        }
        record_id = await local_mgr.save_candle(minimal)
        assert record_id >= 1

        rows = await local_mgr.fetch_by_ativo("R_100")
        row = rows[0]
        assert row["sequencia_recente"] == 0
        assert row["resultado"] is None
        assert row["magnitude"] is None
        assert row["evento_macro"] == 0
        assert row["observacao"] == ""

    async def test_missing_required_field_raises_value_error(self, local_mgr):
        """Campos obrigatórios ausentes devem levantar ValueError com detalhes."""
        incomplete = {"ativo": "R_100", "sessao": "London"}
        with pytest.raises(ValueError, match="Campos obrigatorios ausentes"):
            await local_mgr.save_candle(incomplete)

    async def test_missing_timestamp_raises(self, local_mgr):
        """Sem 'timestamp' (campo 1 do PRD Seção 7) → ValueError."""
        data = {k: v for k, v in SAMPLE_CANDLE.items() if k != "timestamp"}
        with pytest.raises(ValueError):
            await local_mgr.save_candle(data)


# ─────────────────────────────────────────────────────────────────────────────
# BLOCO 2 — LocalCatalogManager: Queries e LGN
# ─────────────────────────────────────────────────────────────────────────────

class TestLocalCatalogQuery:

    async def test_fetch_by_ativo_returns_only_matching_asset(self, local_mgr):
        """fetch_by_ativo deve retornar apenas registros do ativo solicitado."""
        await local_mgr.save_candle(SAMPLE_CANDLE)
        await local_mgr.save_candle({**SAMPLE_CANDLE, "ativo": "CRASH_1000"})

        r100_rows = await local_mgr.fetch_by_ativo("R_100")
        assert len(r100_rows) == 1
        assert r100_rows[0]["ativo"] == "R_100"

    async def test_fetch_by_ativo_respects_limit(self, local_mgr):
        """fetch_by_ativo deve respeitar o parâmetro limit."""
        for _ in range(10):
            await local_mgr.save_candle(SAMPLE_CANDLE)

        rows = await local_mgr.fetch_by_ativo("R_100", limit=5)
        assert len(rows) == 5

    async def test_fetch_returns_most_recent_first(self, local_mgr):
        """Registros devem ser retornados do mais recente para o mais antigo."""
        await local_mgr.save_candle({**SAMPLE_CANDLE, "timestamp": 1_000})
        await local_mgr.save_candle({**SAMPLE_CANDLE, "timestamp": 2_000})
        await local_mgr.save_candle({**SAMPLE_CANDLE, "timestamp": 3_000})

        rows = await local_mgr.fetch_by_ativo("R_100")
        assert rows[0]["timestamp"] == 3_000
        assert rows[-1]["timestamp"] == 1_000

    async def test_count_by_context_returns_zero_for_empty_db(self, local_mgr):
        """Banco vazio deve retornar contagem 0."""
        n = await local_mgr.count_by_context("R_100", "London", "Expansao")
        assert n == 0

    async def test_count_by_context_counts_correctly(self, local_mgr):
        """count_by_context deve contar exatamente as amostras do contexto."""
        for _ in range(5):
            await local_mgr.save_candle({
                **SAMPLE_CANDLE,
                "sessao": "London",
                "contexto_comportamental": "Expansao",
            })
        for _ in range(3):
            await local_mgr.save_candle({
                **SAMPLE_CANDLE,
                "sessao": "NY",
                "contexto_comportamental": "Contracao",
            })

        n_london = await local_mgr.count_by_context("R_100", "London", "Expansao")
        n_ny     = await local_mgr.count_by_context("R_100", "NY", "Contracao")
        assert n_london == 5
        assert n_ny     == 3

    async def test_lgn_threshold_300_reached(self, local_mgr):
        """
        PRD Pilar 3: N >= 300 → edge confiável.
        Insere exatamente 300 registros e verifica a contagem.
        """
        for _ in range(300):
            await local_mgr.save_candle({
                **SAMPLE_CANDLE,
                "sessao": "London",
                "contexto_comportamental": "Expansao",
            })

        n = await local_mgr.count_by_context("R_100", "London", "Expansao")
        assert n == 300
        assert n >= 300  # critério de confiabilidade do LGN

    async def test_count_ignores_different_ativo(self, local_mgr):
        """Contagem não deve incluir registros de outros ativos."""
        await local_mgr.save_candle({**SAMPLE_CANDLE, "ativo": "CRASH_1000"})

        n = await local_mgr.count_by_context("R_100", "London", "Expansao")
        assert n == 0


# ─────────────────────────────────────────────────────────────────────────────
# BLOCO 3 — SupabaseManager._build_signal_data (sem I/O)
# ─────────────────────────────────────────────────────────────────────────────

class TestBuildSignalData:
    """
    Testa _build_signal_data sem nenhuma conexão ao Supabase.
    Este método é a "tradução" do payload do Sniper para o schema do PRD.
    """

    def test_ativo_maps_to_symbol(self, supabase_mgr):
        data = supabase_mgr._build_signal_data(SAMPLE_PAYLOAD, "PRE_SIGNAL")
        assert data["ativo"] == "R_100"

    def test_estrategia_defaults_to_z_score_m1(self, supabase_mgr):
        """Payload sem 'estrategia' deve usar o default Z_SCORE_M1."""
        data = supabase_mgr._build_signal_data(SAMPLE_PAYLOAD, "PRE_SIGNAL")
        assert data["estrategia"] == "Z_SCORE_M1"

    def test_estrategia_override_from_payload(self, supabase_mgr):
        """Payload com 'estrategia' explícita deve prevalecer sobre o default."""
        payload = {**SAMPLE_PAYLOAD, "estrategia": "CRASH_DRIFT"}
        data = supabase_mgr._build_signal_data(payload, "PRE_SIGNAL")
        assert data["estrategia"] == "CRASH_DRIFT"

    def test_direcao_maps_to_direction(self, supabase_mgr):
        data = supabase_mgr._build_signal_data(SAMPLE_PAYLOAD, "PRE_SIGNAL")
        assert data["direcao"] == "PUT"

    def test_p_win_historica_is_float(self, supabase_mgr):
        data = supabase_mgr._build_signal_data(SAMPLE_PAYLOAD, "PRE_SIGNAL")
        assert isinstance(data["p_win_historica"], float)
        assert data["p_win_historica"] == pytest.approx(0.64, abs=1e-6)

    def test_status_pre_signal(self, supabase_mgr):
        data = supabase_mgr._build_signal_data(SAMPLE_PAYLOAD, "PRE_SIGNAL")
        assert data["status"] == "PRE_SIGNAL"

    def test_status_confirmed(self, supabase_mgr):
        data = supabase_mgr._build_signal_data(SAMPLE_PAYLOAD, "CONFIRMED")
        assert data["status"] == "CONFIRMED"

    def test_timestamp_sinal_is_epoch(self, supabase_mgr):
        """timestamp_sinal deve ser o epoch da Deriv (PRD Regra 3)."""
        data = supabase_mgr._build_signal_data(SAMPLE_PAYLOAD, "PRE_SIGNAL")
        assert data["timestamp_sinal"] == 1_700_000_030
        assert isinstance(data["timestamp_sinal"], int)

    def test_contexto_jsonb_has_all_prd_fields(self, supabase_mgr):
        """
        Campo JSONB 'contexto' deve conter exatamente os campos do schema
        definido na Seção 6 do PRD.
        """
        data = supabase_mgr._build_signal_data(SAMPLE_PAYLOAD, "PRE_SIGNAL")
        ctx  = data["contexto"]

        assert "z_score_atual" in ctx
        assert "ev_calculado"  in ctx
        assert "kelly_sizing"  in ctx
        assert "n_amostral"    in ctx

    def test_contexto_z_score_atual_value(self, supabase_mgr):
        data = supabase_mgr._build_signal_data(SAMPLE_PAYLOAD, "PRE_SIGNAL")
        assert data["contexto"]["z_score_atual"] == pytest.approx(2.8234, abs=1e-4)

    def test_contexto_ev_calculado_matches_prd(self, supabase_mgr):
        """EV calculado deve bater com o exemplo do config.json (PRD Seção 6)."""
        data = supabase_mgr._build_signal_data(SAMPLE_PAYLOAD, "PRE_SIGNAL")
        assert data["contexto"]["ev_calculado"] == pytest.approx(0.184, abs=1e-6)

    def test_contexto_kelly_sizing_matches_prd(self, supabase_mgr):
        data = supabase_mgr._build_signal_data(SAMPLE_PAYLOAD, "PRE_SIGNAL")
        assert data["contexto"]["kelly_sizing"] == pytest.approx(0.015, abs=1e-6)

    def test_contexto_n_amostral_is_int(self, supabase_mgr):
        data = supabase_mgr._build_signal_data(SAMPLE_PAYLOAD, "PRE_SIGNAL")
        assert data["contexto"]["n_amostral"] == 347
        assert isinstance(data["contexto"]["n_amostral"], int)

    def test_no_io_in_build(self, supabase_mgr):
        """_build_signal_data é puro — não deve contatar o Supabase."""
        # Se chegou aqui sem erro, o cliente não foi instanciado
        assert supabase_mgr._supabase is None
        supabase_mgr._build_signal_data(SAMPLE_PAYLOAD, "PRE_SIGNAL")
        assert supabase_mgr._supabase is None


# ─────────────────────────────────────────────────────────────────────────────
# BLOCO 4 — SupabaseManager: save_signal e update_signal_status (mocked)
# ─────────────────────────────────────────────────────────────────────────────

class TestSupabaseManagerMocked:

    async def test_save_signal_returns_id_from_supabase(self, supabase_mgr):
        """save_signal deve retornar o ID retornado pelo Supabase."""
        mock_result = MagicMock()
        mock_result.data = [{"id": 99}]

        mock_table = MagicMock()
        mock_table.insert.return_value.execute.return_value = mock_result
        supabase_mgr._get_client = MagicMock(
            return_value=MagicMock(table=MagicMock(return_value=mock_table))
        )

        record_id = await supabase_mgr.save_signal(SAMPLE_PAYLOAD, "PRE_SIGNAL")
        assert record_id == 99

    async def test_save_signal_insert_called_with_correct_table(self, supabase_mgr):
        """save_signal deve inserir na tabela 'catalogo_estrategias'."""
        mock_result = MagicMock()
        mock_result.data = [{"id": 1}]
        mock_client = MagicMock()
        mock_client.table.return_value.insert.return_value.execute.return_value = mock_result
        supabase_mgr._get_client = MagicMock(return_value=mock_client)

        await supabase_mgr.save_signal(SAMPLE_PAYLOAD, "PRE_SIGNAL")

        mock_client.table.assert_called_once_with("catalogo_estrategias")

    async def test_save_signal_returns_none_on_empty_response(self, supabase_mgr):
        """Se Supabase retornar lista vazia, save_signal retorna None."""
        mock_result = MagicMock()
        mock_result.data = []
        mock_client = MagicMock()
        mock_client.table.return_value.insert.return_value.execute.return_value = mock_result
        supabase_mgr._get_client = MagicMock(return_value=mock_client)

        result = await supabase_mgr.save_signal(SAMPLE_PAYLOAD, "PRE_SIGNAL")
        assert result is None

    async def test_update_signal_status_calls_update_eq(self, supabase_mgr):
        """update_signal_status deve chamar UPDATE ... SET status WHERE id=N."""
        mock_result = MagicMock()
        mock_result.data = [{"id": 42, "status": "CONFIRMED"}]
        mock_table = MagicMock()
        mock_table.update.return_value.eq.return_value.execute.return_value = mock_result
        supabase_mgr._get_client = MagicMock(
            return_value=MagicMock(table=MagicMock(return_value=mock_table))
        )

        success = await supabase_mgr.update_signal_status(42, "CONFIRMED")

        assert success is True
        mock_table.update.assert_called_once_with({"status": "CONFIRMED"})
        mock_table.update.return_value.eq.assert_called_once_with("id", 42)

    async def test_update_signal_status_returns_false_on_empty(self, supabase_mgr):
        """Atualização sem linhas afetadas deve retornar False."""
        mock_result = MagicMock()
        mock_result.data = []
        mock_table = MagicMock()
        mock_table.update.return_value.eq.return_value.execute.return_value = mock_result
        supabase_mgr._get_client = MagicMock(
            return_value=MagicMock(table=MagicMock(return_value=mock_table))
        )

        success = await supabase_mgr.update_signal_status(999, "CONFIRMED")
        assert success is False


# ─────────────────────────────────────────────────────────────────────────────
# BLOCO 5 — Integração Sniper + SupabaseManager
# ─────────────────────────────────────────────────────────────────────────────

class TestSniperDBIntegration:

    async def test_pre_signal_calls_save_signal(self, sniper_with_mock_db):
        """PRE_SIGNAL no segundo 50 → save_signal chamado com status PRE_SIGNAL."""
        sniper, mock_db = sniper_with_mock_db

        await sniper._persist_signal("PRE_SIGNAL", SAMPLE_PAYLOAD)

        mock_db.save_signal.assert_called_once_with(SAMPLE_PAYLOAD, "PRE_SIGNAL")

    async def test_pre_signal_stores_id_in_signal_ids(self, sniper_with_mock_db):
        """Após PRE_SIGNAL, _signal_ids[symbol] deve guardar o ID retornado."""
        sniper, mock_db = sniper_with_mock_db
        mock_db.save_signal.return_value = 42

        await sniper._persist_signal("PRE_SIGNAL", SAMPLE_PAYLOAD)

        assert sniper._signal_ids["R_100"] == 42

    async def test_confirmed_calls_update_with_pre_signal_id(self, sniper_with_mock_db):
        """CONFIRMED deve chamar update_signal_status com o ID do PRE_SIGNAL."""
        sniper, mock_db = sniper_with_mock_db
        sniper._signal_ids["R_100"] = 42  # simula PRE_SIGNAL já persistido

        await sniper._persist_signal("CONFIRMED", SAMPLE_PAYLOAD)

        mock_db.update_signal_status.assert_called_once_with(42, "CONFIRMED")

    async def test_confirmed_resets_signal_id(self, sniper_with_mock_db):
        """Após CONFIRMED bem-sucedido, _signal_ids[symbol] deve voltar a None."""
        sniper, mock_db = sniper_with_mock_db
        sniper._signal_ids["R_100"] = 42

        await sniper._persist_signal("CONFIRMED", SAMPLE_PAYLOAD)

        assert sniper._signal_ids["R_100"] is None

    async def test_confirmed_without_pre_signal_id_inserts_directly(self, sniper_with_mock_db):
        """
        CONFIRMED sem PRE_SIGNAL persistido (ex: restart da VPS na mesma vela)
        deve fazer INSERT direto com status CONFIRMED.
        """
        sniper, mock_db = sniper_with_mock_db
        sniper._signal_ids["R_100"] = None  # sem PRE_SIGNAL anterior

        await sniper._persist_signal("CONFIRMED", SAMPLE_PAYLOAD)

        mock_db.save_signal.assert_called_once_with(SAMPLE_PAYLOAD, "CONFIRMED")
        mock_db.update_signal_status.assert_not_called()

    async def test_persist_signal_exception_is_silent(self, sniper_with_mock_db):
        """
        Falha no Supabase (rede, timeout) deve ser capturada silenciosamente.
        O loop principal do Sniper jamais pode parar por erro de banco.
        """
        sniper, mock_db = sniper_with_mock_db
        mock_db.save_signal = AsyncMock(side_effect=ConnectionError("Timeout"))

        # Não deve propagar exceção
        await sniper._persist_signal("PRE_SIGNAL", SAMPLE_PAYLOAD)

    async def test_sniper_without_db_does_not_persist(self):
        """Sniper sem db= None não tenta persistir e não lança exceção."""
        sniper = DerivSniper(CONFIG, app_id="test_id", db=None)
        for price in BASELINE_PRICES:
            sniper.deques["R_100"].append(price)

        # _persist_signal não deve ser chamado — mas se for, não deve falhar
        result = sniper._process_tick_sync("R_100", EPOCH_S50, SPIKE_UP)
        assert result is not None   # sinal gerado normalmente
        assert result[0] == "PRE_SIGNAL"

    async def test_full_cycle_pre_then_confirmed_with_db(self, sniper_with_mock_db):
        """
        Ciclo completo com DB mockado:
        1. PRE_SIGNAL → save_signal(PRE_SIGNAL) → guarda id=42
        2. CONFIRMED  → update_signal_status(42, CONFIRMED) → limpa id
        """
        sniper, mock_db = sniper_with_mock_db
        mock_db.save_signal.return_value = 42

        await sniper._persist_signal("PRE_SIGNAL", SAMPLE_PAYLOAD)
        assert sniper._signal_ids["R_100"] == 42

        await sniper._persist_signal("CONFIRMED", SAMPLE_PAYLOAD)
        mock_db.update_signal_status.assert_called_once_with(42, "CONFIRMED")
        assert sniper._signal_ids["R_100"] is None
