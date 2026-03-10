#!/bin/bash
# =======================================================================
# deploy.sh — Script de instalação e start completo na VPS
# 
# Uso: bash deploy.sh
# Executar como root na VPS DigitalOcean
# IP: 68.183.216.216
# =======================================================================

set -e
PROJECT_DIR="$HOME/catalogadorderiv"
EXECDIR="$PROJECT_DIR/VPS_IQ_OPTION/executor"

echo "======================================"
echo " ORACLE QUANT — VPS Deploy"
echo "======================================"

# ── 1. Dependências do sistema ──────────────────────────────────────────
echo "[1/7] Instalando dependências do sistema..."
apt-get update -qq
apt-get install -y python3 python3-pip python3-venv tmux git rsync curl > /dev/null
echo "OK"

# ── 2. Criar virtualenv ────────────────────────────────────────────────
echo "[2/7] Configurando virtualenv..."
cd "$PROJECT_DIR"
python3 -m venv .venv
source .venv/bin/activate
pip install --quiet --upgrade pip
echo "OK"

# ── 3. Instalar dependências Python ───────────────────────────────────
echo "[3/7] Instalando requirements..."
pip install --quiet -r requirements.txt 2>/dev/null || true
pip install --quiet -r "$EXECDIR/requirements.txt" 2>/dev/null || true
echo "OK"

# ── 4. Validar .env ────────────────────────────────────────────────────
echo "[4/7] Verificando .env..."
if [ ! -f "$PROJECT_DIR/.env" ]; then
    echo "ERRO: .env não encontrado em $PROJECT_DIR"
    exit 1
fi
if grep -q "SUPABASE_URL=" "$PROJECT_DIR/.env"; then
    echo "  .env OK"
else
    echo "AVISO: SUPABASE_URL não encontrado no .env"
fi

# ── 5. Criar sessões tmux ──────────────────────────────────────────────
echo "[5/7] Configurando sessões tmux..."

# Matar sessões antigas se existirem
tmux kill-session -t deriv 2>/dev/null || true
tmux kill-session -t iq_sniper 2>/dev/null || true
tmux kill-session -t executor 2>/dev/null || true

sleep 1

# ── Sessão 1: Deriv Sniper ─────────────────────────────────────────────
tmux new-session -d -s deriv -x 220 -y 50
tmux send-keys -t deriv "cd $PROJECT_DIR && source .venv/bin/activate" Enter
tmux send-keys -t deriv "python run_sniper_lake.py 2>&1 | tee logs/deriv_sniper.log" Enter
echo "  [deriv] started"

# ── Sessão 2: IQ Sniper ────────────────────────────────────────────────
tmux new-session -d -s iq_sniper -x 220 -y 50
tmux send-keys -t iq_sniper "cd $PROJECT_DIR && source .venv/bin/activate" Enter
tmux send-keys -t iq_sniper "CLIENT_ID=\${CLIENT_ID:-GLOBAL} python run_iq_sniper.py 2>&1 | tee logs/iq_sniper.log" Enter
echo "  [iq_sniper] started"

# ── Sessão 3: Executor (Supervisor) ───────────────────────────────────
tmux new-session -d -s executor -x 220 -y 50
tmux send-keys -t executor "cd $EXECDIR && source $PROJECT_DIR/.venv/bin/activate" Enter
tmux send-keys -t executor "python main.py 2>&1 | tee $PROJECT_DIR/logs/executor.log" Enter
echo "  [executor] started"

# ── 6. Criar diretório de logs ─────────────────────────────────────────
mkdir -p "$PROJECT_DIR/logs"
echo "[6/7] Diretório de logs criado: $PROJECT_DIR/logs"

# ── 7. Status final ────────────────────────────────────────────────────
echo "[7/7] Sessões tmux ativas:"
tmux ls

echo ""
echo "======================================"
echo " Deploy concluído!"
echo " Comandos úteis:"
echo "   tmux attach -t deriv      → ver Deriv Sniper"
echo "   tmux attach -t iq_sniper  → ver IQ Sniper"
echo "   tmux attach -t executor   → ver Executor"
echo "   tail -f logs/executor.log → log do executor"
echo "======================================"
