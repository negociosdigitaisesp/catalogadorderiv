"""
run_oracle.py — Ponto de entrada do Oráculo (Camada A)

Executa o backtest completo de todos os ativos definidos em ATIVOS_MONITORADOS,
gera o config.json para o Sniper e persiste os resultados no Supabase.

Uso:
    python run_oracle.py

Variáveis de ambiente requeridas (.env):
    SUPABASE_URL      → URL do projeto Supabase
    SUPABASE_KEY      → Chave service_role do Supabase
    DERIV_APP_ID      → ID do App Deriv
"""

import asyncio
import os
import sys

from dotenv import load_dotenv

load_dotenv()

# ── Ativos a processar (edite esta lista conforme necessário) ─────────────────
ATIVOS_MONITORADOS = [
    # Volatility Index (Z-Score S1)
    "R_10", "R_25", "R_50", "R_75", "R_100",
    # Crash (Drift S2) — IDs oficiais Deriv
    "CRASH1000", "CRASH500", "CRASH300",
    # Boom (Drift S3) — IDs oficiais Deriv
    "BOOM1000", "BOOM500", "BOOM300",
]


async def main():
    from core.oracle_backtest import OracleOrchestrator

    app_id       = os.getenv("DERIV_APP_ID", "85515")
    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_KEY")

    if not supabase_url or not supabase_key:
        print("[ERRO] Defina SUPABASE_URL e SUPABASE_KEY no arquivo .env")
        sys.exit(1)

    print("=" * 60)
    print("  ORÁCULO — Motor de Inteligência Estatística (Camada A)")
    print(f"  Ativos: {ATIVOS_MONITORADOS}")
    print(f"  App ID: {app_id}")
    print("=" * 60)

    oracle = OracleOrchestrator(
        app_id=app_id,
        supabase_url=supabase_url,
        supabase_key=supabase_key,
    )

    await oracle.run(ATIVOS_MONITORADOS)

    print("\n[ORACLE] Concluído! config.json atualizado.")
    print("[ORACLE] Resultados persistidos no Supabase (oracle_backtest_results).")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[ORACLE] Interrompido pelo operador.")
