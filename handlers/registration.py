import logging
import random

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CommandHandler, CallbackQueryHandler

import config
from config import GROUP_CHAT_ID
from database import (
    register_player, get_player_by_telegram_id, get_player_by_username,
    get_player_by_id, assign_role, get_active_players, create_game,
    get_active_game, update_game_phase, end_game, reset_for_new_game,
    get_all_players, get_unassigned_players, get_assigned_roles,
    set_player_gender, get_players_by_gender, init_game_stats,
)
from data import ROLES, FEMALE_ROLES, MALE_ROLES, find_role, get_roles_by_gender
from handlers.voting import send_consent_keyboard

logger = logging.getLogger(__name__)

_debug_admins = set()


def _is_player_mode(user_id: int) -> bool:
    return user_id == config.ADMIN_ID and user_id in _debug_admins


def _is_admin(user_id: int) -> bool:
    return user_id == config.ADMIN_ID and user_id not in _debug_admins


async def handle_debug(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user or user.id != config.ADMIN_ID:
        return

    if user.id in _debug_admins:
        _debug_admins.discard(user.id)
        await update.message.reply_text(
            "Режим отладки выключен. Вы снова ведущий."
        )
    else:
        _debug_admins.add(user.id)
        await update.message.reply_text(
            "Режим отладки включён. Теперь вы игрок.\n"
            "Напишите /start чтобы зарегистрироваться как игрок.\n"
            "Напишите /debug ещё раз чтобы вернуться в режим ведущего."
        )


async def handle_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user:
        return

    text = update.message.text if update.message else ""
    args = text.split()
    is_qr = len(args) > 1 and args[1] == "qr"

    telegram_id = user.id
    username = user.username or user.first_name

    player = get_player_by_telegram_id(telegram_id)

    if not player:
        register_player(telegram_id, username)
        player = get_player_by_telegram_id(telegram_id)

    if not config.ADMIN_ID:
        config.ADMIN_ID = telegram_id
        import os
        try:
            env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
            with open(env_path, "r", encoding="utf-8") as f:
                content = f.read()
            with open(env_path, "w", encoding="utf-8") as f:
                f.write(content.replace("ADMIN_ID=0", f"ADMIN_ID={telegram_id}"))
        except Exception:
            pass
        await update.message.reply_text(
            "👑 Вы назначены ведущим (ID: {telegram_id}).\n"
            "Команды ведущего: /startgame, /vote, /results, /status, /final, /setgroup\n\n"
            "Добавьте бота в групповой чат и напишите /setgroup там."
        )
        logger.info(f"Admin auto-assigned: {telegram_id} (@{username})")
        return

    if _is_admin(user.id):
        await update.message.reply_text(
            "👑 Вы ведущий.\n"
            "Команды: /startgame, /vote, /results, /status, /final, /setgroup, /debug"
        )
        return

    if is_qr:
        from handlers.clues import handle_qr_scan
        await handle_qr_scan(update, context, player)
        return

    if player["role"]:
        await update.message.reply_text(
            f"Вы уже зарегистрированы. Ваша роль: {player['role']}.\n"
            f"Команды: /info, /myclues, /publish, /use"
        )
        return

    if player["gender"]:
        lines = [
            "Добро пожаловать! Вы зарегистрированы.",
            "Ожидайте начала игры от ведущего.",
        ]
        if user.id in _debug_admins:
            lines.extend([
                "",
                "Вы в режиме отладки. Что дальше:",
                "1. Напишите /debug чтобы вернуться в режим ведущего",
                "2. Затем /startgame — бот сам раздаст роли",
                "Или используйте /assign @ваш_ник Роль вручную",
            ])
        await update.message.reply_text("\n".join(lines))
        return

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Мужской", callback_data="gender_male"),
            InlineKeyboardButton("Женский", callback_data="gender_female"),
        ]
    ])
    await update.message.reply_text(
        "Добро пожаловать в игру «Тёмная луна»!\n\n"
        "Выберите ваш пол, чтобы получить подходящую роль:",
        reply_markup=keyboard
    )


