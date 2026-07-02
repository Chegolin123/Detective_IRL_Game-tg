import paramiko
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('144.31.207.192', 22, 'root', '730639779')

# Check .env
c = ssh.exec_command("cat /root/dark_moon_bot/.env")
print("ENV:", c[1].read().decode())

# Check bot PID
c = ssh.exec_command("ps aux | grep 'python3 main' | grep -v grep")
proc = c[1].read().decode()
print("PROC:", proc if proc else "DEAD")

# Check bot log
c = ssh.exec_command("wc -l /root/dark_moon_bot/bot.log 2>/dev/null")
lines = c[1].read().decode().strip()
print(f"Log lines: {lines}")

c = ssh.exec_command("tail -20 /root/dark_moon_bot/bot.log")
log = c[1].read().decode()
print("LOG:", log[-500:] if log else "(empty)")

ssh.close()
