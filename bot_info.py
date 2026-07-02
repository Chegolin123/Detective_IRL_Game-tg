import json, urllib.request
d = json.loads(urllib.request.urlopen(
    "https://api.telegram.org/bot8955021011:AAEMCaRy1qQJciiL5_wygf7Xfb79xmgpmMk/getMe"
).read())
print("Bot username:", d["result"]["username"])
print("Bot ID:", d["result"]["id"])
