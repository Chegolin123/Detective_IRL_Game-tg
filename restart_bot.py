import paramiko, time

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('144.31.207.192', 22, 'root', '730639779')

# Kill ALL python processes running main.py (both python and python3)
ssh.exec_command("kill -9 $(ps aux | grep 'main.py' | grep -v grep | awk '{print $2}') 2>/dev/null")
time.sleep(2)

# Verify all dead
c = ssh.exec_command("ps aux | grep main.py | grep -v grep")
procs = c[1].read().decode()
print("After kill:", "DEAD" if not procs else procs)

# Start fresh with unbuffered output
cmd = "cd /root/dark_moon_bot && PYTHONUNBUFFERED=1 python3 -u main.py > bot.log 2>&1 &"
ssh.exec_command(cmd)
time.sleep(5)

# Check log
c = ssh.exec_command("cat /root/dark_moon_bot/bot.log")
log = c[1].read().decode()
print("=== BOT LOG ===")
print(log if log else "(empty)")
print(f"(len={len(log)})")

c = ssh.exec_command("ps aux | grep 'main.py' | grep -v grep")
proc = c[1].read().decode()
print("=== PROCESSES ===")
print(proc if proc else "DEAD")

# Check if bot responds to Telegram API
import json, urllib.request
token = "8955021011:AAEMCaRy1qQJciiL5_wygf7Xfb79xmgpmMk"
url = f"https://api.telegram.org/bot{token}/getUpdates?offset=-1"
resp = json.loads(urllib.request.urlopen(url).read())
if resp["ok"] and resp["result"]:
    last = resp["result"][-1]
    print(f"Last update: {last['update_id']} from {last.get('message', {}).get('from', {}).get('id', '?')}")
else:
    print(f"Updates: {resp}")

ssh.close()
