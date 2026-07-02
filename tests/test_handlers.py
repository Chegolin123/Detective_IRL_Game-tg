"""Handler unit tests — async handlers with mocked Telegram objects."""

import sys, os, pytest
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ["DATABASE_PATH"] = "test_handlers.db"
os.environ["BOT_TOKEN"] = "test:token"
os.environ["ADMIN_ID"] = "999"
os.environ["GROUP_CHAT_ID"] = "-100123"
os.environ["VOTING_TIMEOUT"] = "120"
os.environ["STALE_GAME_TIMEOUT"] = "300"

# Force reimport config with test env vars
import importlib
import config
importlib.reload(config)

from database import init_db, init_clues
from handlers import registration, clues, voting, admin

from game_logic import is_majority_reached

# Reusable mock builders

def make_user(id=1, first_name="Test", username="testuser", is_bot=False):
    user = MagicMock()
    user.id = id
    user.first_name = first_name
    user.username = username
    user.is_bot = is_bot
    return user


def make_chat(id=-100123, type="private"):
    chat = MagicMock()
    chat.id = id
    chat.type = type
    return chat


def make_message(text="/start", chat=None, user=None, message_id=1):
    msg = MagicMock()
    msg.text = text
    msg.message_id = message_id
    msg.chat = chat or make_chat()
    msg.from_user = user or make_user()
    # reply_text is async
    msg.reply_text = AsyncMock()
    return msg


def make_update(message=None, callback_query=None, user=None, chat=None):
    upd = MagicMock()
    upd.effective_user = user or make_user()
    upd.effective_chat = chat or make_chat()
    upd.message = message
    upd.callback_query = callback_query
    return upd


def make_context():
    ctx = MagicMock()
    ctx.bot.send_message = AsyncMock()
    ctx.bot.edit_message_text = AsyncMock()
    ctx.bot.edit_message_reply_markup = AsyncMock()
    ctx.args = []
    ctx.job_queue = MagicMock()
    ctx.job_queue.run_once = MagicMock()
    ctx.job_queue.jobs = MagicMock(return_value=[])
    ctx.job_data = {}
    return ctx


def make_callback_query(data="consent_yes", user=None, message=None):
    q = MagicMock()
    q.data = data
    q.from_user = user or make_user()
    q.message = message or make_message()
    q.answer = AsyncMock()
    q.edit_message_text = AsyncMock()
    return q


# --- Fixtures ---

@pytest.fixture(autouse=True)
def db_setup_teardown():
    from database import get_connection
    init_db()
    init_clues()
    admin._awaiting_final_confirmation = False
    yield
    admin._awaiting_final_confirmation = False
    conn = get_connection()
    cursor = conn.cursor()
    for table in ["players", "votes", "penalty_votes", "consent_votes", "votes_history", "games"]:
        cursor.execute(f"DELETE FROM {table}")
    conn.commit()
    conn.close()


def _setup_game_with_players():
    from database import (
        create_game, update_game_phase, register_player, assign_role,
        get_player_by_telegram_id
    )
    gid = create_game(-100123, 999)
    update_game_phase(gid, "discussion")
    for uid, role_name, clue in [
        (1, "Анна", "тайна1"),
        (2, "Максим", "тайна2"),
        (3, "Роман", "тайна3"),
    ]:
        register_player(uid, f"p{uid}")
        assign_role(uid, role_name, clue)
    players = {uid: get_player_by_telegram_id(uid) for uid in [1, 2, 3]}
    return gid, players


# ============================================================
# Registration handler tests
# ============================================================

