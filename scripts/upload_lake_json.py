import paramiko
import os

host = "173.212.209.45"
user = "root"
password = "NqBxE5RrCwSd"

local_dir = r"C:\Users\brend\Videos\catalogadorderiv\catalogadorderiv\data_lake"
files_to_upload = ["config_lake.json", "config_iq_lake.json"]
remote_dir = "/root/catalogadorderiv/data_lake"

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
print("Connecting...")
ssh.connect(host, username=user, password=password)

sftp = ssh.open_sftp()

def ensure_dir(sftp, remote_directory):
    if remote_directory == '/':
        return
    if remote_directory == '':
        return
    try:
        sftp.stat(remote_directory)
    except IOError:
        ensure_dir(sftp, os.path.dirname(remote_directory).replace('\\', '/'))
        sftp.mkdir(remote_directory)

ensure_dir(sftp, remote_dir)

for file in files_to_upload:
    local_path = os.path.join(local_dir, file)
    remote_path = f"{remote_dir}/{file}"
    if os.path.exists(local_path):
        print(f"Uploading {local_path} to {remote_path}...")
        try:
            sftp.put(local_path, remote_path)
            print(f"Success: {file}")
        except Exception as e:
            print(f"Failed to upload {file}: {e}")
    else:
        print(f"Local file not found: {local_path}")

sftp.close()
ssh.close()
print("Done.")
