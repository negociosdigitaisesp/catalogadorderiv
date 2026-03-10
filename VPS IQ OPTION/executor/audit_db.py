"""
audit_db.py — Agente Auditor: Fase 1 — Queries de Auditoria do Banco
"""
import httpx
import time
import json
from collections import Counter

URL = "https://ypqekkkrfklaqlzhkbwg.supabase.co"
KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InlwcWVra2tyZmtsYXFsemhrYndnIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc3MjAzMTcxMiwiZXhwIjoyMDg3NjA3NzEyfQ.dToc9a9Pb_D3eYXCcRQzL4KcGoxE-UYvsM3NI4krsjs"
H = {
    "apikey": KEY,
    "Authorization": f"Bearer {KEY}",
    "Content-Type": "application/json",
}

print("=" * 80)
print("FASE 1 — AUDITORIA DO BANCO SUPABASE HFT")
print("=" * 80)

# Q1: Stake real de cada cliente (iq_session_config)
print("\n--- Q1: SESSION CONFIG (stake, stop_win, stop_loss) ---")
r = httpx.get(f"{URL}/rest/v1/iq_session_config?select=*", headers=H, timeout=30)
print(f"Status: {r.status_code}")
print(json.dumps(r.json(), indent=2, ensure_ascii=False))

# Q2: estrategia_ativa de cada cliente (bot_clients)
print("\n--- Q2: BOT CLIENTS (client_id, estrategia_ativa, is_running, balance_type) ---")
r = httpx.get(
    f"{URL}/rest/v1/bot_clients?select=client_id,estrategia_ativa,is_running,balance_type,iq_email",
    headers=H, timeout=30,
)
print(f"Status: {r.status_code}")
data = r.json()
for row in data:
    # Mask email for privacy
    email = row.get("iq_email", "")
    if email and "@" in email:
        local, domain = email.split("@", 1)
        row["iq_email"] = f"{local[0]}***@{domain}"
    print(json.dumps(row, indent=2, ensure_ascii=False))

# Q3: Sinais CONFIRMED recentes (últimos 5 minutos)
print("\n--- Q3: SINAIS CONFIRMED (últimos 5 minutos) ---")
cutoff = int(time.time()) - 300
r = httpx.get(
    f"{URL}/rest/v1/iq_quant_signals?status=eq.CONFIRMED&timestamp_sinal=gte.{cutoff}"
    f"&select=id,ativo,estrategia,direcao,client_id,stake,status,timestamp_sinal"
    f"&order=created_at.desc&limit=20",
    headers=H, timeout=30,
)
print(f"Status: {r.status_code}")
print(json.dumps(r.json(), indent=2, ensure_ascii=False))

# Q3b: Sinais com status minúsculo "confirmed"
print("\n--- Q3b: SINAIS com status='confirmed' (minúsculo) últimos 30 min ---")
cutoff30 = int(time.time()) - 1800
r = httpx.get(
    f"{URL}/rest/v1/iq_quant_signals?status=eq.confirmed&timestamp_sinal=gte.{cutoff30}"
    f"&select=id,ativo,estrategia,direcao,client_id,status,timestamp_sinal"
    f"&order=created_at.desc&limit=20",
    headers=H, timeout=30,
)
print(f"Status: {r.status_code}")
print(json.dumps(r.json(), indent=2, ensure_ascii=False))

# Q4: Todos valores distintos de status nos sinais
print("\n--- Q4: VALORES DISTINTOS DE STATUS nos sinais (últimas 24h) ---")
r = httpx.get(
    f"{URL}/rest/v1/iq_quant_signals?select=status&order=created_at.desc&limit=200",
    headers=H, timeout=30,
)
print(f"Status HTTP: {r.status_code}")
status_values = list(set(s.get("status", "NULL") for s in r.json()))
print(f"Status distintos: {status_values}")

