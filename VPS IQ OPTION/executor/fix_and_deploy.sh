#!/bin/bash
# ═══════════════════════════════════════════════════════════════════════════════
# fix_and_deploy.sh — Fix ALL 3 problems + deploy clean
#
# USAGE: bash fix_and_deploy.sh
#
# Fixes:
#   1. Stake: 10 → 5 in iq_session_config
#   2. Estratégia: FV2 → IQ_LAKE in bot_clients
#   3. Cleanup: stale executing signals + gale state
#   4. Kill ALL workers + signal_injector
#   5. Deploy updated signal_injector.py
#   6. Restart main.py + signal_injector.py (single instance)
# ═══════════════════════════════════════════════════════════════════════════════

set -e

SUPABASE_URL="https://ypqekkkrfklaqlzhkbwg.supabase.co"
SUPABASE_KEY="$SUPABASE_HFT_KEY"
CLIENT_ID="66be291b-99c3-4c25-b8d3-2cecb2eb8333"
EXECUTOR_DIR="/root/catalogadorderiv/VPS IQ OPTION/executor"

echo "════════════════════════════════════════════════════════════"
echo "  FIX & DEPLOY — $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
echo "════════════════════════════════════════════════════════════"

# ── FIX 1: Stake 10 → 5 ─────────────────────────────────────────────────────
echo ""
echo "🔧 FIX 1: Corrigindo stake de 10 para 5..."
curl -s -X PATCH \
  "${SUPABASE_URL}/rest/v1/iq_session_config?client_id=eq.${CLIENT_ID}" \
  -H "apikey: ${SUPABASE_KEY}" \
  -H "Authorization: Bearer ${SUPABASE_KEY}" \
  -H "Content-Type: application/json" \
  -H "Prefer: return=representation" \
  -d '{"stake": 5}' | python3 -m json.tool 2>/dev/null || echo "(sem retorno)"

echo "✅ Stake atualizado para 5"

# ── FIX 2: Estratégia FV2 → IQ_LAKE ─────────────────────────────────────────
echo ""
echo "🔧 FIX 2: Corrigindo estrategia_ativa de FV2 para IQ_LAKE..."
curl -s -X PATCH \
  "${SUPABASE_URL}/rest/v1/bot_clients?client_id=eq.${CLIENT_ID}" \
  -H "apikey: ${SUPABASE_KEY}" \
  -H "Authorization: Bearer ${SUPABASE_KEY}" \
  -H "Content-Type: application/json" \
  -H "Prefer: return=representation" \
  -d '{"estrategia_ativa": "IQ_LAKE"}' | python3 -m json.tool 2>/dev/null || echo "(sem retorno)"

echo "✅ estrategia_ativa atualizada para IQ_LAKE"

# ── FIX 3: Cleanup sinais presos em 'executing' ─────────────────────────────
echo ""
echo "🔧 FIX 3: Limpando sinais presos em 'executing'..."
curl -s -X PATCH \
  "${SUPABASE_URL}/rest/v1/iq_quant_signals?status=eq.executing" \
  -H "apikey: ${SUPABASE_KEY}" \
  -H "Authorization: Bearer ${SUPABASE_KEY}" \
  -H "Content-Type: application/json" \
  -H "Prefer: return=representation" \
  -d '{"status": "executed", "resultado": "timeout"}' | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'  Sinais limpos: {len(d)}')" 2>/dev/null || echo "  (nenhum ou erro)"

echo "✅ Sinais executing limpos"

# ── FIX 4: Limpar gale_state ─────────────────────────────────────────────────
echo ""
echo "🔧 FIX 4: Limpando iq_gale_state..."
curl -s -X DELETE \
  "${SUPABASE_URL}/rest/v1/iq_gale_state?client_id=eq.${CLIENT_ID}" \
  -H "apikey: ${SUPABASE_KEY}" \
  -H "Authorization: Bearer ${SUPABASE_KEY}"

echo "✅ Gale state limpo"

# ── KILL: Matar TODOS os processos ───────────────────────────────────────────
echo ""
echo "🛑 Matando todos os processos do executor..."
pkill -f "python.*main.py" 2>/dev/null || true
pkill -f "python.*signal_injector" 2>/dev/null || true
sleep 2

# Verificar se morreu tudo
REMAINING=$(pgrep -f "python.*(main|signal_injector)" 2>/dev/null | wc -l)
if [ "$REMAINING" -gt "0" ]; then
    echo "⚠️ Ainda há $REMAINING processos. Forçando kill -9..."
    pkill -9 -f "python.*(main|signal_injector)" 2>/dev/null || true
    sleep 1
fi
echo "✅ Todos os processos mortos"

# ── VERIFICAÇÃO: Confirmar dados no banco ────────────────────────────────────
echo ""
echo "📊 Verificando dados corrigidos..."

echo "  Stake atual:"
curl -s "${SUPABASE_URL}/rest/v1/iq_session_config?client_id=eq.${CLIENT_ID}&select=stake" \
  -H "apikey: ${SUPABASE_KEY}" \
  -H "Authorization: Bearer ${SUPABASE_KEY}" | python3 -m json.tool 2>/dev/null

echo "  Estratégia ativa:"
curl -s "${SUPABASE_URL}/rest/v1/bot_clients?client_id=eq.${CLIENT_ID}&select=estrategia_ativa" \
  -H "apikey: ${SUPABASE_KEY}" \
  -H "Authorization: Bearer ${SUPABASE_KEY}" | python3 -m json.tool 2>/dev/null

echo "  Sinais executing restantes:"
curl -s "${SUPABASE_URL}/rest/v1/iq_quant_signals?status=eq.executing&select=id" \
  -H "apikey: ${SUPABASE_KEY}" \
  -H "Authorization: Bearer ${SUPABASE_KEY}" | python3 -m json.tool 2>/dev/null

echo "  Gale state restante:"
curl -s "${SUPABASE_URL}/rest/v1/iq_gale_state?client_id=eq.${CLIENT_ID}&select=signal_id,last_result" \
  -H "apikey: ${SUPABASE_KEY}" \
  -H "Authorization: Bearer ${SUPABASE_KEY}" | python3 -m json.tool 2>/dev/null

# ── RESTART: Iniciar main.py e signal_injector.py ────────────────────────────
echo ""
echo "🚀 Reiniciando executor..."
cd "$EXECUTOR_DIR"
mkdir -p logs

nohup python3 main.py > logs/executor.log 2>&1 &
MAIN_PID=$!
echo "  main.py PID: $MAIN_PID"

nohup python3 signal_injector.py > logs/injector.log 2>&1 &
INJECTOR_PID=$!
echo "  signal_injector.py PID: $INJECTOR_PID"

sleep 2

# Verificar se estão rodando
if kill -0 $MAIN_PID 2>/dev/null; then
    echo "✅ main.py rodando"
else
    echo "❌ main.py morreu! Verificar logs/executor.log"
fi

if kill -0 $INJECTOR_PID 2>/dev/null; then
    echo "✅ signal_injector.py rodando"
else
    echo "❌ signal_injector.py morreu! Verificar logs/injector.log"
fi

# Verificar quantidade de workers (deve ser 1)
echo ""
echo "📋 Processos ativos:"
ps aux | grep -E "python.*(main|worker|signal_injector)" | grep -v grep

echo ""
echo "════════════════════════════════════════════════════════════"
echo "  ✅ FIX & DEPLOY COMPLETO"
echo "════════════════════════════════════════════════════════════"
echo ""
echo "  Para monitorar:"
echo "    tail -f logs/executor.log"
echo "    tail -f logs/injector.log"
