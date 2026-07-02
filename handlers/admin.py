import logging

from telegram import Update
from telegram.ext import ContextTypes

import config
from config import GROUP_CHAT_ID
from database import (
    get_active_game, get_active_players, count_active_players,
    get_found_clue_ids, get_votes_history, update_game_phase,
    get_player_by_id, get_player_clues, get_connection,
    clear_consent_votes, get_eliminated_this_round, reactivate_player,
    get_player_by_username, check_pair_alibi_on_elimination,
    save_achievement, get_all_players,
)
from data import FINALS, FINALS_META, ROLES, CLUES

logger = logging.getLogger(__name__)


async def handle_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user or user.id != config.ADMIN_ID:
        await update.message.reply_text("Эта команда только для ведущего.")
        return

    game = get_active_game()
    if not game:
        await update.message.reply_text("Нет активной игры.")
        return

    active = get_active_players()
    all_players = get_all_players()
    found_clues = get_found_clue_ids()

    phase_emoji = {
        "setup": "🛠️", "discussion": "💬", "voting": "🗳️", "finished": "🏁"
    }
    lines = [
        f"{phase_emoji.get(game['phase'], '❓')} *Статус игры*",
        f"Фаза: {game['phase']} | Раунд: {game['round']}",
        f"В игре: {len(active)} | Всего: {len(all_players)}",
        f"Улики: {len(found_clues)}/15",
        "",
        "*Кто в игре:*"
    ]

    for p in active:
        name = p["role"] or f"@{p['username']}"
        clues_n = len(get_player_clues(p["telegram_id"]))
        alibi = "✅" if p.get("alibi_protected") else "⚠️"
        lines.append(f"{alibi} {name} (улик: {clues_n})")

    eliminated = [p for p in all_players if not p["active"]]
    if eliminated:
        lines.append("")
        lines.append("*Исключены:*")
        for p in eliminated:
            role = p["role"] or f"@{p['username']}"
            lines.append(f"✖️ {role}")

    if found_clues:
        lines.append("")
        lines.append("*Найденные улики:*")
        for cid in found_clues:
            clue_text = CLUES[cid]["text"]
            lines.append(f"• {clue_text}")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")





_awaiting_final_confirmation = False


