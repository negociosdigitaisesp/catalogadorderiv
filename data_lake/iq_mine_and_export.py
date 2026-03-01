"""
Quick script: runs ONLY steps 2-4 of the IQ pipeline (mining, upload, export).
Download already completed — catalog_iq.db has all 8 assets.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ["PYTHONIOENCODING"] = "utf-8"

from dotenv import load_dotenv
from pathlib import Path
load_dotenv(Path(__file__).parent.parent / ".env")

import time
from iq_lake_runner import minerar_grade, upload_to_supabase, exportar_config_elite

inicio = time.time()
print("\n" + "=" * 70)
print("  IQ PIPELINE — Passos 2-4 (Mine → Upload → Export)")
print("=" * 70)

# Passo 2
print("\n[RUNNER] === PASSO 2/3: MINERACAO GALE 2 ===")
t2 = time.time()
df = minerar_grade()
print(f"[RUNNER] Mineracao: {time.time()-t2:.1f}s | {len(df)} registros")

if df.empty:
    print("[RUNNER] Nenhum dado minerado!")
    sys.exit(1)

# Passo 3
print("\n[RUNNER] === PASSO 3/3: UPLOAD SUPABASE ===")
t3 = time.time()
n = upload_to_supabase(df)
print(f"[RUNNER] Upload: {time.time()-t3:.1f}s | {n} registros")

# Passo 4
print("\n[RUNNER] === PASSO 4/4: EXPORTACAO ELITE ===")
t4 = time.time()
config = exportar_config_elite(df)
print(f"[RUNNER] Export: {time.time()-t4:.1f}s")

total = time.time() - inicio
print(f"\n{'='*70}")
print(f"  COMPLETO em {total:.1f}s | {len(df)} minerados | {n} uploaded | {len(config)} Elite")
print(f"{'='*70}\n")
