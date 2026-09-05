import paramiko
import time

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('192.168.0.96', username='sdj', password='nakadashi0721')

print("コンテナ再起動中...")
_, out, _ = ssh.exec_command('echo nakadashi0721 | sudo -S docker compose -f /home/sdj/telauth/docker-compose.yml restart asterisk')
print(out.read().decode())

time.sleep(8)

print("=== pjsip.conf ===")
_, out2, _ = ssh.exec_command('echo nakadashi0721 | sudo -S docker exec telauth-asterisk-1 cat /etc/asterisk/pjsip.conf')
print(out2.read().decode())

print("=== anonymous endpoint ===")
_, out3, _ = ssh.exec_command("echo nakadashi0721 | sudo -S docker exec telauth-asterisk-1 asterisk -rx 'pjsip show endpoint anonymous'")
print(out3.read().decode())

print("=== pjsip show endpoints ===")
_, out4, _ = ssh.exec_command("echo nakadashi0721 | sudo -S docker exec telauth-asterisk-1 asterisk -rx 'pjsip show endpoints'")
print(out4.read().decode())

ssh.close()
