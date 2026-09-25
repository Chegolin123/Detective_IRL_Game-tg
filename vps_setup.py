"""One-shot VPS setup: ставит зависимости и перезапускает бота.

Доступ — по SSH-ключу через vps_ssh (пароль в коде больше не хранится).
"""
import time

from vps_ssh import BOT_DIR, connect


def run(ssh, cmd, timeout=30, kill_first=False):
    if kill_first:
        ssh.exec_command(
            "kill $(ps aux | grep 'main.py' | grep -v grep | awk '{print $2}') 2>/dev/null"
        )
        time.sleep(1)
    _stdin, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    code = stdout.channel.recv_exit_status()
    return stdout.read().decode(), stderr.read().decode(), code


ssh = connect()

out, err, _ = run(ssh, "python3 -c 'import telegram; print(telegram.__version__)'")
print(f"telegram version: {out.strip()}")

if "ModuleNotFoundError" in out or "ModuleNotFoundError" in err:
    print("Installing dependencies...")
    out, err, _ = run(
        ssh,
        f"cd {BOT_DIR} && python3 -m pip install --break-system-packages "
        "python-telegram-bot python-dotenv 2>&1 | tail -5",
        timeout=60,
    )
    print(out)
    if err:
        print(f"ERR: {err[-300:]}")

out, _err, _ = run(ssh, "python3 -c 'from telegram.ext import Application; print(\"OK\")'")
print(f"Import test: {out.strip()}")

out, err, _ = run(
    ssh, f"cd {BOT_DIR} && nohup python3 main.py > bot.log 2>&1 &", kill_first=True
)
time.sleep(5)

out, _err, _ = run(ssh, f"cat {BOT_DIR}/bot.log")
print("=== BOT LOG ===")
print(out[-1000:] if len(out) > 1000 else out)

out, err, _ = run(ssh, "ps aux | grep 'python3 main' | grep -v grep")
print("=== PROCESS ===")
print(out if out else "NOT RUNNING")

if not out:
    print("=== STDERR ===")
    print(err[-500:] if err else "(none)")

ssh.close()
