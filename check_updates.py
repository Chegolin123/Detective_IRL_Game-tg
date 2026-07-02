import json, urllib.request

token = "8955021011:AAEMCaRy1qQJciiL5_wygf7Xfb79xmgpmMk"

url = f"https://api.telegram.org/bot{token}/getUpdates?limit=10"
resp = json.loads(urllib.request.urlopen(url).read())

if resp["ok"] and resp["result"]:
    for upd in resp["result"]:
        msg = upd.get("message", {})
        chat = msg.get("chat", {})
        text = (msg.get("text") or "")[:50]
        print(f"  Update {upd['update_id']}: chat={chat.get('id')} type={chat.get('type')} text={text}")
else:
    print("No recent updates")