async def handle_gender_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user = update.effective_user
    if not user:
        return

    gender = query.data.split("_")[1]
    gender_text = "Мужской" if gender == "male" else "Женский"
    telegram_id = user.id

    set_player_gender(telegram_id, gender)

    await query.edit_message_text(
        f"Пол сохранён: {gender_text}\n\n"
        "Ожидайте, когда ведущий начнёт игру командой /startgame."
    )

    if config.ADMIN_ID:
        try:
            await context.bot.send_message(
                config.ADMIN_ID,
                f"Игрок @{user.username or user.first_name} зарегистрировался. Пол: {gender_text}"
            )
        except Exception:
            pass


async def handle_change_gender(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user:
        return

    game = get_active_game()
    if game:
        await update.message.reply_text("Игра уже началась. Нельзя сменить пол.")
        return

    player = get_player_by_telegram_id(user.id)
    if not player:
        await update.message.reply_text(
            "Вы ещё не зарегистрированы. Напишите /start сначала."
        )
        return

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Мужской", callback_data="change_male"),
            InlineKeyboardButton("Женский", callback_data="change_female"),
        ]
    ])
    await update.message.reply_text(
        "Выберите новый пол:", reply_markup=keyboard
    )


async def handle_change_gender_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user = update.effective_user
    if not user:
        return

    gender = query.data.split("_")[1]
    gender_text = "Мужской" if gender == "male" else "Женский"

    set_player_gender(user.id, gender)
    await query.edit_message_text(f"Пол изменён на {gender_text}.")


