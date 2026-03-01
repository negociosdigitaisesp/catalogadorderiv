"""
check_lake_health.py — Auditoria de Integridade do Data Lake (hft_lake)

Fluxo de auditoria:
  1. Tabela Mãe      → COUNT(*) em hft_raw_metrics (deve ser 14.400)
  2. View Principal  → COUNT(*) de APROVADO em vw_grade_unificada
  3. Amostra Elite   → Top 3 por ev_g2 DESC (Prova de Vida)
  4. Views FV1-FV5   → COUNT(*) em cada view intermediária

Usa psycopg2 (acesso direto ao SQL — mais rápido que API REST).
"""

import sys
import psycopg2
import psycopg2.extras

# ──────────────────────────────────────────────────────────────
# CONFIGURAÇÃO — conexão direta ao Supabase via PostgreSQL
# ──────────────────────────────────────────────────────────────
DB_URL = "postgresql://postgres:1CIwYGQv09MUQA@db.ypqekkkrfklaqlzhkbwg.supabase.co:5432/postgres"

# Volume esperado: 5 ativos × 1440 min × 2 direções
EXPECTED_RAW_COUNT = 14_400

# Views intermediárias (FV1 a FV5)
VIEWS_INTERMEDIARIAS = [
    ("FV1", "hft_lake.vw_fv1_minuto_solido"),
    ("FV2", "hft_lake.vw_fv2_minuto_de_primeira"),
    ("FV3", "hft_lake.vw_fv3_minuto_quente"),
    ("FV4", "hft_lake.vw_fv4_minuto_resiliente"),
    ("FV5", "hft_lake.vw_fv5_minuto_dominante"),
]

# Status de saída
ALL_OK = True


def sep(char="─", width=60):
    print(char * width)


def ok(msg):
    print(f"  ✅ [OK]  {msg}")


def warn(msg):
    global ALL_OK
    ALL_OK = False
    print(f"  ⚠️  [WARN] {msg}")


def err(msg):
    global ALL_OK
    ALL_OK = False
    print(f"  ❌ [ERRO] {msg}")


# ──────────────────────────────────────────────────────────────
# CONEXÃO
# ──────────────────────────────────────────────────────────────
def get_conn():
    try:
        conn = psycopg2.connect(DB_URL)
        conn.autocommit = True
        return conn
    except Exception as e:
        print(f"\n❌ Falha na conexão com o banco: {e}")
        sys.exit(1)


# ──────────────────────────────────────────────────────────────
# CHECK 1 — TABELA MÃE: hft_raw_metrics
# ──────────────────────────────────────────────────────────────
def check_tabela_mae(cur):
    sep()
    print("CHECK 1 — Tabela Mãe: hft_lake.hft_raw_metrics")
    sep()

    cur.execute("SELECT COUNT(*) FROM hft_lake.hft_raw_metrics;")
    count = cur.fetchone()[0]
    print(f"  → Registros encontrados: {count:,}")

    if count == EXPECTED_RAW_COUNT:
        ok(f"Tabela Mãe completa ({count:,} = 5 ativos × 1440 min × 2 direções)")
    elif count == 0:
        err("Tabela vazia! O pipeline provavelmente não rodou.")
    elif count < EXPECTED_RAW_COUNT:
        warn(f"Tabela incompleta: {count:,} de {EXPECTED_RAW_COUNT:,} esperados "
             f"(faltam {EXPECTED_RAW_COUNT - count:,})")
    else:
        warn(f"Tabela com mais linhas que o esperado: {count:,} > {EXPECTED_RAW_COUNT:,} "
             f"(verifique duplicatas)")

    # Breakdown por ativo
    cur.execute("""
        SELECT ativo, COUNT(*) AS n
        FROM hft_lake.hft_raw_metrics
        GROUP BY ativo
        ORDER BY ativo;
    """)
    rows = cur.fetchall()
    if rows:
        print("\n  Breakdown por ativo:")
        for ativo, n in rows:
            marker = "✅" if n == 2880 else "⚠️ "
            print(f"    {marker}  {ativo}: {n:,} linhas (esperado: 2.880)")
    print()


