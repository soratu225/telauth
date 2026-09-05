import paramiko

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('192.168.0.96', username='sdj', password='nakadashi0721')

# extensions.confを直接書き換え（sとワイルドカード両方に対応）
new_ext = """[from-brastel]
; s = デフォルト（拡張番号が特定できない場合）
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

; 数字の拡張番号（050番号宛など）もすべてここで処理
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

[outbound-otp]
exten => _X.,1,NoOp(OTP Call to ${EXTEN} playing ${WAVFILE})
 same => n,Answer()
 same => n,Wait(1)
 same => n,Playback(${WAVFILE})
 same => n,Hangup()
"""

sftp = ssh.open_sftp()
with sftp.open('/home/sdj/telauth/extensions_new.conf', 'w') as f:
    f.write(new_ext)
sftp.close()

_, out, _ = ssh.exec_command("echo nakadashi0721 | sudo -S docker cp /home/sdj/telauth/extensions_new.conf telauth-asterisk-1:/etc/asterisk/extensions.conf")
print("cp:", out.read().decode())

_, out2, _ = ssh.exec_command("echo nakadashi0721 | sudo -S docker exec telauth-asterisk-1 asterisk -rx 'dialplan reload'")
print("reload:", out2.read().decode())

import time
time.sleep(2)

_, out3, _ = ssh.exec_command("echo nakadashi0721 | sudo -S docker exec telauth-asterisk-1 asterisk -rx 'dialplan show from-brastel'")
print("dialplan:", out3.read().decode())

ssh.close()
print("Done!")
