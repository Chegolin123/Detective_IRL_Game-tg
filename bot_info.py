"""Печатает имя и id бота. Токен берётся из BOT_TOKEN (см. config.py)."""
import json
import urllib.request

from config import BOT_TOKEN

with urllib.request.urlopen(
    f"https://api.telegram.org/bot{BOT_TOKEN}/getMe", timeout=20
) as resp:
    d = json.loads(resp.read())

print("Bot username:", d["result"]["username"])
print("Bot ID:", d["result"]["id"])
