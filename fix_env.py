import paramiko
from cryptography.fernet import Fernet

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('192.168.0.96', username='sdj', password='nakadashi0721')

# Fernetキー生成
key = Fernet.generate_key().decode()
print(f"Generated key: {key}")

# .envのSECRET_ENCRYPTION_KEYを書き換え
cmd = f"sed -i 's|SECRET_ENCRYPTION_KEY=.*|SECRET_ENCRYPTION_KEY={key}|' /home/sdj/telauth/.env"
_, out, _ = ssh.exec_command(cmd)
out.read()

# DATABASE_URLも修正（古いものが残っている）
cmd2 = "sed -i 's|DATABASE_URL=sqlite.*|DATABASE_URL=sqlite+aiosqlite:///./data/telauth.db|' /home/sdj/telauth/.env"
_, out2, _ = ssh.exec_command(cmd2)
out2.read()

# 確認
_, out3, _ = ssh.exec_command('grep -E "SECRET_ENCRYPTION_KEY|DATABASE_URL" /home/sdj/telauth/.env')
print("Updated:", out3.read().decode())

# appコンテナ再起動
_, out4, _ = ssh.exec_command('echo nakadashi0721 | sudo -S docker compose -f /home/sdj/telauth/docker-compose.yml restart app')
print("restart:", out4.read().decode())

import time
time.sleep(5)

# 確認
_, out5, _ = ssh.exec_command('cd /home/sdj/telauth && docker compose logs --tail 10 app')
print("app log:", out5.read().decode())

ssh.close()
print("Done!")
