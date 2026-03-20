import paramiko
import os
import sys

def upload_file_sftp(local_path, remote_path, host, user, password):
    if not os.path.exists(local_path):
        print(f"Error: Local file does not exist: {local_path}")
        return
        
    try:
        transport = paramiko.Transport((host, 22))
        transport.connect(username=user, password=password)
        sftp = paramiko.SFTPClient.from_transport(transport)
        print(f"Uploading {local_path} -> {remote_path}...")
        sftp.put(local_path, remote_path)
        print("Upload complete!")
        sftp.close()
        transport.close()
    except Exception as e:
        print("SFTP Error:", e)

def main():
    host = '173.212.209.45'
    user = 'root'
    password = 'NqBxE5RrCwSd'
    
    local_dir = r"c:\Users\brend\Videos\catalogadorderiv\catalogadorderiv\data_lake"
    remote_dir = "/root/catalogadorderiv/data_lake"
    
    files = ["config_lake.json", "config_iq_lake.json"]
    
    for f in files:
        local_file = os.path.join(local_dir, f)
        remote_file = f"{remote_dir}/{f}"
        upload_file_sftp(local_file, remote_file, host, user, password)

if __name__ == '__main__':
    main()
