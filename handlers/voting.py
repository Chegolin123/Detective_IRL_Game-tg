import logging

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from config import GROUP_CHAT_ID, VOTING_TIMEOUT
from database import (
    get_active_game, get_active_players, get_player_by_telegram_id,
    save_consent, get_consent_count, clear_consent_votes,
    save_vote, get_votes, get_vote_count, clear_votes,
    get_penalty_votes, clear_penalty_votes,
    count_active_players, deactivate_player, update_game_phase,
    increment_game_round, save_vote_to_history,
    get_connection, mark_alibi_revealed,
    set_round_eliminated, check_pair_alibi_on_elimination,
)

logger = logging.getLogger(__name__)

_consent_message_ids = {}
_vote_message_id = None
_job_names = set()


async def send_consent_keyboard(context: ContextTypes.DEFAULT_TYPE, telegram_id: int):
    game = get_active_game()
    if not game:
        return

    alive = count_active_players()
    current = get_consent_count(game["id"])
    text = f"🗳️ Голосование\nСогласно: {current}/{alive}"

    keyboard = [
        [InlineKeyboardButton("Начать голосование", callback_data="consent_yes")]
    ]
    msg = await context.bot.send_message(
        telegram_id, text, reply_markup=InlineKeyboardMarkup(keyboard)
    )
    _consent_message_ids[telegram_id] = msg.message_id


