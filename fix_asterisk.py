import paramiko

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('192.168.0.96', username='sdj', password='nakadashi0721')

sftp = ssh.open_sftp()

pjsip_tpl = """[transport-udp]
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
with sftp.open('/home/sdj/telauth/asterisk/pjsip.conf.template', 'w') as f:
    f.write(pjsip_tpl)

ext_conf = """[from-brastel]
exten => s,1,NoOp(Incoming call from ${CALLERID(num)})
 same => n,Answer()
 same => n,Wait(1)
 same => n,GotoIf($["${CALLERID(num)}" = ""]?nocallerid)
 same => n,GotoIf($["${CALLERID(num)}" = "anonymous"]?nocallerid)
 same => n,System(curl -s "http://127.0.0.1:8000/api/v1/inbound?phone_number=${CALLERID(num)}")
 same => n,Wait(2)
 same => n,Playback(telauth/otp_${CALLERID(num)})
 same => n,Hangup()
 same => n(nocallerid),Playback(privacy-unident)
 same => n,Hangup()

exten => _X.,1,NoOp(Incoming call from ${CALLERID(num)} to ${EXTEN})
 same => n,Answer()
 same => n,Wait(1)
 same => n,GotoIf($["${CALLERID(num)}" = ""]?nocallerid)
 same => n,GotoIf($["${CALLERID(num)}" = "anonymous"]?nocallerid)
 same => n,System(curl -s "http://127.0.0.1:8000/api/v1/inbound?phone_number=${CALLERID(num)}")
 same => n,Wait(2)
 same => n,Playback(telauth/otp_${CALLERID(num)})
 same => n,Hangup()
 same => n(nocallerid),Playback(privacy-unident)
 same => n,Hangup()
"""
with sftp.open('/home/sdj/telauth/asterisk/extensions.conf', 'w') as f:
    f.write(ext_conf)

sftp.close()

cmd = "echo nakadashi0721 | sudo -S sh -c 'cd /home/sdj/telauth && docker compose build --no-cache asterisk && docker compose up -d asterisk'"
_, out, err = ssh.exec_command(cmd)
print("BUILD:\n", out.read().decode())
print("ERR:\n", err.read().decode())

ssh.close()
