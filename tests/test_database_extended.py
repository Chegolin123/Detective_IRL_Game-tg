"""Extended database tests — edge cases, error paths, cleanup."""

import sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ["DATABASE_PATH"] = "test_db_extended.db"

from database import (
    init_db, init_clues, register_player, get_player_by_telegram_id,
    get_player_by_username, get_player_by_id, assign_role,
    get_active_players, count_active_players, deactivate_player,
    get_player_clues, save_clue_for_player, remove_clue_from_player,
    get_available_clues, mark_clue_found, get_found_clue_ids,
    create_game, get_active_game, update_game_phase, increment_game_round,
    end_game, reset_all_games, save_vote, get_votes, get_vote_count,
    clear_votes, add_penalty_vote, get_penalty_votes, clear_penalty_votes,
    save_consent, get_consent_count, clear_consent_votes,
    save_vote_to_history, get_votes_history, mark_alibi_revealed,
    get_stale_voting_games, reset_for_new_game, get_connection,
    cleanup_old_games, set_group_chat_id,
)

DB = "test_db_extended.db"


def setup_module(module):
    init_db()
    init_clues()


def teardown_module(module):
    if os.path.exists(DB):
        os.remove(DB)


class TestPlayerEdgeCases:
    def setup_method(self):
        _clean_all()

    def test_get_nonexistent_player_returns_none(self):
        assert get_player_by_telegram_id(999999) is None
        assert get_player_by_username("nobody") is None
        assert get_player_by_id(99999) is None

    def test_register_empty_username(self):
        assert register_player(200, "")
        p = get_player_by_telegram_id(200)
        assert p is not None
        assert p["username"] == ""

    def test_register_same_id_different_username_fails(self):
        register_player(100, "alice")
        assert not register_player(100, "bob")

    def test_get_player_clues_no_player(self):
        assert get_player_clues(999999) == []

    def test_assign_role_no_player(self):
        assign_role(999999, "Анна", "тайна")
        assert get_player_by_telegram_id(999999) is None

    def test_deactivate_nonexistent_player_doesnt_crash(self):
        deactivate_player(99999)

    def test_mark_alibi_revealed_nonexistent(self):
        mark_alibi_revealed(99999)

    def test_clues_for_inactive_player(self):
        register_player(100, "alice")
        assign_role(100, "Анна", "кл")
        save_clue_for_player(100, "clue1")
        p = get_player_by_telegram_id(100)
        deactivate_player(p["id"])
        clues = get_player_clues(100)
        assert clues == ["clue1"]

    def test_remove_clue_not_present(self):
        register_player(100, "alice")
        save_clue_for_player(100, "clue1")
        remove_clue_from_player(100, "nonexistent")
        assert get_player_clues(100) == ["clue1"]

    def test_remove_clue_no_player(self):
        remove_clue_from_player(999999, "clue1")

    def test_save_clue_duplicate(self):
        register_player(100, "alice")
        save_clue_for_player(100, "clue1")
        save_clue_for_player(100, "clue1")
        assert get_player_clues(100) == ["clue1"]

    def test_register_and_get_multiple_players(self):
        for i in range(10):
            register_player(1000 + i, f"player{i}")
        for i in range(10):
            p = get_player_by_telegram_id(1000 + i)
            assert p is not None
            assert p["username"] == f"player{i}"


class TestClueEdgeCases:
    def setup_method(self):
        _clean_all()
        _reset_clues()

    def test_mark_all_clues_then_check_empty(self):
        for i in range(1, 16):
            mark_clue_found(f"clue{i}")
        assert get_available_clues() == []
        assert len(get_found_clue_ids()) == 15

    def test_mark_same_clue_twice(self):
        mark_clue_found("clue1")
        mark_clue_found("clue1")
        assert len(get_found_clue_ids()) == 1

    def test_get_available_returns_dicts_with_keys(self):
        available = get_available_clues()
        for c in available:
            assert "id" in c
            assert "text" in c
            assert "target" in c
            assert c["found"] == 0  # FALSE