async def handle_vote(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user or user.id != config.ADMIN_ID:
        await update.message.reply_text("Эта команда только для ведущего.")
        return

    game = get_active_game()
    if not game or game["phase"] != "discussion":
        await update.message.reply_text("Сейчас нельзя — игра не в фазе обсуждения.")
        return

    from handlers.voting import send_consent_to_all
    await send_consent_to_all(context)
    await update.message.reply_text("✅ Кнопки голосования разосланы всем активным игрокам.")


async def handle_skip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user or user.id != config.ADMIN_ID:
        return

    game = get_active_game()
    if not game:
        await update.message.reply_text("Нет активной игры.")
        return

    if game["phase"] == "voting":
        from handlers.voting import cancel_voting_jobs, remove_vote_keyboard
        await cancel_voting_jobs(context, game["id"], game["round"])
        await remove_vote_keyboard(context)
        from database import clear_votes, clear_penalty_votes
        clear_votes(game["id"], game["round"])
        clear_penalty_votes(game["id"])

    update_game_phase(game["id"], "discussion")
    clear_consent_votes(game["id"])

    await context.bot.send_message(
        GROUP_CHAT_ID,
        "⏭️ Раунд пропущен ведущим. Возвращаемся к обсуждению."
    )
    await update.message.reply_text("Раунд пропущен.")

    from handlers.voting import send_consent_to_all
    await send_consent_to_all(context)


async def handle_restore(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user or user.id != config.ADMIN_ID:
        await update.message.reply_text("Эта команда только для ведущего.")
        return

    game = get_active_game()
    if not game:
        await update.message.reply_text("Нет активной игры.")
        return

    args = context.args or []
    if not args:
        await update.message.reply_text("Использование: /restore @username")
        return

    username_raw = args[0].lstrip("@")
    player = get_player_by_username(username_raw)
    if not player:
        await update.message.reply_text(f"Игрок @{username_raw} не найден.")
        return

    if player.get("round_eliminated") != game["round"]:
        await update.message.reply_text(
            f"❌ Игрок был исключён раньше (раунд {player.get('round_eliminated')}). "
            "Восстановление возможно только в текущем раунде."
        )
        return

    reactivate_player(player["id"])
    await context.bot.send_message(
        GROUP_CHAT_ID,
        f"🔄 @{username_raw} ({player['role']}) возвращён в игру!"
    )

    partner = check_pair_alibi_on_elimination(player["id"])
    if partner:
        await context.bot.send_message(
            GROUP_CHAT_ID,
            f"⚠️ {partner['role']} потерял(а) алиби, "
            f"так как {player['role']} вернулся — но правда осталась."
        )

    await update.message.reply_text(f"@{username_raw} восстановлен.")


async def handle_final(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global _awaiting_final_confirmation
    user = update.effective_user
    if not user or user.id != config.ADMIN_ID:
        await update.message.reply_text("Эта команда только для ведущего.")
        return

    game = get_active_game()
    if not game:
        await update.message.reply_text("Нет активной игры.")
        return

    remaining = get_active_players()
    if len(remaining) > 3:
        await update.message.reply_text(
            f"Слишком много игроков ({len(remaining)}). "
            f"Подождите, пока останется ≤3."
        )
        return

    _awaiting_final_confirmation = True
    remaining_roles = [p["role"] for p in remaining]
    await update.message.reply_text(
        f"⚠️ Завершить игру?\n"
        f"Осталось игроков: {len(remaining)} ({', '.join(remaining_roles)})\n\n"
        f"Напишите /confirm_final чтобы подтвердить."
    )


async def handle_confirm_final(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global _awaiting_final_confirmation
    user = update.effective_user
    if not user or user.id != config.ADMIN_ID:
        await update.message.reply_text("Эта команда только для ведущего.")
        return

    if not _awaiting_final_confirmation:
        await update.message.reply_text(
            "Нет ожидающего подтверждения финала. Используйте /final сначала."
        )
        return

    _awaiting_final_confirmation = False
    game = get_active_game()
    if not game:
        await update.message.reply_text("Игра уже завершена.")
        return

    remaining = get_active_players()
    remaining_roles = [p["role"] for p in remaining]
    found_clues = get_found_clue_ids()

    final_key = "default"
    killer_role = None
    for key in ["victor", "roman", "maxim", "arkadiy"]:
        meta = FINALS_META[key]
        if meta["killer_role"] in remaining_roles and meta["required_clue"] in found_clues:
            final_key = key
            killer_role = meta["killer_role"]
            break

    final_text = FINALS[final_key].strip()

    killer = None
    if killer_role:
        for p in remaining:
            if p["role"] == killer_role:
                killer = p
                break
        if not killer:
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM players WHERE role = ?", (killer_role,))
            row = cursor.fetchone()
            if row:
                killer = dict(row)
            conn.close()

    if killer:
        history = get_votes_history(game["id"])
        winner_names = []
        for record in history:
            if record["target_id"] == killer["id"]:
                pl = get_player_by_id(record["voter_id"])
                if pl:
                    winner_names.append(pl["role"] or f"@{pl['username']}")

        unique_winners = list(dict.fromkeys(winner_names))
        if unique_winners:
            final_text += (
                f"\n\n🏆 *Победители:* {', '.join(unique_winners)}"
                f" — они голосовали за {killer_role}!"
            )
        else:
            final_text += f"\n\n🏆 Никто не голосовал за убийцу. Победа за убийцей."

    alibi_notice = []
    for p in remaining:
        if p.get("pair_id"):
            partners = []
            for r in ROLES:
                if r.get("pair_id") == p["pair_id"] and r["name"] != p["role"]:
                    partners.append(r["name"])
            for partner_name in partners:
                conn = get_connection()
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT active FROM players WHERE role = ?",
                    (partner_name,)
                )
                row = cursor.fetchone()
                conn.close()
                if not row or not row["active"]:
                    alibi_notice.append(
                        f"⚠️ {p['role']} потерял(а) алиби: {partner_name} был(а) исключён(а)."
                    )

    if alibi_notice:
        final_text += "\n\n" + "\n".join(alibi_notice)

    final_text += "\n\nСпасибо за игру!"

    await context.bot.send_message(
        GROUP_CHAT_ID, final_text, parse_mode="Markdown"
    )

    from database import get_all_players, get_player_achievements, get_game_stats
    all_players = get_all_players()
    history = get_votes_history(game["id"])
    eliminated_ids = {r["target_id"] for r in history}
    stats = get_game_stats(game["id"])
    first_scanner_id = stats.get("first_qr_scanner_id") if stats else None
    for p in all_players:
        player_id = p["id"]
        if p["active"]:
            save_achievement(game["id"], player_id, "Выживший в финале")
        if player_id not in eliminated_ids:
            save_achievement(game["id"], player_id, "Ни разу не исключён")
        clues_count = len(get_player_clues(p["telegram_id"]))
        if clues_count >= 1:
            save_achievement(game["id"], player_id, "Нашёл улику")
        if clues_count >= 3:
            save_achievement(game["id"], player_id, "Собрал 3 улики")
        if first_scanner_id and player_id == first_scanner_id:
            save_achievement(game["id"], player_id, "Первооткрыватель")

        achievements = get_player_achievements(game["id"], player_id)
        if achievements:
            try:
                await context.bot.send_message(
                    p["telegram_id"],
                    f"🏆 Ваши достижения:\n" + "\n".join(f"• {a}" for a in achievements)
                )
            except Exception:
                pass

    update_game_phase(game["id"], "finished")
    await update.message.reply_text(
        "Игра завершена. Для новой игры используйте /startgame."
    )


async def handle_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user:
        return

    is_admin = user.id == config.ADMIN_ID

    lines = [
        "📖 *Команды бота*",
        ""
    ]

    if is_admin:
        lines.extend([
            "*Команды ведущего:*",
            "• `/assign @username Имя` — назначить роль",
            "• `/startgame` — начать игру",
            "• `/vote` — разослать кнопки согласия",
            "• `/skip` — пропустить раунд",
            "• `/restore @username` — вернуть исключённого",
            "• `/final` — финал (когда ≤3 игроков)",
            "• `/status` — статус игры",
            ""
        ])

    lines.extend([
        "*Команды игроков:*",
        "• `/start` — регистрация / сканировать QR-код",
        "• `/info` — моя роль и козырь",
        "• `/myclues` — мои улики",
        "• `/publish` — опубликовать улику в чат",
        "• `/use` — использовать улику как козырь (во время голосования)",
        "",
        "📌 *Кнопка «Начать голосование»* — в ЛС бота, когда "
        "большинство нажмёт — начнётся голосование (2 мин)."
    ])

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def handle_setgroup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user or user.id != config.ADMIN_ID:
        return
    chat_id = update.effective_chat.id
    game = get_active_game()
    if game:
        from database import set_group_chat_id
        set_group_chat_id(game["id"], chat_id)
    config.GROUP_CHAT_ID = chat_id
    await update.message.reply_text(f"✅ Группа установлена: {chat_id}")


def register_handlers(app):
    from telegram.ext import CommandHandler
    app.add_handler(CommandHandler("status", handle_status))
    app.add_handler(CommandHandler("vote", handle_vote))
    app.add_handler(CommandHandler("final", handle_final))
    app.add_handler(CommandHandler("confirm_final", handle_confirm_final))
    app.add_handler(CommandHandler("skip", handle_skip))
    app.add_handler(CommandHandler("restore", handle_restore))
    app.add_handler(CommandHandler("help", handle_help))
    app.add_handler(CommandHandler("setgroup", handle_setgroup))
