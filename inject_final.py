import paramiko
import time

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('192.168.0.96', username='sdj', password='nakadashi0721')

sftp = ssh.open_sftp()

# 正しいpjsip.confを直接コンテナ内に書き込む（テンプレートではなく最終ファイル）
correct_pjsip = """[transport-udp]
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

# テンプレートも正しいものに更新（次回再起動時用）
correct_template = """[transport-udp]
type=transport
protocol=udp
bind=0.0.0.0

[brastel-auth]
type=auth
auth_type=userpass
username=${BRASTEL_SIP_USERNAME}
password=${BRASTEL_SIP_PASSWORD}

[brastel-aor]
type=aor
contact=sip:${BRASTEL_SIP_SERVER}
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
server_uri=sip:${BRASTEL_SIP_SERVER}
client_uri=sip:${BRASTEL_SIP_USERNAME}@${BRASTEL_SIP_SERVER}
retry_interval=60
expiration=3600
"""

# ホスト側に一時ファイルとして書き出し
with sftp.open('/home/sdj/pjsip_final.conf', 'w') as f:
    f.write(correct_pjsip)
with sftp.open('/home/sdj/pjsip_template_final.conf', 'w') as f:
    f.write(correct_template)
sftp.close()

# コンテナ内のpjsip.confとテンプレートを両方書き換え
_, out, _ = ssh.exec_command("echo nakadashi0721 | sudo -S docker cp /home/sdj/pjsip_final.conf telauth-asterisk-1:/etc/asterisk/pjsip.conf")
print("pjsip.conf cp:", out.read().decode())

_, out2, _ = ssh.exec_command("echo nakadashi0721 | sudo -S docker cp /home/sdj/pjsip_template_final.conf telauth-asterisk-1:/etc/asterisk/pjsip.conf.template")
print("template cp:", out2.read().decode())

# pjsip reloadでホットリロード（再起動不要）
time.sleep(1)
_, out3, _ = ssh.exec_command("echo nakadashi0721 | sudo -S docker exec telauth-asterisk-1 asterisk -rx 'module reload res_pjsip.so'")
print("pjsip reload:", out3.read().decode())

time.sleep(3)

# エンドポイント確認
_, out4, _ = ssh.exec_command("echo nakadashi0721 | sudo -S docker exec telauth-asterisk-1 asterisk -rx 'pjsip show endpoints'")
result = out4.read().decode()
print("Endpoints:", result)

if "anonymous" in result:
    print("\n✅ SUCCESS: anonymous endpoint found!")
else:
    print("\n❌ FAILED: still no anonymous endpoint")

ssh.close()