class TestGameEdgeCases:
    def setup_method(self):
        _clean_all()

    def test_get_active_game_none(self):
        assert get_active_game() is None

    def test_multiple_games_active_returns_latest(self):
        g1 = create_game(-100, 1)
        g2 = create_game(-200, 2)
        game = get_active_game()
        # Both are active — should return the latest
        assert game["id"] == g2
        end_game(g2)
        game = get_active_game()
        # g1 is still active
        assert game["id"] == g1
        end_game(g1)
        assert get_active_game() is None

    def test_create_game_with_zero_chat_id(self):
        gid = create_game(0, 1)
        game = get_active_game()
        assert game["id"] == gid
        assert game["chat_id"] == 0

    def test_update_phase_nonexistent_game(self):
        update_game_phase(99999, "discussion")  # should not crash

    def test_increment_round_nonexistent(self):
        increment_game_round(99999)  # should not crash

    def test_end_game_nonexistent(self):
        end_game(99999)  # should not crash

    def test_stale_voting_no_games(self):
        assert get_stale_voting_games(60) == []

    def test_set_group_chat_id(self):
        gid = create_game(0, 1)
        set_group_chat_id(gid, -100123)
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT chat_id FROM games WHERE id = ?", (gid,))
        row = cursor.fetchone()
        conn.close()
        assert row["chat_id"] == -100123

    def test_cleanup_old_games(self):
        """Should not crash on empty DB."""
        cleanup_old_games(days=1)

    def test_reset_all_games_twice(self):
        create_game(-100, 1)
        reset_all_games()
        reset_all_games()  # should not crash


class TestVotingEdgeCases:
    def setup_method(self):
        _clean_all()
        self.game_id = create_game(-100123, 999)
        for uid in [1, 2, 3]:
            register_player(uid, f"p{uid}")
            assign_role(uid, f"P{uid}", f"secret{uid}")

    def test_get_votes_empty_round(self):
        assert get_votes(self.game_id, 99) == []

    def test_get_vote_count_zero(self):
        assert get_vote_count(self.game_id, 1) == 0

    def test_clear_votes_empty_round(self):
        clear_votes(self.game_id, 99)  # should not crash

    def test_get_penalty_votes_empty(self):
        assert get_penalty_votes(self.game_id) == {}

    def test_clear_penalty_empty(self):
        clear_penalty_votes(self.game_id)  # should not crash

    def test_consent_count_zero(self):
        assert get_consent_count(self.game_id) == 0

    def test_clear_consent_empty(self):
        clear_consent_votes(self.game_id)

    def test_save_consent_toggle(self):
        p = get_player_by_telegram_id(1)
        save_consent(self.game_id, p["id"], True)
        assert get_consent_count(self.game_id) == 1
        save_consent(self.game_id, p["id"], False)
        assert get_consent_count(self.game_id) == 0

    def test_votes_history_empty(self):
        assert get_votes_history(self.game_id) == []

    def test_penalty_different_targets(self):
        p1 = get_player_by_telegram_id(1)
        p2 = get_player_by_telegram_id(2)
        add_penalty_vote(self.game_id, p1["id"], "clue1")
        add_penalty_vote(self.game_id, p2["id"], "clue2")
        penalties = get_penalty_votes(self.game_id)
        assert penalties[p1["id"]] == 2
        assert penalties[p2["id"]] == 2

    def test_vote_multiple_rounds(self):
        p1 = get_player_by_telegram_id(1)
        p2 = get_player_by_telegram_id(2)
        save_vote(self.game_id, p1["id"], p2["id"], 1)
        save_vote(self.game_id, p1["id"], p2["id"], 2)
        assert get_vote_count(self.game_id, 1) == 1
        assert get_vote_count(self.game_id, 2) == 1


class TestResetEdgeCases:
    def setup_method(self):
        _clean_all()
        # Create game with some data
        self.game_id = create_game(-100, 999)
        update_game_phase(self.game_id, "voting")
        for uid in [1, 2, 3]:
            register_player(uid, f"p{uid}")
            assign_role(uid, f"P{uid}", f"secret{uid}")

    def test_reset_for_new_game_clears_everything(self):
        reset_for_new_game()
        assert get_active_game() is None
        assert count_active_players() >= 3
        assert len(get_available_clues()) == 15
        assert get_votes(self.game_id, 1) == []
        assert get_penalty_votes(self.game_id) == {}
        assert get_consent_count(self.game_id) == 0

    def test_reset_and_start_again(self):
        reset_for_new_game()
        gid = create_game(-200, 998)
        assert get_active_game() is not None
        assert get_active_game()["id"] == gid

    def test_reset_preserves_players(self):
        register_player(100, "alice")
        assign_role(100, "Анна", "кл")
        reset_for_new_game()
        p = get_player_by_telegram_id(100)
        assert p is not None
        assert p["active"] == 1
        # Role is cleared for fresh auto-assign on new game
        assert p["role"] == ""


# --- Helpers ---

def _clean_all():
    conn = get_connection()
    cursor = conn.cursor()
    for table in ["players", "votes", "penalty_votes", "consent_votes", "votes_history", "games"]:
        cursor.execute(f"DELETE FROM {table}")
    conn.commit()
    conn.close()


def _reset_clues():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE clues SET found = FALSE")
    conn.commit()
    conn.close()