class TestHandleStart:
    @pytest.mark.asyncio
    async def test_start_registers_new_user(self):
        user = make_user(id=9999, username="newbie")
        msg = make_message("/start", user=user)
        upd = make_update(message=msg, user=user)
        ctx = make_context()
        await registration.handle_start(upd, ctx)
        msg.reply_text.assert_awaited_once()
        reply = msg.reply_text.call_args[0][0]
        assert "Добро пожаловать" in reply or "Ожидайте" in reply

    @pytest.mark.asyncio
    async def test_start_existing_user_without_role(self):
        from database import register_player, set_player_gender
        register_player(1, "existing")
        set_player_gender(1, "male")
        user = make_user(id=1)
        msg = make_message("/start", user=user)
        upd = make_update(message=msg, user=user)
        ctx = make_context()
        await registration.handle_start(upd, ctx)
        msg.reply_text.assert_awaited_once()
        assert "Ожидайте" in msg.reply_text.call_args[0][0]

    @pytest.mark.asyncio
    async def test_start_existing_user_with_role(self):
        from database import register_player, assign_role
        register_player(1, "player1")
        assign_role(1, "Анна", "козырь")
        user = make_user(id=1)
        msg = make_message("/start", user=user)
        upd = make_update(message=msg, user=user)
        ctx = make_context()
        await registration.handle_start(upd, ctx)
        msg.reply_text.assert_awaited_once()
        assert "Анна" in msg.reply_text.call_args[0][0]

    @pytest.mark.asyncio
    async def test_start_qr_scan(self):
        from database import register_player, assign_role
        register_player(1, "player1")
        assign_role(1, "Анна", "козырь")
        user = make_user(id=1)
        msg = make_message("/start qr", user=user)
        upd = make_update(message=msg, user=user)
        ctx = make_context()
        await registration.handle_start(upd, ctx)
        # Should redirect to QR handler — which needs available clues
        msg.reply_text.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_start_auto_assign_admin_when_zero(self):
        original = config.ADMIN_ID
        config.ADMIN_ID = 0
        try:
            user = make_user(id=42, username="firstadmin")
            msg = make_message("/start", user=user)
            upd = make_update(message=msg, user=user)
            ctx = make_context()
            await registration.handle_start(upd, ctx)
            msg.reply_text.assert_awaited_once()
            assert "ведущим" in msg.reply_text.call_args[0][0]
            assert config.ADMIN_ID == 42
        finally:
            config.ADMIN_ID = original

    @pytest.mark.asyncio
    async def test_start_no_user_does_nothing(self):
        user = None
        msg = make_message("/start", user=None)
        upd = make_update(message=msg, user=None)
        # Override effective_user to be explicitly None
        upd.effective_user = None
        ctx = make_context()
        await registration.handle_start(upd, ctx)
        # Should silently return — reply_text should not be called
        msg.reply_text.assert_not_called()


class TestHandleAssign:
    @pytest.mark.asyncio
    async def test_assign_success(self):
        from database import register_player
        register_player(1, "player1")
        user = make_user(id=999)  # admin
        msg = make_message(user=user)
        msg.reply_text = AsyncMock()
        upd = make_update(message=msg, user=user)
        ctx = make_context()
        ctx.args = ["@player1", "Анна"]
        await registration.handle_assign(upd, ctx)
        msg.reply_text.assert_awaited()
        assert "назначена" in msg.reply_text.call_args[0][0]

    @pytest.mark.asyncio
    async def test_assign_not_admin(self):
        user = make_user(id=1)  # not admin
        msg = make_message(user=user)
        upd = make_update(message=msg, user=user)
        ctx = make_context()
        ctx.args = ["@someone", "Анна"]
        await registration.handle_assign(upd, ctx)
        msg.reply_text.assert_awaited_once()
        assert "только для ведущего" in msg.reply_text.call_args[0][0]

    @pytest.mark.asyncio
    async def test_assign_missing_args(self):
        from database import register_player
        register_player(1, "player1")
        register_player(2, "player2")
        user = make_user(id=999)
        msg = make_message(user=user)
        upd = make_update(message=msg, user=user)
        ctx = make_context()
        ctx.args = ["@player1"]
        await registration.handle_assign(upd, ctx)
        msg.reply_text.assert_awaited_once()
        assert "Назначение ролей" in msg.reply_text.call_args[0][0]

    @pytest.mark.asyncio
    async def test_assign_invalid_role(self):
        from database import register_player
        register_player(1, "player1")
        user = make_user(id=999)
        msg = make_message(user=user)
        upd = make_update(message=msg, user=user)
        ctx = make_context()
        ctx.args = ["@player1", "НесуществующаяРоль"]
        await registration.handle_assign(upd, ctx)
        msg.reply_text.assert_awaited_once()
        assert "не найден" in msg.reply_text.call_args[0][0]

    @pytest.mark.asyncio
    async def test_assign_unregistered_user(self):
        user = make_user(id=999)
        msg = make_message(user=user)
        upd = make_update(message=msg, user=user)
        ctx = make_context()
        ctx.args = ["@unknown", "Анна"]
        await registration.handle_assign(upd, ctx)
        msg.reply_text.assert_awaited_once()
        assert "не зарегистрирован" in msg.reply_text.call_args[0][0]


