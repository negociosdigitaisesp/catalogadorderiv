"""Coleta estatisticas do catalog.db e config.json para o dashboard preview."""
import sqlite3, json, pathlib, sys

conn = sqlite3.connect('catalog/catalog.db')
total = conn.execute('SELECT COUNT(*) FROM candles').fetchone()[0]
por_ativo = conn.execute('SELECT ativo, COUNT(*) as n FROM candles GROUP BY ativo ORDER BY ativo').fetchall()
conn.close()

cfg_path = pathlib.Path('config.json')
grade = []
if cfg_path.exists():
    try:
        cfg = json.loads(cfg_path.read_text(encoding='utf-8'))
        grade = cfg.get('grade_horaria', [])
    except Exception as e:
        print(f'CONFIG_ERROR={e}')

n_total = len(grade)
n_aprov = sum(1 for g in grade if g.get('status') == 'APROVADO')
n_cond  = sum(1 for g in grade if g.get('status') == 'CONDICIONAL')

por_ativo_grade = {}
for g in grade:
    a = g.get('ativo', '?')
    por_ativo_grade[a] = por_ativo_grade.get(a, 0) + 1

top10 = sorted(grade, key=lambda x: x.get('win_rate_g2', 0), reverse=True)[:20]

print(f'TOTAL_CANDLES={total}')
print(f'GRADE_TOTAL={n_total}')
print(f'GRADE_APROVADO={n_aprov}')
print(f'GRADE_CONDICIONAL={n_cond}')

for a, n in sorted(por_ativo_grade.items()):
    print(f'ATIVO|{a}|{n}')

for a, n in por_ativo:
    print(f'CANDLES|{a}|{n}')

print('TOP20_START')
for g in top10:
    sid  = g.get('strategy_id', '?')
    ativ = g.get('ativo', '?')
    hhmm = g.get('hh_mm', '?')
    dir_ = g.get('direcao', '?')
    wr   = g.get('win_rate_g2', 0)
    ev   = g.get('ev_gale2', 0)
    st   = g.get('status', '?')
    p1   = g.get('win_1a_rate', 0)
    pg1  = g.get('win_gale1_rate', 0)
    pg2  = g.get('win_gale2_rate', 0)
    hit  = g.get('hit_rate', 0)
    print(f'{sid}|{ativ}|{hhmm}|{dir_}|{wr:.4f}|{ev:+.3f}|{st}|{p1:.3f}|{pg1:.3f}|{pg2:.3f}|{hit:.3f}')
print('TOP20_END')
