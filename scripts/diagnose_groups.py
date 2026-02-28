"""Diagnostic script to analyze group sizes in catalog.db"""
import sqlite3

conn = sqlite3.connect('catalog/catalog.db')

# V1 groups: (ativo, hh_mm, dia_semana)
rows = conn.execute(
    "SELECT ativo, hh_mm, dia_semana, COUNT(*) as n "
    "FROM candles "
    "GROUP BY ativo, hh_mm, dia_semana "
    "ORDER BY n DESC LIMIT 15"
).fetchall()
print("=== TOP 15 V1 groups (ativo, hh_mm, dia_semana) ===")
for r in rows:
    print(f"  {r[0]:12s} | {r[1]} | day={r[2]} | N={r[3]}")

# Groups WITHOUT dia_semana
rows2 = conn.execute(
    "SELECT ativo, hh_mm, COUNT(*) as n "
    "FROM candles "
    "GROUP BY ativo, hh_mm "
    "ORDER BY n DESC LIMIT 10"
).fetchall()
print()
print("=== TOP 10 groups (ativo, hh_mm) -- sem dia_semana ===")
for r in rows2:
    print(f"  {r[0]:12s} | {r[1]} | N={r[2]}")

# Biggest groups with their WR
rows3 = conn.execute(
    "SELECT ativo, hh_mm, COUNT(*) as n, "
    "SUM(CASE WHEN proxima_1='VERDE' THEN 1 ELSE 0 END) as v, "
    "SUM(CASE WHEN proxima_1='VERMELHA' THEN 1 ELSE 0 END) as vm "
    "FROM candles WHERE proxima_1 != '?' "
    "GROUP BY ativo, hh_mm ORDER BY n DESC LIMIT 20"
).fetchall()
print()
print("=== WR proxima_1 por (ativo, hh_mm) ===")
for r in rows3:
    ativo, hhmm, n, v, vm = r
    wr = v / n if n else 0
    print(f"  {ativo:12s} | {hhmm} | N={n:4d} | VERDE={v} ({wr:.1%}) | VERMELHA={vm}")

# Check Gale2 effective WR on (ativo, hh_mm) groups with N>=15
print()
print("=== Gale2 WR por (ativo, hh_mm) com N>=15 ===")
rows4 = conn.execute(
    "SELECT ativo, hh_mm, COUNT(*) as n, "
    "SUM(CASE WHEN proxima_1='VERDE' THEN 1 "
    "         WHEN proxima_2='VERDE' THEN 1 "
    "         WHEN proxima_3='VERDE' THEN 1 "
    "         ELSE 0 END) as wins "
    "FROM candles WHERE proxima_1 != '?' AND proxima_2 != '?' AND proxima_3 != '?' "
    "GROUP BY ativo, hh_mm HAVING n >= 15 ORDER BY 1.0*wins/n DESC LIMIT 30"
).fetchall()
for r in rows4:
    ativo, hhmm, n, wins = r
    wr = wins / n if n else 0
    print(f"  {ativo:12s} | {hhmm} | N={n:4d} | WR_G2={wr:.1%}")

conn.close()
