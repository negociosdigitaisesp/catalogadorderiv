import paramiko
import sys

def main():
    host = '173.212.209.45'
    user = 'root'
    password = 'NqBxE5RrCwSd'
    
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    
    try:
        client.connect(host, username=user, password=password)
        print("Connected to VPS")
        
        # Let's find the data lake json
        stdin, stdout, stderr = client.exec_command('find /root -name "*.json" 2>/dev/null')
        files = stdout.read().decode('utf-8').strip().split('\n')
        
        print("JSON files in /root:\n", "\n".join(files))
        
    except Exception as e:
        print("Error:", e)
    finally:
        client.close()

if __name__ == '__main__':
    main()
