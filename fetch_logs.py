import paramiko

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('192.168.0.96', username='sdj', password='nakadashi0721')

cmds = [
    'cd /home/sdj/telauth && docker compose logs --tail 50 asterisk',
    'cd /home/sdj/telauth && docker compose logs --tail 50 app'
]

for cmd in cmds:
    print(f"\n--- {cmd} ---")
    _, stdout, stderr = ssh.exec_command(cmd)
    print(stdout.read().decode())
    print(stderr.read().decode())

ssh.close()
