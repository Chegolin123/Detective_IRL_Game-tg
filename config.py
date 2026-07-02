import os
import logging
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
GROUP_CHAT_ID = int(os.getenv("GROUP_CHAT_ID", "0"))
VOTING_TIMEOUT = int(os.getenv("VOTING_TIMEOUT", "120"))
DATABASE_PATH = os.getenv("DATABASE_PATH", "game.db")
STALE_GAME_TIMEOUT = int(os.getenv("STALE_GAME_TIMEOUT", "300"))

logger = logging.getLogger(__name__)

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не задан в .env файле")

if not ADMIN_ID:
    logger.warning("ADMIN_ID не задан. Первый запустивший бота станет админом.")
