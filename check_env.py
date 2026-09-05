import paramiko
import time
from cryptography.fernet import Fernet

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('192.168.0.96', username='sdj', password='nakadashi0721')

# .env確認
print('=== .env ===')
_, out, _ = ssh.exec_command('cat /home/sdj/telauth/.env | grep -E "SECRET|DATABASE"')
print(out.read().decode())

# コンテナ内の環境変数確認
print('=== container env ===')
_, out2, _ = ssh.exec_command('echo nakadashi0721 | sudo -S docker exec telauth-app-1 env | grep -E "SECRET|DATABASE"')
print(out2.read().decode())

ssh.close()
