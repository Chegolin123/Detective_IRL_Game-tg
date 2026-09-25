"""Показывает, какие хендлеры зарегистрированы в main.py на VPS."""
import sys

from vps_ssh import BOT_DIR, connect, run

sys.stdout.reconfigure(encoding="utf-8")

ssh = connect()
try:
    data, _err, _code = run(ssh, f"cat {BOT_DIR}/main.py")
finally:
    ssh.close()

for i, line in enumerate(data.split("\n"), 1):
    if "register" in line or "add_handler" in line or "def main" in line:
        print(f"{i}: {line}")