async def handle_assign(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user or user.id != config.ADMIN_ID:
        await update.message.reply_text("Эта команда только для ведущего.")
        return

    args = context.args or []

    if len(args) >= 2:
        await _do_assign_text(update, context, args)
        return

    available = _get_available_roles()
    unassigned = get_unassigned_players()
    total_roles = len(ROLES)
    assigned_count = total_roles - len(available)

    if not unassigned:
        if not available:
            await update.message.reply_text("Все роли назначены всем игрокам!")
        else:
            await update.message.reply_text("Нет незарегистрированных игроков.")
        return

    lines = [
        f"Назначение ролей  ({assigned_count}/{total_roles})",
        "",
        "Выберите игрока:",
    ]

    keyboard = _build_player_keyboard(unassigned, available)
    await update.message.reply_text(
        "\n".join(lines), reply_markup=keyboard
    )


def _get_available_roles() -> list:
    assigned = set(get_assigned_roles())
    return [r for r in ROLES if r["name"] not in assigned]


def _build_player_keyboard(unassigned: list, available: list) -> InlineKeyboardMarkup:
    keyboard = []
    for p in unassigned:
        name = p["username"] or f"ID{p['telegram_id']}"
        keyboard.append([
            InlineKeyboardButton(f"@{name}", callback_data=f"assign_p_{p['id']}")
        ])
    if keyboard:
        keyboard.append([
            InlineKeyboardButton("Отмена", callback_data="assign_cancel")
        ])
    return InlineKeyboardMarkup(keyboard)


def _build_role_keyboard(available: list) -> InlineKeyboardMarkup:
    keyboard = []
    row = []
    for r in available:
        row.append(InlineKeyboardButton(r["name"], callback_data=f"assign_r_{r['name']}"))
        if len(row) == 3:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    keyboard.append([
        InlineKeyboardButton("Назад", callback_data="assign_back")
    ])
    return InlineKeyboardMarkup(keyboard)


async def _do_assign_text(update: Update, context: ContextTypes.DEFAULT_TYPE, args: list):
    username_raw = args[0].lstrip("@")
    role_name = " ".join(args[1:])

    role_data = find_role(role_name)
    if not role_data:
        available = _get_available_roles()
        names = [r["name"] for r in available]
        await update.message.reply_text(
            f"Персонаж «{role_name}» не найден.\n"
            f"Доступные: {', '.join(names)}"
        )
        return

    assigned = set(get_assigned_roles())
    if role_data["name"] in assigned:
        await update.message.reply_text(
            f"Роль «{role_data['name']}» уже назначена другому игроку."
        )
        return

    player = get_player_by_username(username_raw)
    if not player:
        await update.message.reply_text(f"Пользователь @{username_raw} не зарегистрирован.")
        return

    await _assign_and_notify(update, context, player, role_data, username_raw)


async def _assign_and_notify(update, context, player, role_data, username_raw):
    assign_role(
        player["telegram_id"],
        role_data["name"],
        role_data["clue"],
        role_data.get("role", ""),
        role_data.get("personal_goal", ""),
        role_data.get("pair_id"),
    )

    try:
        await context.bot.send_message(
            player["telegram_id"],
            f"Ваша роль: *{role_data['name']} -- {role_data['role']}*\n"
            f"Алиби: {role_data['alibi']}\n"
            f"Ваш начальный козырь: {role_data['clue']}\n\n"
            f"Команды: /info, /myclues, /publish, /use",
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.warning(f"Не удалось отправить сообщение игроку {username_raw}: {e}")

    total_roles = len(ROLES)
    remaining = total_roles - len(get_assigned_roles())
    player_name = role_data["name"]
    text = (
        f"Роль «{player_name}» назначена @{username_raw}. "
        f"Осталось: {remaining}/{total_roles}"
    )
    if update.callback_query:
        await update.callback_query.edit_message_text(text)
    else:
        await update.message.reply_text(text)

    await context.bot.send_message(
        GROUP_CHAT_ID,
        f" @{username_raw} получил(а) роль -- {player_name}!"
    )


async def handle_assign_player_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user = update.effective_user
    if not user or user.id != config.ADMIN_ID:
        await query.edit_message_text("Эта команда только для ведущего.")
        return

    player_id = int(query.data.split("_")[2])
    context.user_data["assign_player_id"] = player_id

    available = _get_available_roles()
    if not available:
        await query.edit_message_text("Все роли уже назначены!")
        return

    player = get_player_by_id(player_id)
    if not player:
        await query.edit_message_text("Игрок не найден.")
        return

    name = player["username"] or f"ID{player['telegram_id']}"
    lines = [
        f"Игрок: @{name}",
        "",
        "Выберите роль:",
    ]
    keyboard = _build_role_keyboard(available)
    await query.edit_message_text(
        "\n".join(lines), reply_markup=keyboard
    )


async def handle_assign_role_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user = update.effective_user
    if not user or user.id != config.ADMIN_ID:
        await query.edit_message_text("Эта команда только для ведущего.")
        return

    role_name = query.data[len("assign_r_"):]
    role_data = find_role(role_name)
    if not role_data:
        await query.edit_message_text(f"Роль «{role_name}» не найдена.")
        return

    assigned = set(get_assigned_roles())
    if role_data["name"] in assigned:
        await query.edit_message_text(
            f"Роль «{role_data['name']}» уже назначена другому игроку."
        )
        return

    player_id = context.user_data.get("assign_player_id")
    if not player_id:
        await query.edit_message_text("Сначала выберите игрока. Используйте /assign")
        return

    player = get_player_by_id(player_id)
    if not player:
        await query.edit_message_text("Игрок не найден.")
        return

    username_raw = player["username"] or str(player["telegram_id"])
    await _assign_and_notify(update, context, player, role_data, username_raw)


async def handle_assign_back_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user = update.effective_user
    if not user or user.id != config.ADMIN_ID:
        return

    context.user_data.pop("assign_player_id", None)
    available = _get_available_roles()
    unassigned = get_unassigned_players()
    total_roles = len(ROLES)
    assigned_count = total_roles - len(available)

    if not unassigned:
        await query.edit_message_text("Все игроки получили роли!")
        return

    lines = [
        f"Назначение ролей  ({assigned_count}/{total_roles})",
        "",
        "Выберите игрока:",
    ]
    keyboard = _build_player_keyboard(unassigned, available)
    await query.edit_message_text(
        "\n".join(lines), reply_markup=keyboard
    )


async def handle_assign_cancel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user = update.effective_user
    if not user or user.id != config.ADMIN_ID:
        return

    context.user_data.pop("assign_player_id", None)
    await query.edit_message_text("Отменено.")


def _exclude_roles(role_list: list, player_count: int) -> list:
    if len(role_list) <= player_count:
        return role_list
    available = role_list.copy()
    solo = [r for r in available if r["type"] == "одиночное"]
    pair = [r for r in available if r["type"] == "парное"]
    while len(available) > player_count and solo:
        removed = solo.pop()
        if removed in available:
            available.remove(removed)
    while len(available) > player_count and pair:
        removed = pair.pop()
        if removed in available:
            available.remove(removed)
            pair_name = removed.get("pair")
            if pair_name:
                for r in available[:]:
                    if r["name"] == pair_name:
                        available.remove(r)
                        if r in pair:
                            pair.remove(r)
                        break
    return available


async def handle_startgame(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user or not _is_admin(user.id):
        await update.message.reply_text("Эта команда только для ведущего.")
        return

    existing = get_active_game()
    if existing:
        end_game(existing["id"])
    reset_for_new_game()

    male_players = get_players_by_gender("male")
    female_players = get_players_by_gender("female")
    all_players = male_players + female_players

    min_players = 1 if user.id in _debug_admins else 4
    if len(all_players) < min_players:
        await update.message.reply_text(
            f"Зарегистрировано {len(all_players)} игроков. "
            f"Нужно минимум {min_players}."
        )
        return

    male_roles = MALE_ROLES.copy()
    female_roles = FEMALE_ROLES.copy()

    if len(male_players) < len(male_roles):
        male_roles = _exclude_roles(male_roles, len(male_players))
    if len(female_players) < len(female_roles):
        female_roles = _exclude_roles(female_roles, len(female_players))

    if len(male_players) > len(male_roles):
        await update.message.reply_text(
            f"Слишком много мужчин ({len(male_players)}). Максимум: {len(male_roles)}."
        )
        return
    if len(female_players) > len(female_roles):
        await update.message.reply_text(
            f"Слишком много женщин ({len(female_players)}). Максимум: {len(female_roles)}."
        )
        return

    random.shuffle(male_roles)
    random.shuffle(female_roles)

    for i, player in enumerate(male_players):
        role = male_roles[i]
        assign_role(player["telegram_id"], role["name"], role["clue"],
                    role.get("role", ""), role.get("personal_goal", ""),
                    role.get("pair_id"))
        try:
            goal_text = role.get("personal_goal", "")
            goal_section = f"\n\nЛичная задача: {goal_text}" if goal_text else ""
            await context.bot.send_message(
                player["telegram_id"],
                f"Ваша роль: *{role['name']} -- {role['role']}*\n"
                f"Алиби: {role['alibi']}\n"
                f"Начальный козырь: {role['clue']}"
                f"{goal_section}\n\n"
                f"Команды: /info, /myclues, /publish, /use",
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.warning(f"Не удалось отправить сообщение мужчине {player['telegram_id']}: {e}")

    for i, player in enumerate(female_players):
        role = female_roles[i]
        assign_role(player["telegram_id"], role["name"], role["clue"],
                    role.get("role", ""), role.get("personal_goal", ""),
                    role.get("pair_id"))
        try:
            goal_text = role.get("personal_goal", "")
            goal_section = f"\n\nЛичная задача: {goal_text}" if goal_text else ""
            await context.bot.send_message(
                player["telegram_id"],
                f"Ваша роль: *{role['name']} -- {role['role']}*\n"
                f"Алиби: {role['alibi']}\n"
                f"Начальный козырь: {role['clue']}"
                f"{goal_section}\n\n"
                f"Команды: /info, /myclues, /publish, /use",
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.warning(f"Не удалось отправить сообщение женщине {player['telegram_id']}: {e}")

    game_id = create_game(GROUP_CHAT_ID, config.ADMIN_ID)
    update_game_phase(game_id, "discussion")
    init_game_stats(game_id)

    await update.message.reply_text(
        f"Игра началась! Роли распределены.\n"
        f"Всего игроков: {len(all_players)}\n"
        f"Мужчин: {len(male_players)}, Женщин: {len(female_players)}"
    )

    await context.bot.send_message(
        GROUP_CHAT_ID,
        "Игра «Тёмная луна» началась!\n"
        "Проверьте свои роли в личных сообщениях бота (/info).\n\n"
        "Сейчас каждый игрок по кругу озвучит своё алиби.",
        parse_mode="Markdown"
    )

    active = get_active_players()
    for p in active:
        try:
            await send_consent_keyboard(context, p["telegram_id"])
        except Exception as e:
            logger.warning(f"Не удалось отправить кнопку игроку {p['telegram_id']}: {e}")


async def handle_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user:
        return

    row = get_player_by_telegram_id(user.id)
    if not row or not row["role"]:
        await update.message.reply_text("Вам ещё не назначена роль.")
        return
    player = dict(row)

    role_data = find_role(player["role"])
    if role_data:
        alibi_text = role_data["alibi"]
    else:
        alibi_text = "—"

    goal = player.get("personal_goal", "")
    alibi_status = "подтверждено" if player.get("alibi_protected") else "⚠️ поставлено под сомнение (пара исключена)"
    lines = [
        f"<b>🎭 {player['role']}</b>",
        f"<b>Роль:</b> {player.get('role_description', '')}",
        f"<b>Алиби:</b> {alibi_text}",
        f"<b>Статус алиби:</b> {alibi_status}",
        f"<b>Начальный козырь:</b> {player.get('initial_clue', '')}",
    ]
    if goal:
        lines.append(f"\n<b>Личная задача:</b> {goal}")
    status = "активен" if player["active"] else "исключён"
    lines.append(f"\n<b>Статус:</b> {status}")

    card_html = "\n".join(lines)

    import os
    photo_path = os.path.join("images", f"{player['role']}.jpg")
    if os.path.exists(photo_path):
        try:
            with open(photo_path, "rb") as f:
                await update.message.reply_photo(
                    photo=f, caption=card_html, parse_mode="HTML"
                )
            return
        except Exception:
            pass

    await update.message.reply_text(card_html, parse_mode="HTML")


def register_handlers(app):
    app.add_handler(CommandHandler("start", handle_start))
    app.add_handler(CommandHandler("assign", handle_assign))
    app.add_handler(CommandHandler("startgame", handle_startgame))
    app.add_handler(CommandHandler("info", handle_info))
    app.add_handler(CommandHandler("debug", handle_debug))
    app.add_handler(CommandHandler("change_gender", handle_change_gender))
    app.add_handler(CallbackQueryHandler(handle_gender_callback, pattern=r"^gender_"))
    app.add_handler(CallbackQueryHandler(handle_change_gender_callback, pattern=r"^change_"))
    app.add_handler(CallbackQueryHandler(handle_assign_player_callback, pattern=r"^assign_p_\d+$"))
    app.add_handler(CallbackQueryHandler(handle_assign_role_callback, pattern=r"^assign_r_.+$"))
    app.add_handler(CallbackQueryHandler(handle_assign_back_callback, pattern=r"^assign_back$"))
    app.add_handler(CallbackQueryHandler(handle_assign_cancel_callback, pattern=r"^assign_cancel$"))