# ──────────────────────────────────────────────────────────────
# CHECK 2 — VIEW PRINCIPAL: vw_grade_unificada (APROVADO)
# ──────────────────────────────────────────────────────────────
def check_view_principal(cur):
    sep()
    print("CHECK 2 — View Principal: hft_lake.vw_grade_unificada")
    sep()

    cur.execute("""
        SELECT status, COUNT(*) AS n
        FROM hft_lake.vw_grade_unificada
        GROUP BY status
        ORDER BY n DESC;
    """)
    rows = cur.fetchall()

    aprovados = 0
    total = 0
    print("  Status breakdown:")
    for status, n in rows:
        print(f"    → {status}: {n:,} estratégias")
        total += n
        if status == "APROVADO":
            aprovados = n

    print(f"\n  → Total geral na grade: {total:,}")
    print(f"  → APROVADOS: {aprovados:,}")

    if aprovados == 0:
        err("Nenhuma estratégia APROVADA! Verifique os filtros das views SQL.")
    elif aprovados >= 100:
        ok(f"View Principal com {aprovados:,} estratégias APROVADAS")
    else:
        warn(f"Poucos aprovados: {aprovados:,}. Revise os thresholds das views FV.")
    print()


# ──────────────────────────────────────────────────────────────
# CHECK 3 — AMOSTRA ELITE: Top 3 por ev_g2 (Prova de Vida)
# ──────────────────────────────────────────────────────────────
def check_amostra_elite(cur):
    sep()
    print("CHECK 3 — Prova de Vida: Top 3 Estratégias (ev_g2 DESC)")
    sep()

    cur.execute("""
        SELECT
            ativo,
            hh_mm,
            direcao,
            ev_g2,
            wr_g2,
            wr_1a,
            n_total,
            n_filtros,
            filtros_aprovados,
            status
        FROM hft_lake.vw_grade_unificada
        ORDER BY ev_g2 DESC
        LIMIT 3;
    """)
    rows = cur.fetchall()
    cols = [desc[0] for desc in cur.description]

    if not rows:
        err("Nenhuma linha retornada pela vw_grade_unificada!")
        return

    for rank, row in enumerate(rows, 1):
        r = dict(zip(cols, row))
        print(f"\n  [RANK {rank}]")
        print(f"    Ativo    : {r['ativo']}")
        print(f"    Hora     : {r['hh_mm']}")
        print(f"    Direção  : {r['direcao']}")
        print(f"    EV G2    : {r['ev_g2']}")
        print(f"    WR G2    : {r['wr_g2']} ({round(float(r['wr_g2'])*100,1)}%)")
        print(f"    WR 1ª    : {r['wr_1a']} ({round(float(r['wr_1a'])*100,1)}%)")
        print(f"    N Total  : {r['n_total']}")
        print(f"    Filtros  : {r['n_filtros']} ({r['filtros_aprovados']})")
        print(f"    Status   : {r['status']}")

    ok("Amostra Elite retornada com sucesso")
    print()


# ──────────────────────────────────────────────────────────────
# CHECK 4 — VIEWS INTERMEDIÁRIAS: FV1 a FV5
# ──────────────────────────────────────────────────────────────
def check_views_intermediarias(cur):
    sep()
    print("CHECK 4 — Views Intermediárias: FV1 a FV5")
    sep()

    for nome, view in VIEWS_INTERMEDIARIAS:
        try:
            cur.execute(f"SELECT COUNT(*) FROM {view};")
            count = cur.fetchone()[0]
            if count > 0:
                ok(f"{nome} ({view.split('.')[-1]}): {count:,} linhas")
            else:
                err(f"{nome} ({view.split('.')[-1]}): 0 linhas — view vazia ou filtros muito restritivos")
        except Exception as e:
            err(f"{nome} ({view.split('.')[-1]}): Erro de compilação/execução → {e}")

    print()


# ──────────────────────────────────────────────────────────────
# RESULTADO FINAL
# ──────────────────────────────────────────────────────────────
def resultado_final():
    sep("═")
    if ALL_OK:
        print("🏆 AUDITORIA CONCLUÍDA — TODOS OS CHECKS PASSARAM")
        print("   O Data Lake está íntegro e pronto para uso no Sniper.")
    else:
        print("⚠️  AUDITORIA CONCLUÍDA COM ALERTAS/ERROS")
        print("   Revise os itens marcados com ❌ ou ⚠️  acima antes de ligar o Sniper.")
    sep("═")


# ──────────────────────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────────────────────
def main():
    sep("═")
    print("  🔍 CHECK_LAKE_HEALTH — Auditoria do Data Lake hft_lake")
    print("  Banco: Supabase (Catalogador Mayk)")
    sep("═")
    print()

    conn = get_conn()
    cur = conn.cursor()
    print("  ✅ Conexão estabelecida com sucesso!\n")

    try:
        check_tabela_mae(cur)
        check_view_principal(cur)
        check_amostra_elite(cur)
        check_views_intermediarias(cur)
    finally:
        cur.close()
        conn.close()

    resultado_final()


if __name__ == "__main__":
    main()
