import paramiko

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('192.168.0.96', username='sdj', password='nakadashi0721')

print("キャッシュなしで強制再ビルド中...")
cmd = "echo nakadashi0721 | sudo -S docker compose -f /home/sdj/telauth/docker-compose.yml build --no-cache asterisk"
_, out, err = ssh.exec_command(cmd, timeout=120)
print(out.read().decode())

print("起動中...")
cmd2 = "echo nakadashi0721 | sudo -S docker compose -f /home/sdj/telauth/docker-compose.yml up -d asterisk"
_, out2, err2 = ssh.exec_command(cmd2, timeout=30)
print(out2.read().decode())

print("確認中...")
cmd3 = "echo nakadashi0721 | sudo -S docker exec telauth-asterisk-1 cat /etc/asterisk/pjsip.conf"
_, out3, _ = ssh.exec_command(cmd3)
print(out3.read().decode())

ssh.close()
