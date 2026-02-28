"""
CATALOGAÇÃO COMPLETA — Auto Quant Discovery
=============================================
Roda o ciclo REAL do Oráculo com TODOS os 9 ativos do PRD:
  R_10, R_25, R_50, R_75, R_100, CRASH500, CRASH1000, BOOM500, BOOM1000

Salva o resultado em:
  catalogacao/grade_horaria_YYYY-MM-DD_HHMMSS.json
"""
import asyncio
import json
import os
import shutil
import logging
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)

from agente.core.agent_discovery import AgentDiscovery

# ─── Todos os 9 ativos do PRD ─────────────────────────────────────────────────
ATIVOS_PRD = [
    "R_10", "R_25", "R_50", "R_75", "R_100",
    "CRASH500", "CRASH1000",
    "BOOM500", "BOOM1000",
]


async def catalogar():
    print("=" * 62)
    print("  🔬 CATALOGAÇÃO COMPLETA — Auto Quant Discovery")
    print(f"  📋 Ativos: {len(ATIVOS_PRD)} ({', '.join(ATIVOS_PRD)})")
    print("=" * 62)

    # ─── Timestamp para nome do arquivo ───────────────────────────────────
    agora = datetime.now(timezone.utc)
    stamp = agora.strftime("%Y-%m-%d_%H%M%S")
    stamp_legivel = agora.strftime("%Y-%m-%d %H:%M UTC")

    # ─── Prepara pasta de saída ───────────────────────────────────────────
    pasta = Path("catalogacao")
    pasta.mkdir(parents=True, exist_ok=True)

    # ─── Config temporário (não polui o original) ─────────────────────────
    config_temp = str(pasta / f"config_temp_{stamp}.json")
    # Começa limpo
    with open(config_temp, "w") as f:
        json.dump({}, f)

    # ─── Cria o agente ────────────────────────────────────────────────────
    agent = AgentDiscovery(
        config_path=config_temp,
        db_path="catalog/catalog.db",
        app_id="1089",
    )

    print(f"\n[1] Iniciando ciclo completo (FORCE RESET = download de todos os ativos)...")
    print(f"    Data: {stamp_legivel}")
    print(f"    Config temporário: {config_temp}\n")

    # Força reset do catalog.db para garantir que TODOS os 9 ativos sejam baixados
    # Sem isso, se o cache já tem R_75 fresco, ele pula os outros 8 ativos
    agent.loader.reset_catalog(agent.db_path)

    # ─── Roda o ciclo com TODOS os ativos ─────────────────────────────────
    result = await agent.run_cycle(ativos=ATIVOS_PRD)

    # ─── Relatório visual ─────────────────────────────────────────────────
    agent.print_final_report(result)

    # ─── Salva resultado final com identificação ──────────────────────────
    arquivo_final = pasta / f"grade_horaria_{stamp}.json"

    # Lê o config gerado e adiciona metadados
    with open(config_temp, "r") as f:
        config_gerado = json.load(f)

    # Adiciona cabeçalho de identificação
    output = {
        "_identificacao": {
            "projeto": "ORACLE QUANT — Auto Quant Discovery",
            "versao": "2.0",
            "data_catalogacao": stamp_legivel,
            "epoch_catalogacao": int(agora.timestamp()),
            "ativos_analisados": ATIVOS_PRD,
            "total_ativos": len(ATIVOS_PRD),
            "registros_carregados": result.get("registros_carregados", 0),
            "hipoteses_geradas": result.get("hipoteses_geradas", 0),
            "padroes_minerados": result.get("padroes_minerados", 0),
            "aprovadas": result.get("aprovadas", 0),
            "condicionais": result.get("condicionais", 0),
            "reprovadas": result.get("reprovadas", 0),
            "estrategias_escritas": result.get("estrategias_escritas", 0),
            "duracao_segundos": result.get("duracao_segundos", 0),
        },
        "grade_horaria": config_gerado.get("grade_horaria", []),
    }

    with open(arquivo_final, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    # ─── Remove config temporário ─────────────────────────────────────────
    os.remove(config_temp)

    # ─── Resumo final ─────────────────────────────────────────────────────
    n_grade = len(output["grade_horaria"])
    
    print("\n" + "=" * 62)
    print("  📁 CATALOGAÇÃO SALVA COM SUCESSO!")
    print("=" * 62)
    print(f"  Arquivo: {arquivo_final}")
    print(f"  Data:    {stamp_legivel}")
    print(f"  Estratégias na grade: {n_grade}")
    print(f"  Aprovadas: {result.get('aprovadas', 0)} | Condicionais: {result.get('condicionais', 0)}")
    print(f"  Duração total: {result.get('duracao_segundos', 0):.0f}s")
    print("=" * 62)


if __name__ == "__main__":
    asyncio.run(catalogar())
