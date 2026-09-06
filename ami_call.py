import socket
import time

s = socket.socket()
s.settimeout(10)
s.connect(('127.0.0.1', 5038))
print(s.recv(1024).decode())
s.send(b"Action: Login\r\nUsername: telauth\r\nSecret: telauth_ami_secret\r\n\r\n")
time.sleep(0.3)
print(s.recv(1024).decode())
s.send(b"Action: Originate\r\nChannel: PJSIP/07090910342@brastel-endpoint\r\nContext: outbound-otp\r\nExten: 07090910342\r\nPriority: 1\r\nTimeout: 30000\r\nCallerID: 05068766547\r\nVariable: WAVFILE=/app/data/custom_call\r\n\r\n")
time.sleep(2)
print(s.recv(4096).decode())
s.close()