# Q4b: Valores distintos de estrategia nos sinais
print("\n--- Q4b: VALORES DISTINTOS DE ESTRATEGIA nos sinais ---")
r = httpx.get(
    f"{URL}/rest/v1/iq_quant_signals?select=estrategia&order=created_at.desc&limit=200",
    headers=H, timeout=30,
)
print(f"Status HTTP: {r.status_code}")
estrategias = list(set(s.get("estrategia", "NULL") for s in r.json()))
print(f"Estratégias distintas: {estrategias}")

# Q5: Últimas 30 operações (iq_trade_results)
print("\n--- Q5: ÚLTIMAS 30 OPERAÇÕES (iq_trade_results) ---")
r = httpx.get(
    f"{URL}/rest/v1/iq_trade_results?select=created_at,ativo,gale_level,stake,resultado,signal_id,client_id"
    f"&order=created_at.desc&limit=30",
    headers=H, timeout=30,
)
print(f"Status: {r.status_code}")
trades = r.json()
print(json.dumps(trades, indent=2, ensure_ascii=False))

# Q6: Gale state atual
print("\n--- Q6: GALE STATE ATUAL ---")
r = httpx.get(
    f"{URL}/rest/v1/iq_gale_state?select=*&order=created_at.desc",
    headers=H, timeout=30,
)
print(f"Status: {r.status_code}")
print(json.dumps(r.json(), indent=2, ensure_ascii=False))

# Q7: Sinais duplicados (mesmo signal_id executado mais de 1x)
print("\n--- Q7: DUPLICAÇÕES (signal_id repetido em trade_results) ---")
r = httpx.get(
    f"{URL}/rest/v1/iq_trade_results?select=signal_id&order=created_at.desc&limit=200",
    headers=H, timeout=30,
)
print(f"Status: {r.status_code}")
dupes = {k: v for k, v in Counter(x.get("signal_id") for x in r.json()).items() if v > 1}
print(f"Duplicações: {json.dumps(dupes, indent=2)}")

# Q8: Sinais presos em "executing"
print("\n--- Q8: SINAIS PRESOS EM 'executing' ---")
r = httpx.get(
    f"{URL}/rest/v1/iq_quant_signals?status=eq.executing&select=id,ativo,estrategia,created_at,status",
    headers=H, timeout=30,
)
print(f"Status: {r.status_code}")
print(json.dumps(r.json(), indent=2, ensure_ascii=False))

# Q9: Checar se existem sinais com client_id=GLOBAL
print("\n--- Q9: SINAIS COM client_id='GLOBAL' (últimos 200) ---")
r = httpx.get(
    f"{URL}/rest/v1/iq_quant_signals?client_id=eq.GLOBAL&select=id,ativo,estrategia,status,client_id,timestamp_sinal"
    f"&order=created_at.desc&limit=20",
    headers=H, timeout=30,
)
print(f"Status: {r.status_code}")
print(json.dumps(r.json(), indent=2, ensure_ascii=False))

# Q10: Sinais recentes (qualquer status) para ver o padrão completo
print("\n--- Q10: ÚLTIMOS 20 SINAIS (qualquer status) ---")
r = httpx.get(
    f"{URL}/rest/v1/iq_quant_signals?select=id,ativo,estrategia,direcao,status,client_id,stake,timestamp_sinal"
    f"&order=created_at.desc&limit=20",
    headers=H, timeout=30,
)
print(f"Status: {r.status_code}")
print(json.dumps(r.json(), indent=2, ensure_ascii=False))

# Q11: Checar todas as tabelas existentes (schema check)
print("\n--- Q11: TABELAS DO SCHEMA (introspection) ---")
# Supabase supports OpenAPI schema introspection
r = httpx.get(f"{URL}/rest/v1/", headers=H, timeout=30)
print(f"Status: {r.status_code}")
if r.status_code == 200:
    try:
        schema = r.json()
        if isinstance(schema, dict) and "definitions" in schema:
            tables = list(schema["definitions"].keys())
            print(f"Tabelas encontradas: {tables}")
        else:
            print(f"Response type: {type(schema)}")
            print(str(schema)[:500])
    except Exception:
        print(f"Response: {r.text[:500]}")

print("\n" + "=" * 80)
print("FASE 1 COMPLETA")
print("=" * 80)
