import paramiko
import time

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('192.168.0.96', username='sdj', password='nakadashi0721')

# コンテナ内のテンプレートファイルを直接確認
print("=== テンプレートファイル一覧 ===")
_, out, _ = ssh.exec_command("echo nakadashi0721 | sudo -S docker exec telauth-asterisk-1 find /etc/asterisk -name '*.template' -o -name 'pjsip*'")
print(out.read().decode())

print("=== entrypoint.sh ===")
_, out2, _ = ssh.exec_command("echo nakadashi0721 | sudo -S docker exec telauth-asterisk-1 cat /entrypoint.sh")
print(out2.read().decode())

print("=== pjsip.conf.template in container ===")
_, out3, _ = ssh.exec_command("echo nakadashi0721 | sudo -S docker exec telauth-asterisk-1 cat /etc/asterisk/pjsip.conf.template")
print(out3.read().decode())

ssh.close()
