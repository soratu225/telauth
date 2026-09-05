import paramiko
import time

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('192.168.0.96', username='sdj', password='nakadashi0721')

print("Asteriskを完全に再作成中...")
cmd = "echo nakadashi0721 | sudo -S docker compose -f /home/sdj/telauth/docker-compose.yml up -d --force-recreate asterisk"
_, out, err = ssh.exec_command(cmd)
print(out.read().decode())
print(err.read().decode())

time.sleep(8)

print("=== エンドポイント確認 ===")
_, out2, _ = ssh.exec_command("echo nakadashi0721 | sudo -S docker exec telauth-asterisk-1 asterisk -rx 'pjsip show endpoints'")
print(out2.read().decode())

ssh.close()
