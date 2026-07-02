import logging
import asyncio

from telegram.ext import Application

from config import (
    BOT_TOKEN, ADMIN_ID, GROUP_CHAT_ID,
    STALE_GAME_TIMEOUT
)
from database import (
    init_db, init_clues, get_stale_voting_games,
    update_game_phase, reset_all_games, cleanup_old_games
)
from handlers import registration, clues, voting, admin

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    filename="game.log",
    encoding="utf-8"
)
logger = logging.getLogger(__name__)


async def check_stale_games(app: Application):
    stale = get_stale_voting_games(STALE_GAME_TIMEOUT)
    for game in stale:
        update_game_phase(game["id"], "discussion")
        logger.warning(f"Stale game #{game['id']} recovered (was in 'voting')")
        try:
            await app.bot.send_message(
                game["chat_id"],
                "⚠️ Голосование было прервано. Возвращаемся к обсуждению."
            )
        except Exception as e:
            logger.warning(f"Could not notify stale game chat: {e}")


async def post_init(app: Application):
    logger.info("Бот запущен, проверка зависших игр...")
    await check_stale_games(app)
    cleanup_old_games(days=7)
    logger.info("Инициализация завершена")


async def post_shutdown(app: Application):
    logger.info("Бот остановлен")


def main():
    init_db()
    init_clues()

    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

    registration.register_handlers(app)
    clues.register_handlers(app)
    voting.register_handlers(app)
    admin.register_handlers(app)

    logger.info(
        f"Бот запущен. Admin: {ADMIN_ID}, Group: {GROUP_CHAT_ID}"
    )
    print(
        f"Бот запущен. Admin: {ADMIN_ID}, Group: {GROUP_CHAT_ID}\n"
        "Нажмите Ctrl+C для остановки."
    )
    app.run_polling(allowed_updates=["message", "callback_query"])


if __name__ == "__main__":
    main()