class TestHandleStartGame:
    @pytest.mark.asyncio
    async def test_startgame_not_admin(self):
        user = make_user(id=1)
        msg = make_message(user=user)
        upd = make_update(message=msg, user=user)
        ctx = make_context()
        await registration.handle_startgame(upd, ctx)
        msg.reply_text.assert_awaited_once()
        assert "только для ведущего" in msg.reply_text.call_args[0][0]

    @pytest.mark.asyncio
    async def test_startgame_success(self):
        from database import register_player, set_player_gender
        for i in range(4):
            register_player(100 + i, f"player{i}")
            set_player_gender(100 + i, "male" if i < 2 else "female")
        user = make_user(id=999)
        msg = make_message(user=user)
        upd = make_update(message=msg, user=user)
        ctx = make_context()
        await registration.handle_startgame(upd, ctx)
        msg.reply_text.assert_awaited()
        assert "началась" in msg.reply_text.call_args[0][0]


class TestHandleInfo:
    @pytest.mark.asyncio
    async def test_info_no_role(self):
        from database import register_player
        register_player(1, "player1")
        user = make_user(id=1)
        msg = make_message(user=user)
        upd = make_update(message=msg, user=user)
        ctx = make_context()
        await registration.handle_info(upd, ctx)
        msg.reply_text.assert_awaited_once()
        assert "ещё не назначена" in msg.reply_text.call_args[0][0]

    @pytest.mark.asyncio
    async def test_info_with_role(self):
        from database import register_player, assign_role
        register_player(1, "player1")
        assign_role(1, "Анна", "козырь")
        user = make_user(id=1)
        msg = make_message(user=user)
        upd = make_update(message=msg, user=user)
        ctx = make_context()
        await registration.handle_info(upd, ctx)
        msg.reply_text.assert_awaited_once()
        reply = msg.reply_text.call_args[0][0]
        assert "Анна" in reply
        assert "козырь" in reply


# ============================================================
# Admin handler tests
# ============================================================

class TestHandleStatus:
    @pytest.mark.asyncio
    async def test_status_not_admin(self):
        user = make_user(id=1)
        msg = make_message(user=user)
        upd = make_update(message=msg, user=user)
        ctx = make_context()
        await admin.handle_status(upd, ctx)
        msg.reply_text.assert_awaited_once()
        assert "только для ведущего" in msg.reply_text.call_args[0][0]

    @pytest.mark.asyncio
    async def test_status_no_game(self):
        user = make_user(id=999)
        msg = make_message(user=user)
        upd = make_update(message=msg, user=user)
        ctx = make_context()
        await admin.handle_status(upd, ctx)
        msg.reply_text.assert_awaited_once()
        assert "Нет активной игры" in msg.reply_text.call_args[0][0]

    @pytest.mark.asyncio
    async def test_status_with_game(self):
        _setup_game_with_players()
        user = make_user(id=999)
        msg = make_message(user=user)
        upd = make_update(message=msg, user=user)
        ctx = make_context()
        await admin.handle_status(upd, ctx)
        msg.reply_text.assert_awaited_once()


class TestHandleHelp:
    @pytest.mark.asyncio
    async def test_help_for_regular_user(self):
        user = make_user(id=1)
        msg = make_message(user=user)
        upd = make_update(message=msg, user=user)
        ctx = make_context()
        await admin.handle_help(upd, ctx)
        msg.reply_text.assert_awaited_once()
        reply = msg.reply_text.call_args[0][0]
        assert "Команды игроков" in reply
        # Should NOT contain admin commands for regular user
        assert "Команды ведущего" not in reply

    @pytest.mark.asyncio
    async def test_help_for_admin(self):
        user = make_user(id=999)
        msg = make_message(user=user)
        upd = make_update(message=msg, user=user)
        ctx = make_context()
        await admin.handle_help(upd, ctx)
        msg.reply_text.assert_awaited_once()
        reply = msg.reply_text.call_args[0][0]
        assert "Команды ведущего" in reply
        assert "Команды игроков" in reply


