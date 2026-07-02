import paramiko
import sys
sys.stdout.reconfigure(encoding="utf-8")

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("144.31.207.192", 22, "root", "730639779")

c = ssh.exec_command("cat /root/dark_moon_bot/main.py")
data = c[1].read().decode("utf-8")
# Print lines matching registration
for i, line in enumerate(data.split("\n"), 1):
    if "register" in line or "add_handler" in line or "def main" in line:
        print(f"{i}: {line}")
ssh.close()
