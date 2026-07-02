"""One-shot VPS setup via paramiko."""
import paramiko
import time

HOST = "144.31.207.192"
USER = "root"
PASSWORD = "730639779"
DIR = "/root/dark_moon_bot"

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, 22, USER, PASSWORD)

def run(cmd, timeout=30):
    ssh.exec_command(f"kill $(ps aux | grep 'main.py' | grep -v grep | awk '{{print $2}}') 2>/dev/null")
    time.sleep(1)
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    exit_code = stdout.channel.recv_exit_status()
    out = stdout.read().decode()
    err = stderr.read().decode()
    return out, err, exit_code

# Check python-telegram-bot
out, err, _ = run("python3 -c 'import telegram; print(telegram.__version__)'")
print(f"telegram version: {out.strip()}")

if 'ModuleNotFoundError' in out or 'ModuleNotFoundError' in err:
    print("Installing dependencies...")
    out, err, _ = run(f"cd {DIR} && python3 -m pip install --break-system-packages python-telegram-bot python-dotenv 2>&1 | tail -5", timeout=60)
    print(out)
    if err:
        print(f"ERR: {err[-300:]}")

# Test import
out, err, _ = run("python3 -c 'from telegram.ext import Application; print(\"OK\")'")
print(f"Import test: {out.strip()}")

# Start bot
cmd = f"cd {DIR} && nohup python3 main.py > bot.log 2>&1 &"
out, err, _ = run(cmd)
time.sleep(5)

# Check log
out, err, _ = run(f"cat {DIR}/bot.log")
print("=== BOT LOG ===")
print(out[-1000:] if len(out) > 1000 else out)

# Check process
out, err, _ = run("ps aux | grep 'python3 main' | grep -v grep")
print("=== PROCESS ===")
print(out if out else "NOT RUNNING")

if not out:
    print("=== STDERR ===")
    print(err[-500:] if err else "(none)")

ssh.close()
