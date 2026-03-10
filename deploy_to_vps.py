"""
deploy_to_vps.py — Deploy completo para VPS DigitalOcean
=========================================================

Precisa de: pip install paramiko

Uso:
    python deploy_to_vps.py

O que faz:
1. Cria arquivo .tar.gz do projeto
2. Envia para a VPS via SFTP
3. Extrai e roda deploy.sh remotamente (instalação + tmux)
"""
import os
import sys
import tarfile
import tempfile
import paramiko

VPS_IP   = "173.212.209.45"
VPS_USER = "root"
VPS_PASS = "NqBxE5RrCwSd"
KEY_PATH = os.path.expanduser("~/.ssh/id_ed25519")

LOCAL_ROOT = r"C:\Users\brend\Videos\catalogadorderiv\catalogadorderiv"
REMOTE_DIR = "/root/catalogadorderiv"

# Pastas/arquivos a excluir do tarball
EXCLUDE = {
    "__pycache__", ".git", ".venv", "venv", "node_modules",
    ".pytest_cache", "*.pyc", "*.pyo", "catalog.db",
    "logs", ".env",  # .env enviado separado com segurança
}


def connect(key_path=None, password=None):
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    kwargs = dict(hostname=VPS_IP, username=VPS_USER, timeout=20,
                  allow_agent=False, look_for_keys=False)
    if key_path:
        kwargs["key_filename"] = key_path
    else:
        kwargs["password"] = password
    ssh.connect(**kwargs)
    return ssh


def run(ssh, cmd, check=True):
    print(f"-> {cmd[:80]}")
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=120)
    out = stdout.read().decode().strip()
    err = stderr.read().decode().strip()
    if out: print("  " + out[:600])
    if err: print("  ERR:" + err[:400])
    return out


def build_tarball(local_root, exclude_dirs):
    tmp = tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False)
    tmp.close()
    print(f"Building tarball -> {tmp.name}")
    with tarfile.open(tmp.name, "w:gz") as tar:
        for root, dirs, files in os.walk(local_root):
            # prune excluded dirs
            dirs[:] = [d for d in dirs if d not in exclude_dirs and not d.startswith(".")]
            for file in files:
                if any(file.endswith(ext) for ext in [".pyc", ".pyo", ".db"]): continue
                full = os.path.join(root, file)
                arcname = os.path.relpath(full, os.path.dirname(local_root))
                tar.add(full, arcname=arcname)
    size_mb = os.path.getsize(tmp.name) / 1024 / 1024
    print(f"Tarball ready: {size_mb:.1f} MB")
    return tmp.name


def send_file(ssh, local_path, remote_path):
    sftp = ssh.open_sftp()
    size = os.path.getsize(local_path)
    print(f"Uploading {size/1024/1024:.1f} MB -> {remote_path}")
    sftp.put(local_path, remote_path)
    sftp.close()
    print("Upload complete.")


def send_env(ssh, local_env_path, remote_env_path):
    """Envia .env separado para não incluir em tar."""
    sftp = ssh.open_sftp()
    sftp.put(local_env_path, remote_env_path)
    sftp.close()
    print(f".env sent to {remote_env_path}")


