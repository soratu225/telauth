import paramiko

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('192.168.0.96', username='sdj', password='nakadashi0721')

cmds = [
    "echo nakadashi0721 | sudo -S docker exec telauth-asterisk-1 find /usr/lib -name '*anonymous*' 2>/dev/null",
    "echo nakadashi0721 | sudo -S docker exec telauth-asterisk-1 asterisk -rx 'module show like anonymous'",
    "echo nakadashi0721 | sudo -S docker exec telauth-asterisk-1 asterisk -rx 'pjsip show endpoint anonymous'",
    "echo nakadashi0721 | sudo -S docker exec telauth-asterisk-1 cat /etc/asterisk/pjsip.conf",
]

for cmd in cmds:
    print(f'\n--- {cmd[:70]} ---')
    _, out, _ = ssh.exec_command(cmd)
    print(out.read().decode())

ssh.close()
