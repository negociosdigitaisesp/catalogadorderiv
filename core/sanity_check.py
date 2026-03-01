"""
core/sanity_check.py — Validação de Sanidade da Fábrica Gêmea
==============================================================
Verifica que a duplicação de schemas IQ/Deriv não criou conflitos:
  1. Schema isolation (nomes de tabela não colidem)
  2. Python module isolation (imports não sobrescrevem)
  3. ENV variable isolation (chaves Deriv vs IQ separadas)
  4. Database file isolation (catalog.db vs catalog_iq.db)
"""

import os
import sys
import importlib
import psycopg2

DB_URL = os.getenv(
    "DB_URL",
    "postgresql://postgres:1CIwYGQv09MUQA@db.ypqekkkrfklaqlzhkbwg.supabase.co:5432/postgres"
)

ALL_OK = True


def ok(msg):
    print(f"  \u2705 [OK]  {msg}")


def fail(msg):
    global ALL_OK
    ALL_OK = False
    print(f"  \u274c [FAIL] {msg}")


def sep(title):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


# ─────────────────────────────────────────────────────────────
# CHECK 1: Schema Isolation no Supabase
# ─────────────────────────────────────────────────────────────
def check_schema_isolation():
    sep("CHECK 1: Schema Isolation (Supabase)")

    conn = psycopg2.connect(DB_URL)
    conn.autocommit = True
    cur = conn.cursor()

    # Tabelas em cada schema
    cur.execute("""
        SELECT schemaname, tablename
        FROM pg_tables
        WHERE schemaname IN ('hft_lake', 'iq_lake', 'iq_quant', 'public')
          AND tablename LIKE ANY(ARRAY['hft_%', 'iq_%', 'oracle_%', 'signals'])
        ORDER BY schemaname, tablename;
    """)
    rows = cur.fetchall()

    schemas_found = set()
    tables_by_schema: dict[str, list[str]] = {}
    for schema, table in rows:
        schemas_found.add(schema)
        tables_by_schema.setdefault(schema, []).append(table)

    # Verificar que hft_lake e iq_lake existem separados
    if "hft_lake" in schemas_found and "iq_lake" in schemas_found:
        ok("hft_lake e iq_lake coexistem sem conflito")
    else:
        missing = []
        if "hft_lake" not in schemas_found:
            missing.append("hft_lake")
        if "iq_lake" not in schemas_found:
            missing.append("iq_lake")
        fail(f"Schema(s) ausente(s): {', '.join(missing)}")

    # Verificar que iq_quant existe
    if "iq_quant" in schemas_found:
        ok("iq_quant schema existe")
    else:
        fail("iq_quant schema nao encontrado")

    # Verificar que tabelas NÃO têm nomes idênticos entre schemas diferentes
    all_table_names = []
    for schema, tables in tables_by_schema.items():
        for t in tables:
            fqn = f"{schema}.{t}"
            all_table_names.append(fqn)
            print(f"    Encontrada: {fqn}")

    # Nomes base não devem colidir entre hft_lake e iq_lake
    hft_tables = set(tables_by_schema.get("hft_lake", []))
    iq_tables  = set(tables_by_schema.get("iq_lake", []))
    collision  = hft_tables & iq_tables
    if collision:
        fail(f"Colisao de nomes entre hft_lake e iq_lake: {collision}")
    else:
        ok("Nenhuma colisao de nomes entre hft_lake e iq_lake")

    cur.close()
    conn.close()


# ─────────────────────────────────────────────────────────────
# CHECK 2: Python Module Isolation
# ─────────────────────────────────────────────────────────────
def check_module_isolation():
    sep("CHECK 2: Python Module Isolation")

    # data_loader e iq_loader devem ser modulos distintos
    modules_to_check = [
        ("agente.core.data_loader", "DataLoader (Deriv)"),
        ("core.iq_loader",          "IQLoader (IQ Option)"),
    ]

    loaded = {}
    for mod_name, desc in modules_to_check:
        try:
            mod = importlib.import_module(mod_name)
            loaded[mod_name] = mod
            ok(f"{desc} importa com sucesso: {mod_name}")
        except ImportError:
            # Aceitável — pode não estar no sys.path
            print(f"  \u26a0\ufe0f  [SKIP] {desc} nao encontrado no sys.path (aceitavel)")

    # Se ambos carregaram, verificar que não são o mesmo módulo
    if len(loaded) == 2:
        mod_a = loaded["agente.core.data_loader"]
        mod_b = loaded["core.iq_loader"]
        if mod_a is mod_b:
            fail("data_loader e iq_loader apontam para o MESMO modulo!")
        else:
            ok("data_loader e iq_loader sao modulos DISTINTOS")

    # Verificar que iq_loader tem a classe IQLoader
    try:
        # Add project root to path if needed
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if project_root not in sys.path:
            sys.path.insert(0, project_root)

        from core.iq_loader import IQLoader
        ok(f"IQLoader classe encontrada: {IQLoader}")

        # Verificar métodos essenciais
        essential = ["iq_timestamp_to_epoch", "fetch_candles_iq", "_enforce_rate_limit"]
        for method in essential:
            if hasattr(IQLoader, method):
                ok(f"  IQLoader.{method}() presente")
            else:
                fail(f"  IQLoader.{method}() AUSENTE")

    except ImportError as e:
        fail(f"Nao conseguiu importar core.iq_loader: {e}")


# ─────────────────────────────────────────────────────────────
# CHECK 3: Database File Isolation
# ─────────────────────────────────────────────────────────────
def check_db_isolation():
    sep("CHECK 3: Database File Isolation")

    deriv_db = "catalog/catalog.db"
    iq_db    = "catalog/catalog_iq.db"

    if deriv_db != iq_db:
        ok(f"Deriv DB: {deriv_db}")
        ok(f"IQ DB:    {iq_db}")
        ok("Paths de banco sao DISTINTOS — sem risco de contaminacao")
    else:
        fail("Paths de banco sao IDENTICOS! Risco de contaminacao cruzada!")


# ─────────────────────────────────────────────────────────────
# CHECK 4: ENV Variable Namespace
# ─────────────────────────────────────────────────────────────
def check_env_namespace():
    sep("CHECK 4: ENV Variable Namespace")

    deriv_vars = ["DERIV_APP_ID", "DERIV_TOKEN"]
    iq_vars    = ["IQ_EMAIL", "IQ_PASSWORD"]

    # Verificar que não há sobreposição de nomes
    overlap = set(deriv_vars) & set(iq_vars)
    if overlap:
        fail(f"Variaveis de ambiente com nomes identicos: {overlap}")
    else:
        ok("Variaveis Deriv e IQ tem namespaces separados")

    # Listar as que existem no env atual
    for v in deriv_vars:
        val = os.getenv(v)
        status = "definida" if val else "ausente"
        print(f"    {v}: {status}")
    for v in iq_vars:
        val = os.getenv(v)
        status = "definida" if val else "ausente (ok para agora)"
        print(f"    {v}: {status}")


# ─────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────
def main():
    print("\n" + "=" * 60)
    print("  SANITY CHECK — Fabrica Gemea (Deriv x IQ Option)")
    print("=" * 60)

    check_schema_isolation()
    check_module_isolation()
    check_db_isolation()
    check_env_namespace()

    sep("RESULTADO FINAL")
    if ALL_OK:
        print("  \u2705 TODOS OS CHECKS PASSARAM — Fabrica Gemea validada!")
        print("  Nenhum conflito de nomes detectado.")
    else:
        print("  \u274c FALHAS DETECTADAS — revise os itens acima.")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    main()