async def update_consent_counters(context: ContextTypes.DEFAULT_TYPE):
    game = get_active_game()
    if not game:
        return
    alive = count_active_players()
    current = get_consent_count(game["id"])
    text = f"🗳️ Голосование\nСогласно: {current}/{alive}"
    keyboard = [
        [InlineKeyboardButton("Начать голосование", callback_data="consent_yes")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    for p in get_active_players():
        tid = p["telegram_id"]
        msg_id = _consent_message_ids.get(tid)
        if msg_id:
            try:
                await context.bot.edit_message_text(
                    text, chat_id=tid, message_id=msg_id, reply_markup=reply_markup
                )
            except Exception:
                pass


async def send_voting_keyboard(context: ContextTypes.DEFAULT_TYPE):
    global _vote_message_id
    game = get_active_game()
    if not game:
        return

    active = get_active_players()
    keyboard = []
    row = []
    for p in active:
        row.append(InlineKeyboardButton(p["role"], callback_data=f"vote_{p['id']}"))
        if len(row) == 3:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)

    reply_markup = InlineKeyboardMarkup(keyboard)
    msg = await context.bot.send_message(
        GROUP_CHAT_ID,
        f"🗳️ Голосуйте за исключение! У вас {VOTING_TIMEOUT} сек.",
        reply_markup=reply_markup
    )
    _vote_message_id = msg.message_id


async def remove_vote_keyboard(context: ContextTypes.DEFAULT_TYPE):
    global _vote_message_id
    if _vote_message_id:
        try:
            await context.bot.edit_message_reply_markup(
                chat_id=GROUP_CHAT_ID,
                message_id=_vote_message_id,
                reply_markup=None
            )
        except Exception:
            pass
        _vote_message_id = None


async def cancel_voting_jobs(context: ContextTypes.DEFAULT_TYPE, game_id: int, round_num: int):
    global _job_names
    name = f"finalize_{game_id}_{round_num}"
    if name in _job_names:
        current_jobs = context.job_queue.jobs()
        for job in current_jobs:
            if job.name == name:
                job.schedule_removal()
        _job_names.discard(name)


async def auto_finalize_voting(context: ContextTypes.DEFAULT_TYPE):
    job_data = context.job.data
    game_id = job_data["game_id"]
    round_num = job_data["round"]

    game = get_active_game()
    if not game or game["id"] != game_id or game["phase"] != "voting":
        return

    await remove_vote_keyboard(context)
    await finalize_votes(context, game_id, round_num)


async def finalize_votes(context: ContextTypes.DEFAULT_TYPE, game_id: int, round_num: int):
    await cancel_voting_jobs(context, game_id, round_num)

    game = get_active_game()
    if not game or game["phase"] != "voting" or game["id"] != game_id:
        return

    votes = get_votes(game_id, round_num)
    penalties = get_penalty_votes(game_id)

    counter = {}
    for v in votes:
        tid = v["target_id"]
        counter[tid] = counter.get(tid, 0) + 1
    for tid, pcount in penalties.items():
        counter[tid] = counter.get(tid, 0) + pcount

    if not counter:
        await context.bot.send_message(
            GROUP_CHAT_ID, "Никто не проголосовал. Возвращаемся к обсуждению."
        )
        update_game_phase(game_id, "discussion")
        clear_consent_votes(game_id)
        clear_penalty_votes(game_id)
        clear_votes(game_id, round_num)
        await send_consent_to_all(context)
        return

    max_votes = max(counter.values())
    candidates = [pid for pid, cnt in counter.items() if cnt == max_votes]
    total_votes = sum(counter.values())
    alive = count_active_players()
    unanimous = total_votes > 0 and len(candidates) == 1 and counter[candidates[0]] == total_votes
    turnout_ok = total_votes > alive * 0.5

    if not turnout_ok and not unanimous:
        await context.bot.send_message(
            GROUP_CHAT_ID,
            f"Явка меньше 50% ({total_votes}/{alive}). Голосование недействительно. Возвращаемся к обсуждению."
        )
        update_game_phase(game_id, "discussion")
        clear_consent_votes(game_id)
        clear_penalty_votes(game_id)
        clear_votes(game_id, round_num)
        await send_consent_to_all(context)
        return

    if len(candidates) > 1:
        await context.bot.send_message(
            GROUP_CHAT_ID, "Ничья! Никто не исключён. Начинается новый раунд обсуждения."
        )
        update_game_phase(game_id, "discussion")
        clear_consent_votes(game_id)
        clear_penalty_votes(game_id)
        clear_votes(game_id, round_num)
        await send_consent_to_all(context)
        return

    eliminated_id = candidates[0]
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM players WHERE id = ?", (eliminated_id,))
    row = cursor.fetchone()
    eliminated = dict(row) if row else None
    conn.close()

    if not eliminated:
        update_game_phase(game_id, "discussion")
        clear_consent_votes(game_id)
        clear_penalty_votes(game_id)
        clear_votes(game_id, round_num)
        await send_consent_to_all(context)
        return

    for v in votes:
        save_vote_to_history(game_id, v["voter_id"], v["target_id"], round_num)

    eliminated_name = eliminated["role"]
    await context.bot.send_message(
        GROUP_CHAT_ID,
        f"🗳️ Исключается *{eliminated_name}*!",
        parse_mode="Markdown"
    )

    if eliminated["alibi_protected"] and eliminated["initial_clue"]:
        await context.bot.send_message(
            GROUP_CHAT_ID,
            f"🔍 Вскрыт козырь {eliminated_name}: {eliminated['initial_clue']}"
        )
        mark_alibi_revealed(eliminated_id)

    deactivate_player(eliminated_id)
    set_round_eliminated(eliminated_id, round_num)

    partner = check_pair_alibi_on_elimination(eliminated_id)
    if partner:
        await context.bot.send_message(
            GROUP_CHAT_ID,
            f"⚠️ {partner['role']} потерял(а) алиби, "
            f"так как {eliminated_name} был(а) исключён(а)!"
        )

    clear_penalty_votes(game_id)
    clear_votes(game_id, round_num)

    remaining = count_active_players()
    _consent_message_ids.clear()

    if remaining > 3:
        update_game_phase(game_id, "discussion")
        clear_consent_votes(game_id)
        await context.bot.send_message(
            GROUP_CHAT_ID,
            f"Новый раунд обсуждения. Осталось {remaining} игроков.\n"
            "Нажмите кнопку «Начать голосование» в ЛС бота, когда будете готовы."
        )
        await send_consent_to_all(context)
    else:
        update_game_phase(game_id, "discussion")
        clear_consent_votes(game_id)
        await context.bot.send_message(
            GROUP_CHAT_ID,
            f"Осталось {remaining} игроков. Ведущий, используйте /final для завершения игры."
        )


async def send_consent_to_all(context: ContextTypes.DEFAULT_TYPE):
    for p in get_active_players():
        try:
            await send_consent_keyboard(context, p["telegram_id"])
        except Exception as e:
            logger.warning(f"send_consent_to_all: {e}")


async def handle_consent_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user = update.effective_user
    if not user:
        return

    player = get_player_by_telegram_id(user.id)
    if not player or not player["active"]:
        await query.edit_message_text("Вы не можете голосовать.")
        return

    game = get_active_game()
    if not game or game["phase"] != "discussion":
        await query.edit_message_text("Сейчас нельзя инициировать голосование.")
        return

    # Atomic consent check + transition to prevent race condition
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("BEGIN IMMEDIATE")
        cursor.execute(
            "DELETE FROM consent_votes WHERE game_id = ? AND player_id = ?",
            (game["id"], player["id"])
        )
        cursor.execute(
            "INSERT INTO consent_votes (game_id, player_id, agreed) VALUES (?, ?, 1)",
            (game["id"], player["id"])
        )
        cursor.execute(
            "SELECT COUNT(*) as cnt FROM consent_votes WHERE game_id = ? AND agreed = 1",
            (game["id"],)
        )
        current = cursor.fetchone()["cnt"]
        cursor.execute("SELECT COUNT(*) as cnt FROM players WHERE active = 1")
        alive = cursor.fetchone()["cnt"]
        conn.commit()
    except Exception as e:
        conn.rollback()
        logger.error(f"consent race condition: {e}")
        await query.edit_message_text("Ошибка. Попробуйте ещё раз.")
        return
    finally:
        conn.close()

    await query.edit_message_text(
        f"✅ Вы согласны начать голосование.\nСогласно: {current}/{alive}"
    )

    await update_consent_counters(context)

    # Re-read game state to prevent double transition from race condition
    game = get_active_game()
    if not game or game["phase"] != "discussion":
        return

    if current > alive / 2:
        _consent_message_ids.clear()
        increment_game_round(game["id"])
        round_num = game["round"] + 1
        update_game_phase(game["id"], "voting")

        await context.bot.send_message(
            GROUP_CHAT_ID,
            f"🗳️ Большинство игроков согласно. Голосование начинается! У вас {VOTING_TIMEOUT} сек."
        )

        await send_voting_keyboard(context)

        global _job_names
        job_name = f"finalize_{game['id']}_{round_num}"
        _job_names.add(job_name)
        context.job_queue.run_once(
            auto_finalize_voting,
            VOTING_TIMEOUT,
            data={"game_id": game["id"], "round": round_num},
            name=job_name
        )


async def handle_vote_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user = update.effective_user
    if not user:
        return

    player = get_player_by_telegram_id(user.id)
    if not player or not player["active"]:
        await query.answer("Вы не можете голосовать.", show_alert=True)
        return

    game = get_active_game()
    if not game or game["phase"] != "voting":
        await query.answer("Голосование уже завершено.", show_alert=True)
        return

    target_id = int(query.data.split("_")[1])
    save_vote(game["id"], player["id"], target_id, game["round"])

    await query.answer("Ваш голос учтён. Вы можете изменить его до завершения голосования.")

    voted = get_vote_count(game["id"], game["round"])
    alive = count_active_players()

    if voted >= alive:
        # Re-check phase; another callback may have already triggered finalization
        game2 = get_active_game()
        if not game2 or game2["phase"] != "voting":
            return
        await remove_vote_keyboard(context)
        await finalize_votes(context, game2["id"], game2["round"])


def register_handlers(app):
    from telegram.ext import CallbackQueryHandler
    app.add_handler(CallbackQueryHandler(handle_consent_callback, pattern="^consent_"))
    app.add_handler(CallbackQueryHandler(handle_vote_callback, pattern="^vote_"))
