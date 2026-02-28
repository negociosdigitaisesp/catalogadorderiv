"""
agente/core/agent_discovery.py
=====================================
Auto Quant Discovery -- Modulo 5 -- O Orquestrador

Responsabilidade:
  Conectar todos os 4 modulos do agente em um unico ciclo autonomo:
  DataLoader -> HypothesisGenerator -> PatternMiner -> StrategyValidator -> StrategyWriter

  Ao terminar, o config.json esta atualizado com todas as novas estrategias
  descobertas, validadas e prontas para o Sniper operar.

EXECUCAO:
  python agente/core/agent_discovery.py

REGRAS ABSOLUTAS (PRD):
  - Sem loops bloqueantes -- tudo async/await
  - Sem datetime.now() para logica de trading
  - Sem salvar ticks no Supabase
  - Sem indicadores tecnicos
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path
from time import time
from typing import Any, Optional

# Ajusta o path para imports relativos funcionarem ao rodar direto
_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
if str(_ROOT / "agente") not in sys.path:
    sys.path.insert(0, str(_ROOT / "agente"))

from agente.core.data_loader import DataLoader
from agente.core.hypothesis_generator import HypothesisGenerator
from agente.core.pattern_miner import PatternMiner
from agente.core.strategy_validator import StrategyValidator
from agente.core.strategy_writer import StrategyWriter

logger = logging.getLogger(__name__)

# Ativos padrao do PRD (9 ativos Deriv validos)
_ATIVOS_PADRAO = [
    "R_10", "R_25", "R_50", "R_75", "R_100",
    "CRASH500", "CRASH1000",
    "BOOM500", "BOOM1000",
]


class AgentDiscovery:
    """
    Orquestrador final do Auto Quant Discovery.

    Conecta DataLoader -> HypothesisGenerator -> PatternMiner ->
    StrategyValidator -> StrategyWriter em um ciclo autonomo assincrono.

    Uso:
        agent = AgentDiscovery()
        result = asyncio.run(agent.run_cycle())
        agent.print_final_report(result)
    """

    def __init__(
        self,
        config_path: str = "config.json",
        db_path: str = "catalog/catalog.db",
        app_id: Optional[str] = None,
        supabase_url: Optional[str] = None,
        supabase_key: Optional[str] = None,
    ) -> None:
        self.config_path = config_path
        self.db_path     = db_path

        # Le do .env se nao fornecidos
        self.app_id       = app_id       or os.getenv("DERIV_APP_ID",       "85515")
        self.supabase_url = supabase_url or os.getenv("SUPABASE_URL",       "") \
                                        or os.getenv("NEXT_PUBLIC_SUPABASE_URL", "")
        self.supabase_key = supabase_key or os.getenv("SUPABASE_KEY",       "") \
                                        or os.getenv("SUPABASE_SERVICE_KEY", "")

        # Instancia os 5 modulos
        self.loader    = DataLoader()
        self.generator = HypothesisGenerator()
        self.miner     = PatternMiner()
        self.validator = StrategyValidator()
        self.writer    = StrategyWriter()

        # Supabase client (lazy -- inicializado em run_cycle)
        self.supabase_client: Any = None

        logger.info("[AGENT] AgentDiscovery inicializado | app_id=%s", self.app_id)

    def _get_supabase_client(self) -> Any:
        """Inicializa o cliente Supabase de forma lazy."""
        if self.supabase_client is not None:
            return self.supabase_client

        if not self.supabase_url or not self.supabase_key:
            logger.warning(
                "[AGENT] Credenciais Supabase ausentes -- "
                "notify_supabase sera um no-op."
            )
            self.supabase_client = _NullSupabaseClient()
            return self.supabase_client

        try:
            from supabase import create_client
            self.supabase_client = create_client(self.supabase_url, self.supabase_key)
            logger.info("[AGENT] Supabase conectado: %s", self.supabase_url[:40])
        except Exception as exc:
            logger.error("[AGENT] Erro ao conectar Supabase: %s", exc)
            self.supabase_client = _NullSupabaseClient()

        return self.supabase_client

    # -------------------------------------------------------------------------
    # METODO 2: run_cycle
    # -------------------------------------------------------------------------

    async def run_cycle(
        self,
        ativos: Optional[list[str]] = None,
    ) -> dict:
        """
        Ciclo completo do Auto Quant Discovery -- 5 passos.

        PASSO 1: Carrega dados (DataLoader)
        PASSO 2: Gera hipoteses (HypothesisGenerator)
        PASSO 3: Minera padroes com backtest vetorizado (PatternMiner)
        PASSO 4: Valida estatisticamente (StrategyValidator)
        PASSO 5: Escreve aprovadas no config.json e Supabase (StrategyWriter)
        """
        inicio = time()

        if ativos is None:
            ativos = _ATIVOS_PADRAO

        supabase_client = self._get_supabase_client()

        # -- PASSO 1: Carregar Dados -------------------------------------------
        logger.info("[AGENT] === PASSO 1: Carregando dados ===")
        df = await self.loader.load_or_fetch(
            ativos=ativos,
            db_path=self.db_path,
            app_id=self.app_id,
        )
        n_registros = len(df)
        logger.info("[AGENT] Dados carregados: %d registros", n_registros)

        if df.empty:
            logger.warning(
                "[AGENT] Nenhum dado disponivel. Ciclo encerrado sem descobertas."
            )
            return _empty_cycle_result(time() - inicio)

        # -- PASSO 2: Gerar Hipoteses ------------------------------------------
        logger.info("[AGENT] === PASSO 2: Gerando hipoteses ===")
        hypotheses = self.generator.generate_hypotheses(df)
        n_hipoteses = len(hypotheses)
        logger.info("[AGENT] %d hipoteses geradas", n_hipoteses)

        if not hypotheses:
            logger.warning("[AGENT] Nenhuma hipotese gerada. Ciclo encerrado.")
            return _empty_cycle_result(time() - inicio, n_registros)

        # -- PASSO 3: Minerar Padroes ------------------------------------------
        logger.info("[AGENT] === PASSO 3: Minerando padroes (Grade Horaria Elite) ===")
        mined = self.miner.mine_all(df, hypotheses)
        n_minerados = len(mined)
        logger.info("[AGENT] %d padroes sobreviveram ao minerador", n_minerados)

        if not mined:
            logger.warning("[AGENT] Nenhum padrao aprovado pelo minerador. Ciclo encerrado.")
            return _empty_cycle_result(time() - inicio, n_registros, n_hipoteses)

        # -- PASSO 4: Validar --------------------------------------------------
        logger.info("[AGENT] === PASSO 4: Validando (Elite G2) ===")
        validated = self.validator.validate_batch(mined)
        n_aprovadas    = len(validated.get("aprovados", []))
        n_condicionais = len(validated.get("condicionais", []))
        n_reprovadas   = len(validated.get("reprovados", []))
        logger.info("[AGENT] %d aprovadas", n_aprovadas)
        logger.info("[AGENT] %d condicionais", n_condicionais)
        logger.info("[AGENT] %d reprovadas", n_reprovadas)

        # -- PASSO 5: Escrever -------------------------------------------------
        logger.info("[AGENT] === PASSO 5: Escrevendo estrategias ===")
        write_result = await self.writer.write_all(
            validated_batch=validated,
            supabase_client=supabase_client,
            config_path=self.config_path,
            report_path=str(Path(self.db_path).parent / "reports"),
        )
        n_escritas = write_result.get("estrategias_escritas", 0)
        logger.info("[AGENT] Ciclo completo. %d estrategias escritas", n_escritas)

        duracao = time() - inicio

        # Salva historico do ciclo no Supabase (Modulo 6 - Frontend)
        try:
            supabase_client.table("agent_cycles").insert({
                "started_at": int(inicio),
                "duration_seconds": round(duracao, 2),
                "registros_carregados": n_registros,
                "hipoteses_geradas": n_hipoteses,
                "padroes_minerados": n_minerados,
                "aprovadas": n_aprovadas,
                "condicionais": n_condicionais,
                "reprovadas": n_reprovadas,
                "estrategias_escritas": n_escritas
            }).execute()
            logger.info("[AGENT] Ciclo salvo na tabela agent_cycles.")
        except Exception as e:
            logger.error("[AGENT] Erro ao salvar historico do ciclo no Supabase: %s", e)

        return {
            "registros_carregados": n_registros,
            "hipoteses_geradas":    n_hipoteses,
            "padroes_minerados":    n_minerados,
            "aprovadas":            n_aprovadas,
            "condicionais":         n_condicionais,
            "reprovadas":           n_reprovadas,
            "estrategias_escritas": n_escritas,
            "config_atualizado":    write_result.get("config_atualizado", False),
            "supabase_notificado":  write_result.get("supabase_notificado", False),
            "duracao_segundos":     round(duracao, 2),
        }

    # -------------------------------------------------------------------------
    # METODO 3: print_final_report
    # -------------------------------------------------------------------------

    def print_final_report(self, cycle_result: dict) -> None:
        r = cycle_result
        config_ok  = "[OK] SIM" if r.get("config_atualizado")   else "[X] NAO"
        supa_ok    = "[OK] SIM" if r.get("supabase_notificado") else "[X] NAO"

        print("\n")
        print("+" + "=" * 50 + "+")
        print("|        AUTO QUANT DISCOVERY -- RELATORIO         |")
        print("+" + "=" * 50 + "+")
        print(f"|  Registros analisados:  {r.get('registros_carregados', 0):<25}|")
        print(f"|  Hipoteses geradas:     {r.get('hipoteses_geradas',    0):<25}|")
        print(f"|  Padroes minerados:     {r.get('padroes_minerados',    0):<25}|")
        print("+" + "-" * 50 + "+")
        print(f"|  [OK] APROVADAS:        {r.get('aprovadas',            0):<25}|")
        print(f"|  [!]  CONDICIONAIS:     {r.get('condicionais',         0):<25}|")
        print(f"|  [X]  REPROVADAS:       {r.get('reprovadas',           0):<25}|")
        print("+" + "-" * 50 + "+")
        print(f"|  Estrategias escritas:  {r.get('estrategias_escritas', 0):<25}|")
        print(f"|  Config atualizado:     {config_ok:<25}|")
        print(f"|  Supabase notificado:   {supa_ok:<25}|")
        print(f"|  Duracao:               {r.get('duracao_segundos', 0):.1f}s{'':<22}|")
        print("+" + "=" * 50 + "+")
        print()


# -----------------------------------------------------------------------------
# HELPERS INTERNOS
# -----------------------------------------------------------------------------

def _empty_cycle_result(
    duracao: float,
    n_registros: int = 0,
    n_hipoteses: int = 0,
) -> dict:
    return {
        "registros_carregados": n_registros,
        "hipoteses_geradas":    n_hipoteses,
        "padroes_minerados":    0,
        "aprovadas":            0,
        "condicionais":         0,
        "reprovadas":           0,
        "estrategias_escritas": 0,
        "config_atualizado":    False,
        "supabase_notificado":  False,
        "duracao_segundos":     round(duracao, 2),
    }


class _NullSupabaseClient:
    """Cliente nulo para quando as credenciais Supabase nao estao configuradas."""

    def table(self, *args: Any, **kwargs: Any) -> "_NullSupabaseClient":
        return self

    def upsert(self, *args: Any, **kwargs: Any) -> "_NullSupabaseClient":
        return self

    def insert(self, *args: Any, **kwargs: Any) -> "_NullSupabaseClient":
        return self

    def execute(self) -> dict:
        logger.debug("[NullSupabase] execute() chamado -- sem credenciais configuradas.")
        return {"data": [], "error": None}


# -----------------------------------------------------------------------------
# ENTRY POINT
# -----------------------------------------------------------------------------

if __name__ == "__main__":
    import logging as _logging
    from dotenv import load_dotenv

    load_dotenv()

    _logging.basicConfig(
        level=_logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    print("\nAuto Quant Discovery -- Iniciando ciclo...\n")

    agent = AgentDiscovery()
    result = asyncio.run(agent.run_cycle())
    agent.print_final_report(result)
