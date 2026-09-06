import socket
import time

s = socket.socket()
s.settimeout(15)
s.connect(('127.0.0.1', 5038))
print(s.recv(1024).decode())
s.send(b"Action: Login\r\nUsername: telauth\r\nSecret: telauth_ami_secret\r\n\r\n")
time.sleep(0.3)
print(s.recv(1024).decode())

# outbound-otp コンテキストのWAVFILE変数を渡してLocal経由で発信
# PJSIP/07090910342@brastel-endpoint では outbound-otp contextが使われないため
# Local channelを使いWAVFILE変数を渡す
s.send(
    b"Action: Originate\r\n"
    b"Channel: Local/07090910342@outbound-otp\r\n"
    b"Context: outbound-otp\r\n"
    b"Exten: 07090910342\r\n"
    b"Priority: 1\r\n"
    b"Timeout: 60000\r\n"
    b"CallerID: 05068766547\r\n"
    b"Variable: WAVFILE=/app/data/custom_call\r\n"
    b"\r\n"
)
time.sleep(3)
resp = s.recv(4096).decode()
print(resp)
s.close()