class TestHandleFinal:
    @pytest.mark.asyncio
    async def test_final_not_admin(self):
        user = make_user(id=1)
        msg = make_message(user=user)
        upd = make_update(message=msg, user=user)
        ctx = make_context()
        await admin.handle_final(upd, ctx)
        msg.reply_text.assert_awaited_once()
        assert "только для ведущего" in msg.reply_text.call_args[0][0]

    @pytest.mark.asyncio
    async def test_final_no_game(self):
        user = make_user(id=999)
        msg = make_message(user=user)
        upd = make_update(message=msg, user=user)
        ctx = make_context()
        await admin.handle_final(upd, ctx)
        msg.reply_text.assert_awaited_once()
        assert "Нет активной игры" in msg.reply_text.call_args[0][0]

    @pytest.mark.asyncio
    async def test_final_too_many_players(self):
        gid, players = _setup_game_with_players()
        # We have 3 players — that should be <=3 so fine
        user = make_user(id=999)
        msg = make_message(user=user)
        upd = make_update(message=msg, user=user)
        ctx = make_context()
        await admin.handle_final(upd, ctx)
        # Should proceed with finale
        msg.reply_text.assert_awaited()

    @pytest.mark.asyncio
    async def test_final_success(self):
        from database import register_player, assign_role, mark_clue_found
        gid, players = _setup_game_with_players()
        mark_clue_found("clue4")
        user = make_user(id=999)
        msg = make_message(user=user)
        upd = make_update(message=msg, user=user)
        ctx = make_context()
        await admin.handle_final(upd, ctx)
        msg.reply_text.assert_awaited()
        # Now it asks for confirmation
        reply = msg.reply_text.call_args[0][0]
        assert "/confirm_final" in reply

    @pytest.mark.asyncio
    async def test_confirm_final_no_await(self):
        user = make_user(id=999)
        msg = make_message(user=user)
        upd = make_update(message=msg, user=user)
        ctx = make_context()
        await admin.handle_confirm_final(upd, ctx)
        msg.reply_text.assert_awaited()
        reply = msg.reply_text.call_args[0][0]
        assert "/final" in reply

    @pytest.mark.asyncio
    async def test_confirm_final_success(self):
        from database import mark_clue_found
        gid, players = _setup_game_with_players()
        mark_clue_found("clue4")
        admin._awaiting_final_confirmation = True
        user = make_user(id=999)
        msg = make_message(user=user)
        upd = make_update(message=msg, user=user)
        ctx = make_context()
        await admin.handle_confirm_final(upd, ctx)
        ctx.bot.send_message.assert_awaited()
        admin._awaiting_final_confirmation = False

    @pytest.mark.asyncio
    async def test_setgroup_admin(self):
        user = make_user(id=999)
        chat = make_chat(id=-100456, type="group")
        msg = make_message("/setgroup", user=user, chat=chat)
        upd = make_update(message=msg, user=user, chat=chat)
        ctx = make_context()
        await admin.handle_setgroup(upd, ctx)
        msg.reply_text.assert_awaited_once()
        assert "✅" in msg.reply_text.call_args[0][0]
        assert config.GROUP_CHAT_ID == -100456

    @pytest.mark.asyncio
    async def test_setgroup_non_admin_silent(self):
        user = make_user(id=1)
        chat = make_chat(id=-100456, type="group")
        msg = make_message("/setgroup", user=user, chat=chat)
        upd = make_update(message=msg, user=user, chat=chat)
        ctx = make_context()
        await admin.handle_setgroup(upd, ctx)
        msg.reply_text.assert_not_called()


# ============================================================
# Clues handler tests
# ============================================================

class TestHandleMyClues:
    @pytest.mark.asyncio
    async def test_myclues_empty(self):
        from database import register_player
        register_player(1, "player1")
        user = make_user(id=1)
        msg = make_message(user=user)
        upd = make_update(message=msg, user=user)
        ctx = make_context()
        await clues.handle_myclues(upd, ctx)
        msg.reply_text.assert_awaited_once()
        assert "нет" in msg.reply_text.call_args[0][0]

    @pytest.mark.asyncio
    async def test_myclues_with_clues(self):
        from database import register_player, save_clue_for_player
        register_player(1, "player1")
        save_clue_for_player(1, "clue1")
        user = make_user(id=1)
        msg = make_message(user=user)
        upd = make_update(message=msg, user=user)
        ctx = make_context()
        await clues.handle_myclues(upd, ctx)
        msg.reply_text.assert_awaited_once()
        reply = msg.reply_text.call_args[0][0]
        assert "улики" in reply
        assert "clue1" not in reply  # should show actual text


