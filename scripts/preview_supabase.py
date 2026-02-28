"""
Preview: hft_oracle_results — Conecta no Supabase e mostra tudo organizado por ativo.
"""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def preview():
    try:
        import psycopg2
    except ImportError:
        print("Instalando psycopg2-binary...")
        import subprocess
        subprocess.check_call([sys.executable, "-m", "pip", "install", "psycopg2-binary", "-q"])
        import psycopg2

    conn_str = "postgresql://postgres:1CIwYGQv09MUQA@db.ypqekkkrfklaqlzhkbwg.supabase.co:5432/postgres"
    print("Conectando ao Supabase...")
    conn = psycopg2.connect(conn_str, sslmode="require")
    cur = conn.cursor()

    # ── Total de registros ────────────────────────────────────────────────
    cur.execute("SELECT COUNT(*) FROM public.hft_oracle_results")
    total = cur.fetchone()[0]
    print(f"\n{'='*80}")
    print(f"  PREVIEW: public.hft_oracle_results  ({total} registros)")
    print(f"{'='*80}")

    if total == 0:
        print("\n  ⚠️  Tabela vazia. Rode a migração e o catalogar_completo.py primeiro.")
        cur.close()
        conn.close()
        return

    # ── Resumo por ativo ──────────────────────────────────────────────────
    cur.execute("""
        SELECT 
            ativo,
            COUNT(*) as total,
            COUNT(*) FILTER (WHERE status = 'APROVADO')    as aprovados,
            COUNT(*) FILTER (WHERE status = 'CONDICIONAL') as condicionais,
            COUNT(*) FILTER (WHERE status = 'REPROVADO')   as reprovados,
            ROUND(AVG(win_rate)::numeric, 4) as avg_wr,
            ROUND(AVG(ev_real)::numeric, 4)  as avg_ev
        FROM public.hft_oracle_results
        GROUP BY ativo
        ORDER BY ativo
    """)
    rows = cur.fetchall()

    print(f"\n  {'ATIVO':<12} {'Total':>6} {'✅Aprov':>8} {'⚠️Cond':>8} {'❌Repr':>8} {'WR Média':>10} {'EV Médio':>10}")
    print(f"  {'─'*12} {'─'*6} {'─'*8} {'─'*8} {'─'*8} {'─'*10} {'─'*10}")
    for row in rows:
        ativo, tot, apr, cond, rep, avg_wr, avg_ev = row
        print(f"  {ativo:<12} {tot:>6} {apr:>8} {cond:>8} {rep:>8} {float(avg_wr):>9.2%} {float(avg_ev):>+10.4f}")

    # ── Detalhes por ativo (organizado) ───────────────────────────────────
    cur.execute("""
        SELECT 
            ativo, strategy_id, variacao_estrategia,
            win_rate, ev_real, status, sizing_override,
            n_win_1a, n_win_g1, n_win_g2, n_hit, n_total,
            (config_otimizada->>'hh_mm') as hh_mm,
            (config_otimizada->>'direcao') as direcao
        FROM public.hft_oracle_results
        ORDER BY ativo, win_rate DESC
    """)
    all_rows = cur.fetchall()

    current_ativo = None
    for row in all_rows:
        (ativo, sid, var, wr, ev, status, stake,
         n1a, ng1, ng2, nhit, ntotal, hhmm, direcao) = row

        if ativo != current_ativo:
            current_ativo = ativo
            print(f"\n  {'='*78}")
            print(f"  📊 {ativo}")
            print(f"  {'='*78}")
            print(f"  {'Hora':<7} {'Dir':<5} {'Var':<4} {'WR G2':>7} {'EV':>8} {'1ª':>4} {'G1':>4} {'G2':>4} {'HIT':>4} {'N':>5} {'Status':<12} {'Stake':>5}")
            print(f"  {'─'*7} {'─'*5} {'─'*4} {'─'*7} {'─'*8} {'─'*4} {'─'*4} {'─'*4} {'─'*4} {'─'*5} {'─'*12} {'─'*5}")

        wr_f   = float(wr) if wr else 0
        ev_f   = float(ev) if ev else 0
        stk_f  = float(stake) if stake else 0
        var_s  = var or "?"
        hhmm_s = hhmm or "?"
        dir_s  = direcao or "?"
        n1a    = n1a or 0
        ng1    = ng1 or 0
        ng2    = ng2 or 0
        nhit   = nhit or 0
        ntotal = ntotal or 0

        icon = "✅" if status == "APROVADO" else "⚠️" if status == "CONDICIONAL" else "❌"
        print(f"  {hhmm_s:<7} {dir_s:<5} {var_s:<4} {wr_f:>6.1%} {ev_f:>+8.4f} {n1a:>4} {ng1:>4} {ng2:>4} {nhit:>4} {ntotal:>5} {icon}{status:<11} {stk_f:>5.1f}")

    # ── Colunas disponíveis ───────────────────────────────────────────────
    cur.execute("""
        SELECT column_name, data_type 
        FROM information_schema.columns 
        WHERE table_name = 'hft_oracle_results' 
        ORDER BY ordinal_position
    """)
    cols = cur.fetchall()
    print(f"\n  {'='*78}")
    print(f"  📋 Schema da tabela ({len(cols)} colunas):")
    print(f"  {'='*78}")
    for cname, ctype in cols:
        print(f"    {cname:<30} {ctype}")

    cur.close()
    conn.close()
    print(f"\n{'='*80}")
    print(f"  Preview concluído.")
    print(f"{'='*80}\n")


if __name__ == "__main__":
    preview()
