"""
lake_runner.py — Orquestrador da nova arquitetura Data Lake

EXECUTA EM SEQUÊNCIA:
  1. lake_loader  → Agrega métricas do catalog.db
  2. lake_uploader → Envia para hft_lake.hft_raw_metrics
  3. lake_exporter → Gera config_lake.json

USO:
  python data_lake/lake_runner.py

NÃO interfere com nenhum processo existente.
"""

import time
from lake_loader import run_loader
from lake_uploader import upload
from lake_exporter import run_exporter


def main():
    inicio = time.time()
    print("\n" + "="*60)
    print("  ORACLE QUANT — DATA LAKE RUNNER")
    print("="*60)

    # Passo 1: Carregar
    print("\n[RUNNER] === PASSO 1/3: LOADER ===")
    t1 = time.time()
    df = run_loader()
    print(f"[RUNNER] Loader: {round(time.time()-t1, 1)}s")

    if df.empty:
        print("[RUNNER] ❌ Nenhum dado carregado. Abortando.")
        return

    # Passo 2: Upload
    print("\n[RUNNER] === PASSO 2/3: UPLOADER ===")
    t2 = time.time()
    resultado = upload(df)
    print(f"[RUNNER] Uploader: {round(time.time()-t2, 1)}s")

    # Passo 3: Exportar
    print("\n[RUNNER] === PASSO 3/3: EXPORTER ===")
    t3 = time.time()
    run_exporter()
    print(f"[RUNNER] Exporter: {round(time.time()-t3, 1)}s")

    total = round(time.time() - inicio, 1)
    print(f"\n{'='*60}")
    print(f"  ✅ DATA LAKE COMPLETO em {total}s")
    print(f"  Registros processados: {resultado['inseridos']}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
