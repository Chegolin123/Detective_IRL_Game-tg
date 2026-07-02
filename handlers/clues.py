import logging
import random

from telegram import Update
from telegram.ext import ContextTypes

from config import GROUP_CHAT_ID
from database import (
    get_player_by_telegram_id, get_available_clues, mark_clue_found,
    save_clue_for_player, get_player_clues, remove_clue_from_player,
    get_active_game, get_penalty_votes, add_penalty_vote,
    get_player_by_telegram_id as get_player
)
from data import CLUES

logger = logging.getLogger(__name__)


async def handle_qr_scan(update: Update, context: ContextTypes.DEFAULT_TYPE, player):
    user = update.effective_user
    if not user:
        return

    if not player or not player["role"]:
        await update.message.reply_text("Вам ещё не назначена роль.")
        return

    available = get_available_clues()
    if not available:
        await update.message.reply_text("Все улики уже найдены.")
        return

    player_clues = get_player_clues(user.id)
    if len(player_clues) >= 3:
        await update.message.reply_text("Вы уже нашли 3 улики. Дайте другим шанс!")
        return

    clue = random.choice(available)
    clue_id = clue["id"]
    mark_clue_found(clue_id)
    save_clue_for_player(user.id, clue_id)

    clue_text = CLUES[clue_id]["text"]
    await update.message.reply_text(f"🔍 Вы нашли улику: {clue_text}")

    name = player["role"] or user.first_name
    await context.bot.send_message(
        GROUP_CHAT_ID,
        f"🔍 {name} нашёл(ла) улику!"
    )


async def handle_publish(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user:
        return

    player_clues = get_player_clues(user.id)
    if not player_clues:
        await update.message.reply_text("У вас нет улик для публикации.")
        return

    clue_id = player_clues[0]
    clue_text = CLUES[clue_id]["text"]
    player = get_player(user.id)
    name = player["role"] if player else user.first_name

    await context.bot.send_message(
        GROUP_CHAT_ID,
        f"🔍 Опубликована улика ({name}): {clue_text}"
    )

    remove_clue_from_player(user.id, clue_id)
    await update.message.reply_text("Улика опубликована в общем чате.")


async def handle_use(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user:
        return

    game = get_active_game()
    if not game or game["phase"] != "voting":
        await update.message.reply_text(
            "❌ Сейчас нельзя использовать улику. Дождитесь голосования."
        )
        return

    player_clues = get_player_clues(user.id)
    if not player_clues:
        await update.message.reply_text("❌ У вас нет сохранённых улик.")
        return

    clue_id = player_clues[0]
    clue_text = CLUES[clue_id]["text"]
    target_role = CLUES[clue_id].get("target")

    player = get_player(user.id)
    name = player["role"] if player else user.first_name

    await context.bot.send_message(
        GROUP_CHAT_ID,
        f"🔍 {name} использует улику: {clue_text}"
    )

    if target_role:
        from database import get_active_players
        active_players = get_active_players()
        targets = target_role if isinstance(target_role, list) else [target_role]
        penalized = []
        for t_name in targets:
            for p in active_players:
                if p["role"] == t_name:
                    add_penalty_vote(game["id"], p["id"], clue_id)
                    penalized.append(t_name)
                    break
        if penalized:
            await update.message.reply_text(
                f"✅ Улика опубликована. {', '.join(penalized)} получает +2 штрафных голоса."
            )
        else:
            await update.message.reply_text("✅ Улика опубликована.")
    else:
        await update.message.reply_text("✅ Улика опубликована.")

    remove_clue_from_player(user.id, clue_id)


async def handle_whisper(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user:
        return

    args = context.args or []
    if not args:
        await update.message.reply_text(
            "Использование: /whisper @username\n"
            "Тайно покажет вашу улику другому игроку."
        )
        return

    player_clues = get_player_clues(user.id)
    if not player_clues:
        await update.message.reply_text("У вас нет улик для передачи.")
        return

    target_username = args[0].lstrip("@")
    target = get_player_by_telegram_id(user.id)
    from database import get_player_by_username as _get_by_username
    recipient = _get_by_username(target_username)

    if not recipient:
        await update.message.reply_text(f"Пользователь @{target_username} не зарегистрирован.")
        return

    if not recipient.get("active"):
        await update.message.reply_text("Этот игрок уже исключён.")
        return

    clue_id = player_clues[0]
    clue_text = CLUES[clue_id]["text"]

    try:
        await context.bot.send_message(
            recipient["telegram_id"],
            f"🤫 Вам тайно передали улику: {clue_text}\n"
            f"Вы не можете использовать её через /use, "
            f"но можете обсудить с другими."
        )
        await update.message.reply_text(
            f"✅ Улика тайно показана @{target_username}."
        )
    except Exception as e:
        logger.warning(f"Whisper failed to {target_username}: {e}")
        await update.message.reply_text(
            "Не удалось отправить сообщение получателю."
        )


async def handle_myclues(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user:
        return

    player_clues = get_player_clues(user.id)
    if not player_clues:
        await update.message.reply_text("У вас нет сохранённых улик.")
        return

    text_lines = ["📋 Ваши сохранённые улики:"]
    for cid in player_clues:
        clue_text = CLUES[cid]["text"]
        text_lines.append(f"• {clue_text}")
    text_lines.append(f"\nВсего: {len(player_clues)}/3")

    await update.message.reply_text("\n".join(text_lines))


def register_handlers(app):
    from telegram.ext import CommandHandler
    app.add_handler(CommandHandler("publish", handle_publish))
    app.add_handler(CommandHandler("use", handle_use))
    app.add_handler(CommandHandler("myclues", handle_myclues))
    app.add_handler(CommandHandler("whisper", handle_whisper))
