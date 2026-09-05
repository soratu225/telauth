import paramiko

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('192.168.0.96', username='sdj', password='nakadashi0721')

# テンプレートを直接書き換え（環境変数はすでに展開済みの値を使用）
new_conf = """[transport-udp]
type=transport
protocol=udp
bind=0.0.0.0

[brastel-auth]
type=auth
auth_type=userpass
username=22628092
password=564ee64b

[brastel-aor]
type=aor
contact=sip:softphone.spc.brastel.ne.jp
qualify_frequency=15

[global]
type=global
default_outbound_endpoint=brastel-endpoint

[anonymous]
type=endpoint
context=from-brastel
disallow=all
allow=ulaw
allow=alaw

[brastel-endpoint]
type=endpoint
transport=transport-udp
aors=brastel-aor
outbound_auth=brastel-auth
context=from-brastel
disallow=all
allow=ulaw
allow=alaw
rewrite_contact=yes
rtp_symmetric=yes
force_rport=yes
direct_media=no

[brastel-reg]
type=registration
transport=transport-udp
outbound_auth=brastel-auth
server_uri=sip:softphone.spc.brastel.ne.jp
client_uri=sip:22628092@softphone.spc.brastel.ne.jp
retry_interval=60
expiration=3600
"""

# コンテナ内のpjsip.confを直接書き換え
sftp = ssh.open_sftp()
with sftp.open('/home/sdj/telauth/pjsip_new.conf', 'w') as f:
    f.write(new_conf)
sftp.close()

# コンテナ内にコピー
_, out, _ = ssh.exec_command("echo nakadashi0721 | sudo -S docker cp /home/sdj/telauth/pjsip_new.conf telauth-asterisk-1:/etc/asterisk/pjsip.conf")
print("cp:", out.read().decode())

# Asteriskにリロードさせる（再起動不要）
_, out2, _ = ssh.exec_command("echo nakadashi0721 | sudo -S docker exec telauth-asterisk-1 asterisk -rx 'core reload'")
print("reload:", out2.read().decode())

import time
time.sleep(3)

# 確認
_, out3, _ = ssh.exec_command("echo nakadashi0721 | sudo -S docker exec telauth-asterisk-1 asterisk -rx 'pjsip show endpoints'")
print("endpoints:", out3.read().decode())

ssh.close()
print("Done!")