def main():
    # ── Conectar ────────────────────────────────────────────────────────
    print("Connecting to VPS...")
    ssh = None
    for method, kw in [
        ("SSH Key", dict(key_path=KEY_PATH)),
        ("Password", dict(password=VPS_PASS)),
    ]:
        try:
            ssh = connect(**kw)
            print(f"[OK] Connected via {method}")
            break
        except paramiko.ssh_exception.AuthenticationException as e:
            # Maybe the system enforces a password change on first login?
            print(f"[FAIL] {method}: Authentication failed.")
        except Exception as e:
            print(f"[FAIL] {method}: {e}")

    if not ssh:
        print("""
ERROR: Nao foi possivel conectar a VPS.

Troubleshooting:
1. No painel DigitalOcean -> seu Droplet -> Access -> Reset Root Password
2. Ou: DigitalOcean -> Droplet -> Access -> Launch Droplet Console
   E entao habilite senha: passwd root
""")
        sys.exit(1)

    # ── Verificar ambiente ────────────────────────────────────────────
    print("\n=== Ambiente VPS ===")
    run(ssh, "uname -a")
    run(ssh, "python3 --version || python --version")
    run(ssh, "tmux -V")

    # ── Preparar diretório ────────────────────────────────────────────
    run(ssh, f"mkdir -p {REMOTE_DIR} /root/catalogadorderiv/logs")

    # ── Build e enviar tarball ────────────────────────────────────────
    tarball = build_tarball(LOCAL_ROOT, EXCLUDE)
    remote_tar = "/tmp/catalogadorderiv.tar.gz"
    send_file(ssh, tarball, remote_tar)
    os.unlink(tarball)

    # ── Extrair ───────────────────────────────────────────────────────
    print("\n=== Extraindo projeto ===")
    run(ssh, f"tar -xzf {remote_tar} -C /root/ --overwrite")
    run(ssh, f"ls {REMOTE_DIR}")

    # ── Enviar .env ───────────────────────────────────────────────────
    local_env = os.path.join(LOCAL_ROOT, ".env")
    if os.path.exists(local_env):
        send_env(ssh, local_env, f"{REMOTE_DIR}/.env")

    # ── Instalar dependências ─────────────────────────────────────────
    print("\n=== Instalando dependências ===")
    run(ssh, f"cd {REMOTE_DIR} && python3 -m venv .venv")
    run(ssh, f"cd {REMOTE_DIR} && .venv/bin/pip install --quiet --upgrade pip")
    run(ssh, f"cd {REMOTE_DIR} && .venv/bin/pip install --quiet -r requirements.txt 2>&1 | tail -5")

    EXECDIR = f"{REMOTE_DIR}/VPS\\ IQ\\ OPTION/executor"
    run(ssh, f"ls '{REMOTE_DIR}/VPS IQ OPTION/executor/'")
    run(ssh, f"cd '{REMOTE_DIR}/VPS IQ OPTION/executor' && {REMOTE_DIR}/.venv/bin/pip install --quiet -r requirements.txt 2>&1 | tail -5")

    # ── Parar sessões antigas e iniciar novas ─────────────────────────
    print("\n=== Iniciando sessões tmux ===")
    for sess in ["deriv", "iq_sniper", "executor"]:
        run(ssh, f"tmux kill-session -t {sess} 2>/dev/null || true")

    VENV = f"{REMOTE_DIR}/.venv/bin"

    # Deriv Sniper
    run(ssh, f"tmux new-session -d -s deriv -x 220 -y 50")
    run(ssh, f"""tmux send-keys -t deriv "cd {REMOTE_DIR} && {VENV}/python run_sniper_lake.py >> logs/deriv.log 2>&1" Enter""")

    # IQ Sniper
    run(ssh, f"tmux new-session -d -s iq_sniper -x 220 -y 50")
    run(ssh, f"""tmux send-keys -t iq_sniper "cd {REMOTE_DIR} && CLIENT_ID=GLOBAL {VENV}/python run_iq_sniper.py >> logs/iq_sniper.log 2>&1" Enter""")

    # Executor
    run(ssh, f"tmux new-session -d -s executor -x 220 -y 50")
    run(ssh, f"""tmux send-keys -t executor "cd '{REMOTE_DIR}/VPS IQ OPTION/executor' && {VENV}/python main.py >> {REMOTE_DIR}/logs/executor.log 2>&1" Enter""")

    print("\n=== Sessões ativas ===")
    run(ssh, "tmux ls")

    print("""
====================================================
 DEPLOY CONCLUÍDO ✅
 
 Para acompanhar logs:
   tmux attach -t deriv
   tmux attach -t iq_sniper
   tmux attach -t executor
   
 Arquivo de logs:
   ~/catalogadorderiv/logs/
====================================================
""")
    ssh.close()


if __name__ == "__main__":
    main()
