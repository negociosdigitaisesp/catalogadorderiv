import asyncio
import os
import json
import pandas as pd
from pathlib import Path
from agente.core.strategy_writer import StrategyWriter

import logging
logging.basicConfig(level=logging.INFO, format="%(message)s")

async def test_writer():
    print("="*50)
    print(" TESTE 5: STRATEGY WRITER (M4) ")
    print("="*50)
    
    # ─── Mock Data ────────────────────────────────────────────────────────────
    # O StrategyWriter.write_all() espera o dict INTEIRO vindo do StrategyValidator:
    #   { "aprovados": [...], "condicionais": [...], "reprovados": [...] }
    #
    # Cada item dentro precisa ter:
    #   validated_result["mined_result"]["hypothesis"]["ativo"]     → ex: "R_100"
    #   validated_result["mined_result"]["hypothesis"]["contexto"]  → ex: {"hh_mm": "14:00", "dia_semana": 4}
    #   validated_result["mined_result"]["hypothesis"]["direcao"]   → ex: "CALL"
    # ──────────────────────────────────────────────────────────────────────────
    
    aprovadas = {
        "aprovados": [
            {
                "status": "APROVADO",
                "motivo": "Aprovado por recorrência alta (WR=98.0%, N=30, score=0.98)",
                "stake_multiplier": 1.0,
                "win_1a_rate": 0.70,
                "win_gale1_rate": 0.20,
                "win_gale2_rate": 0.08,
                "hit_rate": 0.02,
                "ev_gale2": 0.50,
                "kelly_quarter": 0.25,
                "criterios_aprovados": 3,
                "mined_result": {
                    "variacao": "V4",
                    "ativo": "R_100",
                    "horario_alvo": "14:00",
                    "score_ponderado": 0.98,
                    "win_rate_final": 0.98,
                    "n_test": 30,
                    "ev_final": 0.50,
                    "p_1a": 0.70, "p_gale1": 0.20, "p_gale2": 0.08, "p_hit": 0.02,
                    "n_total": 30, "n_win_1a": 21, "n_win_g1": 6, "n_win_g2": 2, "n_hit": 1,
                    "hypothesis": {
                        "ativo": "R_100",
                        "direcao": "CALL",
                        "contexto": {"hh_mm": "14:00", "dia_semana": 4},
                    }
                }
            }
        ],
        "condicionais": [
            {
                "status": "CONDICIONAL",
                "motivo": "Condicional — padrão promissor mas aguarda confirmação (WR=92.0%, N=25)",
                "stake_multiplier": 0.5,
                "win_1a_rate": 0.60,
                "win_gale1_rate": 0.20,
                "win_gale2_rate": 0.12,
                "hit_rate": 0.08,
                "ev_gale2": 0.15,
                "kelly_quarter": 0.125,
                "criterios_aprovados": 2,
                "mined_result": {
                    "variacao": "V3",
                    "ativo": "R_50",
                    "horario_alvo": "15:00",
                    "score_ponderado": 0.92,
                    "win_rate_final": 0.92,
                    "n_test": 25,
                    "ev_final": 0.15,
                    "p_1a": 0.60, "p_gale1": 0.20, "p_gale2": 0.12, "p_hit": 0.08,
                    "n_total": 25, "n_win_1a": 15, "n_win_g1": 5, "n_win_g2": 3, "n_hit": 2,
                    "hypothesis": {
                        "ativo": "R_50",
                        "direcao": "PUT",
                        "contexto": {"hh_mm": "15:00", "dia_semana": 2},
                    }
                }
            }
        ],
        "reprovados": []
    }
    
    # ─── Backup ───────────────────────────────────────────────────────────────
    config_path = Path("config.json")
    backup_path = Path("config.json.backup.test")
    if config_path.exists():
        import shutil
        shutil.copy("config.json", str(backup_path))
        print("[!] Backup do config.json original criado para não sujar sua VPS.")
        
    writer = StrategyWriter()
    
    # ─── DummySupabaseClient ──────────────────────────────────────────────────
    class DummySupabaseClient:
        """Simula insert no Supabase sem fazer chamada real."""
        def table(self, name):
            self._table = name
            return self
        def insert(self, data):
            self._data = data
            return self
        def execute(self):
            print(f"  [Mock Supabase] INSERT em '{self._table}' executado com sucesso.")
            class Resp:
                data = [self._data]
            return Resp()

    dummy_client = DummySupabaseClient()
    
    # ─── Executa ──────────────────────────────────────────────────────────────
    print("\n[1] Executando StrategyWriter.write_all(aprovadas, dummy_client)...")
    result = await writer.write_all(aprovadas, dummy_client)
    
    print(f"\n[2] Resultado do Writer: {result['estrategias_escritas']} estratégias escritas "
          f"({result['aprovadas']} aprovadas | {result['condicionais']} condicionais)")
    
    # ─── Verificação do config.json ───────────────────────────────────────────
    print("\n[3] Verificando modificações no config.json gerado...")
    try:
        with open("config.json", "r") as f:
            cfg = json.load(f)
        
        # O Writer salva na chave "grade_horaria" conforme o PRD
        estrategias = cfg.get("grade_horaria", [])
        
        print(f"  Encontradas {len(estrategias)} estratégias na seção 'grade_horaria':")
        for est in estrategias:
            print(f"   -> ID: {est['strategy_id']} | {est['ativo']} | "
                  f"Hora: {est['hh_mm']} | Stake: {est['stake']} | "
                  f"WR_G2: {est['win_rate_g2']*100:.1f}% | Status: {est['status']}")
            
        assert any(e["ativo"] == "R_100" and e["stake"] == 1.0 for e in estrategias), \
            "ERRO: R_100 (Elite, stake 1.0) com erro de gravação!"
        assert any(e["ativo"] == "R_50" and e["stake"] == 0.5 for e in estrategias), \
            "ERRO: R_50 (Condicional, stake 0.5) com erro de gravação!"
        
        print("\n  ✅ SUCESSO: Gravador M4 escreveu os multiplicadores corretos (1.0 e 0.5) no config.json.")
        print("  ✅ SUCESSO: Schema 'grade_horaria' com strategy_id temporal gravado perfeitamente.")
        
    finally:
        # Restaura o original
        if backup_path.exists():
            import shutil
            shutil.copy(str(backup_path), "config.json")
            os.remove(str(backup_path))
            print("[✓] Backup do config original restaurado com sucesso.")

    print("\n==================================================")
    print(" TESTE M4 CONCLUÍDO COM SUCESSO ")
    print("==================================================")

if __name__ == "__main__":
    asyncio.run(test_writer())
