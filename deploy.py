import paramiko
import os
from scp import SCPClient
import sys

HOST = "192.168.0.96"
USER = "sdj"
PASS = "nakadashi0721"
REMOTE_DIR = "/home/sdj/telauth"
LOCAL_DIR = "c:/PROJECT/telauth"

def create_ssh_client():
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    print(f"Connecting to {HOST}...")
    ssh.connect(HOST, username=USER, password=PASS, timeout=10)
    return ssh

def put_files(ssh):
    sftp = ssh.open_sftp()
    
    def put_dir(local, remote):
        try:
            sftp.mkdir(remote)
        except IOError:
            pass
        for item in os.listdir(local):
            if item in ['.git', '__pycache__', 'sounds']:
                continue
            lpath = os.path.join(local, item)
            rpath = f"{remote}/{item}"
            if os.path.isdir(lpath):
                put_dir(lpath, rpath)
            else:
                sftp.put(lpath, rpath)
                
    # Create remote base dir
    ssh.exec_command(f"mkdir -p {REMOTE_DIR}")
    
    # Files and dirs to upload
    targets = [
        "app", 
        "asterisk", 
        "tests", 
        "docker-compose.yml", 
        "Dockerfile", 
        "Dockerfile.asterisk", 
        "requirements.txt", 
        ".env.example"
    ]
    
    for t in targets:
        lpath = os.path.join(LOCAL_DIR, t)
        rpath = f"{REMOTE_DIR}/{t}"
        print(f"Uploading {t}...")
        if os.path.isdir(lpath):
            put_dir(lpath, rpath)
        else:
            sftp.put(lpath, rpath)
    sftp.close()

def run_commands(ssh):
    cmds = [
        f"cd {REMOTE_DIR} && cp -n .env.example .env",
        f"echo '{PASS}' | sudo -S sh -c 'cd {REMOTE_DIR} && docker compose build'",
        f"echo '{PASS}' | sudo -S sh -c 'cd {REMOTE_DIR} && docker compose up -d'"
    ]
    for cmd in cmds:
        print(f"Executing: {cmd}")
        stdin, stdout, stderr = ssh.exec_command(cmd)
        
        # ログをストリーミング出力
        for line in iter(stdout.readline, ""):
            print(line, end="")
        for line in iter(stderr.readline, ""):
            print(line, end="", file=sys.stderr)
            
        exit_status = stdout.channel.recv_exit_status()
        if exit_status != 0:
            print(f"Command failed with exit status {exit_status}")

if __name__ == "__main__":
    try:
        ssh = create_ssh_client()
        print("SSH Connection successful.")
        put_files(ssh)
        print("Upload complete.")
        run_commands(ssh)
        ssh.close()
        print("Deployment finished successfully!")
    except Exception as e:
        print(f"Deployment failed: {e}")
