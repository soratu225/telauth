import paramiko
import time
from cryptography.fernet import Fernet

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('192.168.0.96', username='sdj', password='nakadashi0721')

key = Fernet.generate_key().decode()
print(f"Key: {key}")

# .envを直接上書き（コメントなし、クリーンな状態で）
env_content = f"""SERVICE_NAME=アピレンティック電話認証サービス
API_KEY=changeme
SECRET_ENCRYPTION_KEY={key}

BRASTEL_SIP_SERVER=softphone.spc.brastel.ne.jp
BRASTEL_SIP_USERNAME=22628092
BRASTEL_SIP_PASSWORD=564ee64b
BRASTEL_SIP_CALLER_ID=05068766547

ASTERISK_HOST=127.0.0.1
ASTERISK_AMI_PORT=5038
ASTERISK_AMI_USERNAME=telauth
ASTERISK_AMI_PASSWORD=telauth_ami_secret

TTS_LANG=ja
TTS_SOUNDS_DIR=/var/lib/asterisk/sounds/telauth
TTS_SOUNDS_HOST_DIR=./sounds

OTP_INTERVAL_SECONDS=900
OTP_DIGITS=6
CALL_RATE_LIMIT_SECONDS=300

DATABASE_URL=sqlite+aiosqlite:///./data/telauth.db
"""

sftp = ssh.open_sftp()
with sftp.open('/home/sdj/telauth/.env', 'w') as f:
    f.write(env_content)
sftp.close()
print(".env written")

# appコンテナを完全に作り直し（down + up）
_, out, _ = ssh.exec_command('echo nakadashi0721 | sudo -S docker compose -f /home/sdj/telauth/docker-compose.yml up -d --force-recreate app')
print(out.read().decode())

time.sleep(8)

# 確認
_, out2, _ = ssh.exec_command('echo nakadashi0721 | sudo -S docker exec telauth-app-1 env | grep SECRET')
print("container SECRET:", out2.read().decode())

_, out3, _ = ssh.exec_command('cd /home/sdj/telauth && docker compose logs --tail 5 app')
print("app log:", out3.read().decode())

ssh.close()
print("Done!")
