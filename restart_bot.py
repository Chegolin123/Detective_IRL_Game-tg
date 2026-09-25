"""Перезапуск бота на VPS и проверка, что Telegram его видит."""
import json
import time
import urllib.request

from config import BOT_TOKEN
from vps_ssh import BOT_DIR, connect, run

ssh = connect()
try:
    # Убить все процессы main.py
    ssh.exec_command(
        "kill -9 $(ps aux | grep 'main.py' | grep -v grep | awk '{print $2}') 2>/dev/null"
    )
    time.sleep(2)

    procs, _e, _c = run(ssh, "ps aux | grep main.py | grep -v grep")
    print("After kill:", "DEAD" if not procs else procs)

    run(
        ssh,
        f"cd {BOT_DIR} && PYTHONUNBUFFERED=1 python3 -u main.py > bot.log 2>&1 &",
    )
    time.sleep(5)

    log, _e, _c = run(ssh, f"cat {BOT_DIR}/bot.log")
    print("=== BOT LOG ===")
    print(log if log else "(empty)")
    print(f"(len={len(log)})")

    proc, _e, _c = run(ssh, "ps aux | grep 'main.py' | grep -v grep")
    print("=== PROCESSES ===")
    print(proc if proc else "DEAD")
finally:
    ssh.close()

# Проверка, что бот отвечает (токен — из окружения, в коде его нет)
with urllib.request.urlopen(
    f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates?offset=-1", timeout=20
) as resp:
    body = json.loads(resp.read())

if body["ok"] and body["result"]:
    last = body["result"][-1]
    print(
        f"Last update: {last['update_id']} "
        f"from {last.get('message', {}).get('from', {}).get('id', '?')}"
    )
else:
    print(f"Updates: {body}")
