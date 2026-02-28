"""
scripts/apply_migration.py

Aplica a migration SQL diretamente no Supabase via psycopg2.
Equivalente ao `supabase db push` da CLI.

Uso:
    python scripts/apply_migration.py
"""

import os
import glob
import sys

from dotenv import load_dotenv

load_dotenv()

try:
    import psycopg2
except ImportError:
    print("[ERRO] psycopg2 não instalado: pip install psycopg2-binary")
    sys.exit(1)

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    print("[ERRO] DATABASE_URL não configurado no .env")
    sys.exit(1)

# Pasta de migrations
MIGRATIONS_DIR = os.path.join(os.path.dirname(__file__), "migrations")
migration_files = sorted(glob.glob(os.path.join(MIGRATIONS_DIR, "*.sql")))

if not migration_files:
    print("[MIGRATE] Nenhum arquivo .sql encontrado em scripts/migrations/")
    sys.exit(0)

print(f"[MIGRATE] Conectando ao banco...")
try:
    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = True
    cur = conn.cursor()
    print(f"[MIGRATE] Conexão estabelecida.")
except Exception as e:
    print(f"[ERRO] Falha ao conectar: {e}")
    sys.exit(1)

for sql_file in migration_files:
    filename = os.path.basename(sql_file)
    print(f"[MIGRATE] Aplicando: {filename}...")
    try:
        with open(sql_file, "r", encoding="utf-8") as f:
            sql = f.read()
        cur.execute(sql)
        print(f"[MIGRATE] ✓ {filename} aplicado com sucesso.")
    except Exception as e:
        print(f"[MIGRATE] ✗ Erro em {filename}: {e}")
        conn.close()
        sys.exit(1)

cur.close()
conn.close()
print("[MIGRATE] Todas as migrations aplicadas com sucesso!")
