import paramiko
import sys

HOST = "192.168.0.96"
USER = "sdj"
PASS = "nakadashi0721"

def install_docker():
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(HOST, username=USER, password=PASS, timeout=10)
    
    # 公式のDockerインストールスクリプトを利用するコマンド
    # パスワードはsudo時に渡す
    cmd = (
        "echo '{}' | sudo -S sh -c '"
        "curl -fsSL https://get.docker.com -o get-docker.sh && "
        "sh get-docker.sh && "
        "usermod -aG docker {}'"
    ).format(PASS, USER)
    
    print("Installing Docker...")
    stdin, stdout, stderr = ssh.exec_command(cmd)
    for line in iter(stdout.readline, ""):
        print(line, end="")
    for line in iter(stderr.readline, ""):
        print(line, end="", file=sys.stderr)
        
    ssh.close()

if __name__ == "__main__":
    install_docker()
    print("Docker installed. You may need to log out and log back in for group changes to take effect, or we will just use sudo for now.")
