"""Состояние бота на VPS: ключи .env (без значений), процесс, размер лога."""
import sys

from vps_ssh import BOT_DIR, connect, run

sys.stdout.reconfigure(encoding="utf-8")

ssh = connect()
try:
    # печатаем только имена переменных, значения секретов не выводим
    env, _e, _c = run(ssh, f"grep -o '^[A-Z_]*' {BOT_DIR}/.env")
    print("ENV keys:", ", ".join(x for x in env.split() if x) or "(пусто)")

    proc, _e, _c = run(ssh, "ps aux | grep 'python3 main' | grep -v grep")
    print("PROC:", proc.strip() if proc.strip() else "DEAD")

    lines, _e, _c = run(ssh, f"wc -l {BOT_DIR}/bot.log 2>/dev/null")
    print(f"Log lines: {lines.strip()}")

    log, _e, _c = run(ssh, f"tail -20 {BOT_DIR}/bot.log")
    print("LOG:", log[-500:] if log else "(empty)")
finally:
    ssh.close()