class TestHandlePublish:
    @pytest.mark.asyncio
    async def test_publish_no_clues(self):
        from database import register_player
        register_player(1, "player1")
        user = make_user(id=1)
        msg = make_message(user=user)
        upd = make_update(message=msg, user=user)
        ctx = make_context()
        await clues.handle_publish(upd, ctx)
        msg.reply_text.assert_awaited_once()
        assert "нет улик" in msg.reply_text.call_args[0][0]

    @pytest.mark.asyncio
    async def test_publish_success(self):
        from database import register_player, assign_role, save_clue_for_player
        register_player(1, "player1")
        assign_role(1, "Анна", "козырь")
        save_clue_for_player(1, "clue1")
        user = make_user(id=1)
        msg = make_message(user=user)
        upd = make_update(message=msg, user=user)
        ctx = make_context()
        await clues.handle_publish(upd, ctx)
        msg.reply_text.assert_awaited()
        # Now shows clue selection keyboard, not direct publish
        reply = msg.reply_text.call_args[1]
        assert "reply_markup" in reply


class TestHandleUse:
    @pytest.mark.asyncio
    async def test_use_game_not_in_voting(self):
        from database import register_player
        register_player(1, "player1")
        user = make_user(id=1)
        msg = make_message(user=user)
        upd = make_update(message=msg, user=user)
        ctx = make_context()
        await clues.handle_use(upd, ctx)
        msg.reply_text.assert_awaited_once()
        assert "Дождитесь" in msg.reply_text.call_args[0][0]

    @pytest.mark.asyncio
    async def test_use_during_voting_no_clues(self):
        from database import register_player, assign_role, create_game, update_game_phase
        register_player(1, "player1")
        assign_role(1, "Анна", "козырь")
        gid = create_game(-100, 999)
        update_game_phase(gid, "voting")
        user = make_user(id=1)
        msg = make_message(user=user)
        upd = make_update(message=msg, user=user)
        ctx = make_context()
        await clues.handle_use(upd, ctx)
        msg.reply_text.assert_awaited_once()
        assert "нет сохранённых улик" in msg.reply_text.call_args[0][0]

    @pytest.mark.asyncio
    async def test_use_during_voting_success(self):
        from database import (
            register_player, assign_role, create_game, update_game_phase,
            save_clue_for_player
        )
        register_player(1, "player1")
        assign_role(1, "Анна", "козырь")
        gid = create_game(-100, 999)
        update_game_phase(gid, "voting")
        save_clue_for_player(1, "clue1")
        user = make_user(id=1)
        msg = make_message(user=user)
        upd = make_update(message=msg, user=user)
        ctx = make_context()
        await clues.handle_use(upd, ctx)
        msg.reply_text.assert_awaited()


class TestHandleQrScan:
    @pytest.mark.asyncio
    async def test_qr_no_role(self):
        from database import register_player
        register_player(1, "player1")
        user = make_user(id=1)
        msg = make_message(user=user)
        upd = make_update(message=msg, user=user)
        ctx = make_context()
        player = {"role": "", "id": 1}
        await clues.handle_qr_scan(upd, ctx, player)
        msg.reply_text.assert_awaited_once()
        assert "ещё не назначена" in msg.reply_text.call_args[0][0]

    @pytest.mark.asyncio
    async def test_qr_success(self):
        from database import register_player, assign_role
        register_player(1, "player1")
        assign_role(1, "Анна", "козырь")
        user = make_user(id=1)
        msg = make_message(user=user)
        upd = make_update(message=msg, user=user)
        ctx = make_context()
        player = {"role": "Анна", "id": 1}
        await clues.handle_qr_scan(upd, ctx, player)
        msg.reply_text.assert_awaited()
        assert "нашли улику" in msg.reply_text.call_args[0][0]

    @pytest.mark.asyncio
    async def test_qr_max_clues_reached(self):
        from database import register_player, assign_role, save_clue_for_player
        register_player(1, "player1")
        assign_role(1, "Анна", "козырь")
        for i in range(1, 4):
            save_clue_for_player(1, f"clue{i}")
        user = make_user(id=1)
        msg = make_message(user=user)
        upd = make_update(message=msg, user=user)
        ctx = make_context()
        player = {"role": "Анна", "id": 1}
        await clues.handle_qr_scan(upd, ctx, player)
        msg.reply_text.assert_awaited_once()
        assert "уже нашли 3" in msg.reply_text.call_args[0][0]


# ============================================================
# Voting handler tests
# ============================================================

