"""
TESTE 6: AgentDiscovery (M5) — End-to-End
==========================================
Roda o ciclo completo REAL do Oráculo:
  DataLoader → HypothesisGenerator → PatternMiner → StrategyValidator → StrategyWriter

Usa apenas 1 ativo (R_75) com 15 dias de dados para ser rápido.
Supabase é bypassado via _NullSupabaseClient (sem credenciais).
Config.json é protegido via backup/restore.
"""
import asyncio
import json
import os
import shutil
import logging
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)

from agente.core.agent_discovery import AgentDiscovery

async def test_e2e():
    print("="*58)
    print(" TESTE 6: AGENT DISCOVERY (M5) — END-TO-END ")
    print("="*58)
    
    # ─── Backup config.json ───────────────────────────────────────────────
    config_path = Path("config.json")
    backup_path = Path("config.json.backup.test6")
    if config_path.exists():
        shutil.copy(str(config_path), str(backup_path))
        print("[!] Backup do config.json criado.")

    try:
        # ─── Cria o agente SEM credenciais Supabase (NullClient) ──────────
        agent = AgentDiscovery(
            config_path="config.json",
            db_path="catalog/catalog.db",
            app_id="1089",
            supabase_url="",   # força NullSupabaseClient
            supabase_key="",
        )

        print("\n[1] Iniciando ciclo completo com 1 ativo (R_75, 15 dias)...\n")
        
        # Roda apenas com R_75 para ser rápido (~15 dias = ~21k velas)
        result = await agent.run_cycle(ativos=["R_75"])

        # ─── Relatório visual ─────────────────────────────────────────────
        agent.print_final_report(result)

        # ─── Validação dos resultados ─────────────────────────────────────
        print("\n[2] VALIDAÇÃO AUTOMÁTICA DO CICLO:")
        
        registros = result.get("registros_carregados", 0)
        hipoteses = result.get("hipoteses_geradas", 0)
        minerados = result.get("padroes_minerados", 0)
        aprovadas = result.get("aprovadas", 0)
        condicionais = result.get("condicionais", 0)
        reprovadas = result.get("reprovadas", 0)
        escritas = result.get("estrategias_escritas", 0)
        duracao = result.get("duracao_segundos", 0)
        
        # Checagem 1: Dados foram carregados?
        assert registros > 0, f"ERRO: 0 registros carregados!"
        print(f"  ✅ Dados carregados: {registros} registros")
        
        # Checagem 2: Hipóteses geradas?
        assert hipoteses > 0, f"ERRO: 0 hipóteses geradas!"
        print(f"  ✅ Hipóteses geradas: {hipoteses}")
        
        # Checagem 3: Mineração rodou? (pode ter 0 se WR mínimo for alto)
        print(f"  {'✅' if minerados > 0 else '⚠️'} Padrões minerados: {minerados}")
        
        # Checagem 4: Validação separou corretamente?
        total_validados = aprovadas + condicionais + reprovadas
        if minerados > 0:
            assert total_validados == minerados, \
                f"ERRO: Total validados ({total_validados}) != minerados ({minerados})"
            print(f"  ✅ Validação consistente: {aprovadas} aprovadas + {condicionais} condicionais + {reprovadas} reprovadas = {total_validados}")
        else:
            print(f"  ⚠️ Sem padrões minerados (WR mínimo alto). OK para teste.")
        
        # Checagem 5: Gravação funcionou?
        if escritas > 0:
            with open("config.json", "r") as f:
                cfg = json.load(f)
            grade = cfg.get("grade_horaria", [])
            assert len(grade) >= escritas, \
                f"ERRO: config tem {len(grade)} mas {escritas} foram escritas!"
            print(f"  ✅ Config.json atualizado: {len(grade)} estratégias na grade_horaria")
        else:
            print(f"  ⚠️ 0 estratégias escritas (filtros PRD imperam). Normal no ambiente de teste.")

        # Checagem 6: Tempo de execução razoável?
        assert duracao < 300, f"ERRO: Ciclo levou {duracao}s (>5min)!"
        print(f"  ✅ Duração: {duracao:.1f}s")
        
        print(f"\n  🏆 CICLO COMPLETO EXECUTADO COM SUCESSO!")

    finally:
        # ─── Restaura config.json ─────────────────────────────────────────
        if backup_path.exists():
            shutil.copy(str(backup_path), "config.json")
            os.remove(str(backup_path))
            print("[✓] Config.json original restaurado.\n")

    print("="*58)
    print(" TESTE 6 CONCLUÍDO — PIPELINE INTEIRO VALIDADO! ")
    print("="*58)

if __name__ == "__main__":
    asyncio.run(test_e2e())
