import os
import sys
import tarfile
import tempfile
import time
import paramiko

VPS_IP   = "68.183.216.216"
VPS_USER = "root"
VPS_PASS = "OracleQuant2026!"
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
    print(f"-> {cmd() if callable(cmd) else cmd[:80]}")
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=300)
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
    sftp = ssh.open_sftp()
    sftp.put(local_env_path, remote_env_path)
    sftp.close()
    print(f".env sent to {remote_env_path}")

def main():
    print("Connecting to VPS...")
    ssh = None
    for method, kw in [
        ("Password", dict(password=VPS_PASS)),
        ("SSH Key", dict(key_path=KEY_PATH)),
    ]:
        try:
            ssh = connect(**kw)
            print(f"[OK] Connected via {method}")
            break
        except Exception as e:
            print(f"[FAIL] {method}: {e}")

    if not ssh:
        print("ERROR: Nao foi possivel conectar a VPS.")
        sys.exit(1)

    print("\n=== Ambiente VPS ===")
    run(ssh, "uname -a")
    run(ssh, "python3 --version || python --version")
    run(ssh, "tmux -V")

    run(ssh, f"mkdir -p {REMOTE_DIR} /root/catalogadorderiv/logs")

    tarball = build_tarball(LOCAL_ROOT, EXCLUDE)
    remote_tar = "/tmp/catalogadorderiv.tar.gz"
    send_file(ssh, tarball, remote_tar)
    os.unlink(tarball)

    print("\n=== Extraindo projeto ===")
    run(ssh, f"tar -xzf {remote_tar} -C /root/ --overwrite")
    run(ssh, f"ls {REMOTE_DIR}")

    local_env = os.path.join(LOCAL_ROOT, ".env")
    if os.path.exists(local_env):
        send_env(ssh, local_env, f"{REMOTE_DIR}/.env")

    print("\n=== Instalando dependências ===")
    run(ssh, f"cd {REMOTE_DIR} && python3 -m venv .venv")
    run(ssh, f"cd {REMOTE_DIR} && .venv/bin/pip install --quiet --upgrade pip")
    run(ssh, f"cd {REMOTE_DIR} && .venv/bin/pip install --quiet -r requirements.txt 2>&1 | tail -5")

    # The user says: "APENAS ELE O QUE LER O ARQUIVO JSON O ULTIMO QUE GERAMOS" 
    # That meant Deriv Data Lake Executor (= run_sniper_lake.py)

    print("\n=== Iniciando sessões tmux (Somente Deriv Data Lake) ===")
    run(ssh, f"tmux kill-session -t deriv 2>/dev/null || true")

    VENV = f"{REMOTE_DIR}/.venv/bin"

    # Deriv Sniper Data Lake Executor
    run(ssh, f"tmux new-session -d -s deriv -x 220 -y 50")
    run(ssh, f"""tmux send-keys -t deriv "cd {REMOTE_DIR} && {VENV}/python run_sniper_lake.py >> logs/deriv.log 2>&1" Enter""")

    print("\n=== Sessões ativas ===")
    run(ssh, "tmux ls")

    print("""
====================================================
 DEPLOY CONCLUÍDO ✅
 
 Para acompanhar logs:
   tmux attach -t deriv
   
 Arquivo de logs:
   ~/catalogadorderiv/logs/deriv.log
====================================================
""")
    ssh.close()

if __name__ == "__main__":
    main()
