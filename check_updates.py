"""Последние обновления бота. Токен — из BOT_TOKEN (см. config.py)."""
import json
import urllib.request

from config import BOT_TOKEN

with urllib.request.urlopen(
    f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates?limit=10", timeout=20
) as resp:
    body = json.loads(resp.read())

if body["ok"] and body["result"]:
    for upd in body["result"]:
        msg = upd.get("message", {})
        chat = msg.get("chat", {})
        text = (msg.get("text") or "")[:50]
        print(f"  Update {upd['update_id']}: chat={chat.get('id')} type={chat.get('type')} text={text}")
else:
    print("No recent updates")
