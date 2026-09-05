import paramiko
import sys

HOST = "192.168.0.96"
USER = "sdj"
PASS = "nakadashi0721"

def install_and_run_upnp():
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(HOST, username=USER, password=PASS, timeout=10)
    
    # 1. install miniupnpc
    print("Installing miniupnpc...")
    install_cmd = f"echo '{PASS}' | sudo -S apt-get update && echo '{PASS}' | sudo -S apt-get install -y miniupnpc"
    stdin, stdout, stderr = ssh.exec_command(install_cmd)
    stdout.read()  # wait
    
    # 2. Run upnpc to open ports
    print("Opening ports via UPnP...")
    # SIP port
    cmds = [
        "upnpc -a 192.168.0.96 5060 5060 UDP"
    ]
    # RTP ports (10000-10020)
    for port in range(10000, 10021):
        cmds.append(f"upnpc -a 192.168.0.96 {port} {port} UDP")
        
    for cmd in cmds:
        print(f"Running: {cmd}")
        _, out, _ = ssh.exec_command(cmd)
        result = out.read().decode()
        if "failed" in result.lower() or "error" in result.lower():
            print(f"UPnP Result for {cmd}: {result.strip()}")
            
    ssh.close()

if __name__ == "__main__":
    install_and_run_upnp()
    print("UPnP operations completed.")
