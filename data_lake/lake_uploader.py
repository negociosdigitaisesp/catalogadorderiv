"""
lake_uploader.py — Envia DataFrame para hft_lake.hft_raw_metrics no Supabase

LÓGICA:
- Usa conexão direta PostgreSQL (psycopg2) para contornar a limitação de
  schema exposure do PostgREST (que só expõe public por padrão)
- Usa INSERT ... ON CONFLICT DO UPDATE (UPSERT nativo) — nunca duplica
- Processa em batches de 500 linhas com executemany para performance
- Loga progresso em tempo real

Requer: DATABASE_URL no ambiente (.env) OU as variáveis individuais
NÃO modifica nenhum arquivo ou tabela existente além de hft_lake.hft_raw_metrics
"""

import os
import pandas as pd
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://postgres:1CIwYGQv09MUQA@db.ypqekkkrfklaqlzhkbwg.supabase.co:5432/postgres"
)
TABELA = "hft_lake.hft_raw_metrics"
BATCH_SIZE = 500

UPSERT_SQL = """
INSERT INTO hft_lake.hft_raw_metrics (
    ativo, hh_mm, direcao,
    n_30d, win_1a_30d, win_g1_30d, win_g2_30d, hit_30d,
    n_7d,  win_1a_7d,  win_g1_7d,  win_g2_7d,  hit_7d,
    n_3d,  win_1a_3d,  win_g1_3d,  win_g2_3d,  hit_3d,
    updated_at
)
VALUES (
    %(ativo)s, %(hh_mm)s, %(direcao)s,
    %(n_30d)s, %(win_1a_30d)s, %(win_g1_30d)s, %(win_g2_30d)s, %(hit_30d)s,
    %(n_7d)s,  %(win_1a_7d)s,  %(win_g1_7d)s,  %(win_g2_7d)s,  %(hit_7d)s,
    %(n_3d)s,  %(win_1a_3d)s,  %(win_g1_3d)s,  %(win_g2_3d)s,  %(hit_3d)s,
    NOW()
)
ON CONFLICT ON CONSTRAINT hft_raw_metrics_upsert
DO UPDATE SET
    n_30d       = EXCLUDED.n_30d,
    win_1a_30d  = EXCLUDED.win_1a_30d,
    win_g1_30d  = EXCLUDED.win_g1_30d,
    win_g2_30d  = EXCLUDED.win_g2_30d,
    hit_30d     = EXCLUDED.hit_30d,
    n_7d        = EXCLUDED.n_7d,
    win_1a_7d   = EXCLUDED.win_1a_7d,
    win_g1_7d   = EXCLUDED.win_g1_7d,
    win_g2_7d   = EXCLUDED.win_g2_7d,
    hit_7d      = EXCLUDED.hit_7d,
    n_3d        = EXCLUDED.n_3d,
    win_1a_3d   = EXCLUDED.win_1a_3d,
    win_g1_3d   = EXCLUDED.win_g1_3d,
    win_g2_3d   = EXCLUDED.win_g2_3d,
    hit_3d      = EXCLUDED.hit_3d,
    updated_at  = NOW();
"""


def upload(df: pd.DataFrame) -> dict:
    """
    Faz upsert do DataFrame na tabela hft_lake.hft_raw_metrics via psycopg2.
    Retorna dict com total inserido/atualizado.
    """
    registros = df.to_dict(orient="records")
    total = len(registros)
    inseridos = 0

    print(f"\n[UPLOADER] Enviando {total} registros para {TABELA}...")
    print(f"[UPLOADER] Batch size: {BATCH_SIZE} | Batches: {(total // BATCH_SIZE) + 1}\n")

    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = False

    try:
        cur = conn.cursor()

        for i in range(0, total, BATCH_SIZE):
            batch = registros[i:i + BATCH_SIZE]
            n_batch = len(batch)

            try:
                psycopg2.extras.execute_batch(cur, UPSERT_SQL, batch, page_size=n_batch)
                conn.commit()

                inseridos += n_batch
                pct = round(inseridos / total * 100, 1)
                print(f"[UPLOADER] Batch {i//BATCH_SIZE + 1} OK | {inseridos}/{total} ({pct}%)")

            except Exception as e:
                conn.rollback()
                print(f"[UPLOADER] ERRO no batch {i//BATCH_SIZE + 1}: {e}")
                raise

        cur.close()

    finally:
        conn.close()

    print(f"\n[UPLOADER] Upload completo: {inseridos}/{total} registros")
    return {"total": total, "inseridos": inseridos}


if __name__ == "__main__":
    from lake_loader import run_loader
    df = run_loader()
    upload(df)
