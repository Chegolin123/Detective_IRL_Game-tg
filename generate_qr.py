import os
import qrcode
from dotenv import load_dotenv

load_dotenv()

BOT_USERNAME = os.getenv("BOT_USERNAME")

if not BOT_USERNAME:
    print("BOT_USERNAME не задан в .env")
    print("Добавьте строку: BOT_USERNAME=ваш_бот_без_@")
    exit(1)

url = f"t.me/{BOT_USERNAME}?start=qr"
img = qrcode.make(url)
img.save("qr_code.png")

print(f"QR-код создан: qr_code.png")
print(f"Ссылка: {url}")
print("Распечатайте и разложите в комнате.")
