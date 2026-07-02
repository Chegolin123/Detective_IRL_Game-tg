import logging
import random

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from config import GROUP_CHAT_ID
from database import (
    get_player_by_telegram_id, get_available_clues, mark_clue_found,
    save_clue_for_player, get_player_clues, remove_clue_from_player,
    get_active_game, get_penalty_votes, add_penalty_vote,
    get_player_by_telegram_id as get_player,
    get_player_by_username as _get_by_username,
    get_active_players,
)
from data import CLUES

logger = logging.getLogger(__name__)


def _build_clue_keyboard(clue_ids: list, action_prefix: str) -> InlineKeyboardMarkup:
    keyboard = []
    for cid in clue_ids:
        short = CLUES[cid]["text"][:40] + ("…" if len(CLUES[cid]["text"]) > 40 else "")
        keyboard.append([
            InlineKeyboardButton(short, callback_data=f"{action_prefix}_{cid}")
        ])
    keyboard.append([InlineKeyboardButton("Отмена", callback_data=f"{action_prefix}_cancel")])
    return InlineKeyboardMarkup(keyboard)


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

    await update.message.reply_text(
        "Какую улику опубликовать?",
        reply_markup=_build_clue_keyboard(player_clues, "pub")
    )


async def handle_publish_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user = update.effective_user
    if not user:
        return

    data = query.data
    if data == "pub_cancel":
        await query.edit_message_text("Отменено.")
        return

    clue_id = data[len("pub_"):]
    clue_text = CLUES[clue_id]["text"]
    player = get_player(user.id)
    if not player:
        await query.edit_message_text("Игрок не найден.")
        return

    name = player["role"] or user.first_name
    await context.bot.send_message(
        GROUP_CHAT_ID,
        f"🔍 Опубликована улика ({name}): {clue_text}"
    )

    remove_clue_from_player(user.id, clue_id)
    await query.edit_message_text("✅ Улика опубликована в общем чате.")


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

    await update.message.reply_text(
        "Какую улику использовать?",
        reply_markup=_build_clue_keyboard(player_clues, "use")
    )


async def handle_use_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user = update.effective_user
    if not user:
        return

    data = query.data
    if data == "use_cancel":
        await query.edit_message_text("Отменено.")
        return

    clue_id = data[len("use_"):]
    clue_text = CLUES[clue_id]["text"]
    target_role = CLUES[clue_id].get("target")

    game = get_active_game()
    if not game or game["phase"] != "voting":
        await query.edit_message_text("❌ Голосование уже завершено.")
        return

    player = get_player(user.id)
    if not player:
        await query.edit_message_text("Игрок не найден.")
        return

    name = player["role"] or user.first_name
    await context.bot.send_message(
        GROUP_CHAT_ID,
        f"🔍 {name} использует улику: {clue_text}"
    )

    if target_role:
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
            await query.edit_message_text(
                f"✅ Улика опубликована. {', '.join(penalized)} получает +2 штрафных голоса."
            )
        else:
            await query.edit_message_text("✅ Улика опубликована.")
    else:
        await query.edit_message_text("✅ Улика опубликована.")

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
    recipient = _get_by_username(target_username)
    if not recipient:
        await update.message.reply_text(f"Пользователь @{target_username} не зарегистрирован.")
        return

    if not recipient.get("active"):
        await update.message.reply_text("Этот игрок уже исключён.")
        return

    context.user_data["whisper_target"] = recipient
    await update.message.reply_text(
        f"Какую улику показать @{target_username}?",
        reply_markup=_build_clue_keyboard(player_clues, "whis")
    )


async def handle_whisper_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user = update.effective_user
    if not user:
        return

    data = query.data
    if data == "whis_cancel":
        await query.edit_message_text("Отменено.")
        return

    recipient = context.user_data.get("whisper_target")
    if not recipient:
        await query.edit_message_text("Сначала используйте /whisper @username.")
        return

    clue_id = data[len("whis_"):]
    clue_text = CLUES[clue_id]["text"]

    try:
        await context.bot.send_message(
            recipient["telegram_id"],
            f"🤫 Вам тайно передали улику: {clue_text}\n"
            f"Вы не можете использовать её через /use, "
            f"но можете обсудить с другими."
        )
        await query.edit_message_text(
            f"✅ Улика тайно показана @{recipient.get('username', '')}."
        )
    except Exception as e:
        logger.warning(f"Whisper callback failed: {e}")
        await query.edit_message_text("Не удалось отправить сообщение получателю.")

    context.user_data.pop("whisper_target", None)


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
    from telegram.ext import CommandHandler, CallbackQueryHandler
    app.add_handler(CommandHandler("publish", handle_publish))
    app.add_handler(CommandHandler("use", handle_use))
    app.add_handler(CommandHandler("myclues", handle_myclues))
    app.add_handler(CommandHandler("whisper", handle_whisper))
    app.add_handler(CallbackQueryHandler(handle_publish_callback, pattern=r"^pub_"))
    app.add_handler(CallbackQueryHandler(handle_use_callback, pattern=r"^use_"))
    app.add_handler(CallbackQueryHandler(handle_whisper_callback, pattern=r"^whis_"))
