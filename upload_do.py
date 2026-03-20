import paramiko
import os
import zipfile
import tempfile
import time

def zip_folders(folders_to_zip, zip_path, base_dir):
    print("-> Criando arquivo ZIP...")
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for folder in folders_to_zip:
            if not os.path.exists(folder):
                print(f"Aviso: Pasta não encontrada: {folder}")
                continue
            for root, dirs, files in os.walk(folder):
                # Ignorar __pycache__ e pastas indesejadas
                if '__pycache__' in root:
                    continue
                for file in files:
                    if file.endswith('.pyc'):
                         continue
                    file_path = os.path.join(root, file)
                    arcname = os.path.relpath(file_path, start=base_dir)
                    zipf.write(file_path, arcname)
    print(f"-> Arquivo ZIP criado: {zip_path}")
    return zip_path

def upload_and_restart():
    hostname = "68.183.216.216"
    username = "root"
    password = "OracleQuant2026!"
    
    base_dir = os.path.join(os.path.dirname(__file__), "catalogadorderiv")
    
    folders_to_zip = [
        os.path.join(base_dir, "VPS IQ OPTION", "executor"),
        os.path.join(base_dir, "catalogacao"),
        os.path.join(base_dir, "core"),
        os.path.join(base_dir, "data_lake"),
        os.path.join(base_dir, "agente")
    ]
    
    zip_filename = "update_payload.zip"
    zip_local_path = os.path.join(os.path.dirname(__file__), zip_filename)
    
    zip_folders(folders_to_zip, zip_local_path, base_dir)
    
    remote_zip_path = f"/root/{zip_filename}"
    
    try:
        print(f"-> Conectando na VPS {hostname}...")
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(hostname, username=username, password=password, timeout=10)
        
        print(f"-> Fazendo upload do pacote de atualização para {remote_zip_path}...")
        sftp = client.open_sftp()
        sftp.put(zip_local_path, remote_zip_path)
        sftp.close()
        
        print("-> Extraindo arquivos na VPS...")
        extract_cmds = [
            f"unzip -o {remote_zip_path} -d /root/catalogadorderiv"
        ]
        
        for cmd in extract_cmds:
            stdin, stdout, stderr = client.exec_command(cmd)
            stdout.read() # wait for completion
            
        print("-> Reiniciando serviços (Executor da IQ Option e Sniper)...")
        # Reiniciar Executor IQ
        commands = [
            "tmux kill-session -t executor 2>/dev/null",
            "tmux new-session -d -s executor",
            "tmux send-keys -t executor \"cd '/root/catalogadorderiv/VPS IQ OPTION/executor' && /root/catalogadorderiv/.venv/bin/python3 main.py > /root/catalogadorderiv/logs/executor.log 2>&1\" Enter",
            
            # Reiniciar Data Lake / Agent se precisarmos (ajustar conforme PRDIQVPS.md)
            # Geralmente temos as tmux sessions oracle_quant e miner_worker e tg_bot
            "systemctl restart tg_bot 2>/dev/null || true",
            "pm2 restart all 2>/dev/null || true"
        ]
        
        for cmd in commands:
            print(f"Executando: {cmd}")
            client.exec_command(cmd)
            time.sleep(1)
            
        print("\n[OK] Upload concluido e servicos reiniciados com sucesso!")
        
    except Exception as e:
        print(f"Erro: {e}")
    finally:
        client.close()
        if os.path.exists(zip_local_path):
            os.remove(zip_local_path)

if __name__ == "__main__":
    upload_and_restart()