class TestHandleConsentCallback:
    @pytest.mark.asyncio
    async def test_consent_not_a_player(self):
        user = make_user(id=999)
        cq = make_callback_query(user=user)
        upd = MagicMock()
        upd.effective_user = user
        upd.callback_query = cq
        ctx = make_context()
        await voting.handle_consent_callback(upd, ctx)
        cq.answer.assert_awaited_once()
        cq.edit_message_text.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_consent_success(self):
        gid, players = _setup_game_with_players()
        user = make_user(id=1)
        cq = make_callback_query(user=user)
        upd = MagicMock()
        upd.effective_user = user
        upd.callback_query = cq
        ctx = make_context()
        await voting.handle_consent_callback(upd, ctx)
        cq.answer.assert_awaited_once()
        cq.edit_message_text.assert_awaited_once()
        assert "✅" in cq.edit_message_text.call_args[0][0]

    @pytest.mark.asyncio
    async def test_consent_not_in_discussion(self):
        from database import create_game, update_game_phase, register_player, assign_role
        gid = create_game(-100, 999)
        update_game_phase(gid, "voting")
        register_player(1, "p1")
        assign_role(1, "Анна", "кл")
        user = make_user(id=1)
        cq = make_callback_query(user=user)
        upd = MagicMock()
        upd.effective_user = user
        upd.callback_query = cq
        ctx = make_context()
        await voting.handle_consent_callback(upd, ctx)
        cq.edit_message_text.assert_awaited()
        assert "нельзя" in cq.edit_message_text.call_args[0][0]

    @pytest.mark.asyncio
    async def test_consent_reaches_majority(self):
        from database import get_player_by_telegram_id, save_consent
        gid, players = _setup_game_with_players()
        # Pre-save consent for player 3 so player 2's consent triggers majority
        save_consent(gid, players[3]["id"], True)
        user = make_user(id=2)
        cq = make_callback_query(user=user)
        upd = MagicMock()
        upd.effective_user = user
        upd.callback_query = cq
        ctx = make_context()
        await voting.handle_consent_callback(upd, ctx)
        cq.answer.assert_awaited()
        # Should have triggered voting start
        ctx.bot.send_message.assert_awaited()


class TestHandleVoteCallback:
    @pytest.mark.asyncio
    async def test_vote_success(self):
        from database import create_game, update_game_phase, register_player, assign_role
        gid = create_game(-100, 999)
        update_game_phase(gid, "voting")
        register_player(1, "p1")
        assign_role(1, "Анна", "кл")
        register_player(2, "p2")
        assign_role(2, "Максим", "кл2")
        user = make_user(id=1)
        cq = make_callback_query(data="vote_2", user=user)
        upd = MagicMock()
        upd.effective_user = user
        upd.callback_query = cq
        ctx = make_context()
        await voting.handle_vote_callback(upd, ctx)
        # answer() is called at handler start + with result message = 2 total
        assert cq.answer.await_count == 2
        assert "учтён" in cq.answer.call_args[0][0]

    @pytest.mark.asyncio
    async def test_vote_not_active_player(self):
        from database import register_player
        register_player(1, "p1")
        user = make_user(id=1)
        cq = make_callback_query(data="vote_2", user=user)
        upd = MagicMock()
        upd.effective_user = user
        upd.callback_query = cq
        ctx = make_context()
        await voting.handle_vote_callback(upd, ctx)
        assert cq.answer.await_count == 2
        assert "завершено" in cq.answer.call_args[0][0]


# ============================================================
# Game logic extended tests
# ============================================================

class TestCalculateResultsExtended:
    def test_no_players_zero_division_no_crash(self):
        result = calculate_results([], {}, 0)
        assert not result["has_votes"]
        assert not result["turnout_ok"]

    def test_all_alive_vote_same(self):
        votes = [{"target_id": 1} for _ in range(5)]
        result = calculate_results(votes, {}, 5)
        assert result["unanimous"]
        assert result["turnout_ok"]
        assert result["candidates"] == [1]

    def test_penalties_on_top_of_unanimous(self):
        votes = [{"target_id": 1}, {"target_id": 1}]
        penalties = {1: 2}
        result = calculate_results(votes, penalties, 5)
        assert result["max_votes"] == 4
        assert result["candidates"] == [1]


class TestIsMajorityReachedExtended:
    def test_zero_players(self):
        assert not is_majority_reached(0, 0)

    def test_zero_consent(self):
        assert not is_majority_reached(0, 5)

    def test_one_player_majority(self):
        assert is_majority_reached(1, 1)


# Don't redefine — import at module level
from game_logic import calculate_results
