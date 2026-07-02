"""Tests for database.py — SQLite operations."""

import sys
import os
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Use temp DB
os.environ["DATABASE_PATH"] = "test_db_temp.db"

from database import (
    init_db, init_clues,
    register_player, get_player_by_telegram_id, get_player_by_username,
    get_player_by_id, assign_role, get_active_players, count_active_players,
    deactivate_player, get_player_clues, save_clue_for_player,
    remove_clue_from_player, get_available_clues, mark_clue_found,
    get_found_clue_ids, create_game, get_active_game, update_game_phase,
    increment_game_round, end_game, save_vote, get_votes, get_vote_count,
    clear_votes, add_penalty_vote, get_penalty_votes, clear_penalty_votes,
    save_consent, get_consent_count, clear_consent_votes,
    save_vote_to_history, get_votes_history, mark_alibi_revealed,
    get_stale_voting_games, reset_for_new_game, get_connection,
)

DB = "test_db_temp.db"


def setup_module(module):
    init_db()
    init_clues()


def teardown_module(module):
    if os.path.exists(DB):
        os.remove(DB)


class TestPlayers:
    def setup_method(self):
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM players")
        conn.commit()
        conn.close()

    def test_register_player(self):
        assert register_player(100, "alice")
        p = get_player_by_telegram_id(100)
        assert p is not None
        assert p["username"] == "alice"
        assert p["role"] == ""

    def test_register_duplicate(self):
        register_player(100, "alice")
        assert not register_player(100, "alice2")  # should return False

    def test_get_player_by_username(self):
        register_player(100, "alice")
        p = get_player_by_username("alice")
        assert p is not None
        assert p["telegram_id"] == 100

    def test_get_player_by_id(self):
        register_player(100, "alice")
        p = get_player_by_telegram_id(100)
        p2 = get_player_by_id(p["id"])
        assert p2["telegram_id"] == 100

    def test_assign_role(self):
        register_player(100, "alice")
        assign_role(100, "Анна", "тайный козырь")
        p = get_player_by_telegram_id(100)
        assert p["role"] == "Анна"
        assert p["initial_clue"] == "тайный козырь"
        assert p["alibi_protected"] == 1

    def test_active_players(self):
        register_player(100, "alice")
        register_player(101, "bob")
        register_player(102, "charlie")
        assign_role(100, "Анна", "кл1")
        assign_role(101, "Боб", "кл2")
        active = get_active_players()
        assert len(active) >= 2

    def test_count_active(self):
        register_player(100, "alice")
        register_player(101, "bob")
        assert count_active_players() >= 2

    def test_deactivate_player(self):
        register_player(100, "alice")
        p = get_player_by_telegram_id(100)
        deactivate_player(p["id"])
        p2 = get_player_by_telegram_id(100)
        assert p2["active"] == 0

    def test_player_clues_crud(self):
        register_player(100, "alice")
        save_clue_for_player(100, "clue1")
        assert get_player_clues(100) == ["clue1"]
        save_clue_for_player(100, "clue2")
        assert get_player_clues(100) == ["clue1", "clue2"]
        # Duplicate should not add
        save_clue_for_player(100, "clue1")
        assert len(get_player_clues(100)) == 2
        # Remove
        remove_clue_from_player(100, "clue1")
        assert get_player_clues(100) == ["clue2"]

    def test_alibi_revealed(self):
        register_player(100, "alice")
        assign_role(100, "Анна", "тайна")
        p = get_player_by_telegram_id(100)
        assert p["alibi_protected"] == 1
        mark_alibi_revealed(p["id"])
        p2 = get_player_by_telegram_id(100)
        assert p2["alibi_protected"] == 0


class TestClues:
    def setup_method(self):
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE clues SET found = FALSE")
        conn.commit()
        conn.close()

    def test_available_clues(self):
        available = get_available_clues()
        assert len(available) == 15  # all 15 clues available

    def test_mark_found(self):
        mark_clue_found("clue1")
        available = get_available_clues()
        assert len(available) == 14
        found = get_found_clue_ids()
        assert "clue1" in found

    def test_all_found(self):
        for i in range(1, 16):
            mark_clue_found(f"clue{i}")
        available = get_available_clues()
        assert len(available) == 0
        assert len(get_found_clue_ids()) == 15


class TestGames:
    def setup_method(self):
        reset_for_new_game()

    def test_create_and_get(self):
        gid = create_game(-100123, 999)
        game = get_active_game()
        assert game is not None
        assert game["id"] == gid
        assert game["phase"] == "setup"
        assert game["chat_id"] == -100123
        assert game["admin_id"] == 999

    def test_phase_update(self):
        gid = create_game(-100123, 999)
        update_game_phase(gid, "discussion")
        game = get_active_game()
        assert game["phase"] == "discussion"

    def test_increment_round(self):
        gid = create_game(-100123, 999)
        increment_game_round(gid)
        game = get_active_game()
        assert game["round"] == 1

    def test_end_game(self):
        gid = create_game(-100123, 999)
        end_game(gid)
        game = get_active_game()
        assert game is None  # no longer active

    def test_stale_voting_games(self):
        gid = create_game(-100123, 999)
        update_game_phase(gid, "voting")
        # Force the created_at to be old
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE games SET created_at = '2020-01-01' WHERE id = ?",
            (gid,)
        )
        conn.commit()
        conn.close()
        stale = get_stale_voting_games(60)  # 60 second timeout
        assert len(stale) >= 1
        assert stale[0]["id"] == gid


class TestVoting:
    def setup_method(self):
        reset_for_new_game()
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM players")
        cursor.execute("DELETE FROM votes")
        cursor.execute("DELETE FROM penalty_votes")
        cursor.execute("DELETE FROM consent_votes")
        cursor.execute("DELETE FROM votes_history")
        conn.commit()
        conn.close()

        # Create game and players
        self.game_id = create_game(-100123, 999)
        register_player(1, "p1")
        register_player(2, "p2")
        register_player(3, "p3")
        register_player(4, "p4")
        register_player(5, "p5")
        for uid in [1, 2, 3, 4, 5]:
            assign_role(uid, f"P{uid}", f"secret{uid}")
        self.p1 = get_player_by_telegram_id(1)
        self.p2 = get_player_by_telegram_id(2)
        self.p3 = get_player_by_telegram_id(3)
        self.p4 = get_player_by_telegram_id(4)
        self.p5 = get_player_by_telegram_id(5)

    def test_save_and_get_votes(self):
        save_vote(self.game_id, self.p1["id"], self.p2["id"], 1)
        votes = get_votes(self.game_id, 1)
        assert len(votes) == 1
        assert votes[0]["voter_id"] == self.p1["id"]
        assert votes[0]["target_id"] == self.p2["id"]

    def test_vote_overwrite(self):
        save_vote(self.game_id, self.p1["id"], self.p2["id"], 1)
        save_vote(self.game_id, self.p1["id"], self.p3["id"], 1)  # change vote
        votes = get_votes(self.game_id, 1)
        assert len(votes) == 1
        assert votes[0]["target_id"] == self.p3["id"]

    def test_vote_count(self):
        save_vote(self.game_id, self.p1["id"], self.p2["id"], 1)
        save_vote(self.game_id, self.p3["id"], self.p2["id"], 1)
        assert get_vote_count(self.game_id, 1) == 2

    def test_clear_votes(self):
        save_vote(self.game_id, self.p1["id"], self.p2["id"], 1)
        clear_votes(self.game_id, 1)
        assert get_vote_count(self.game_id, 1) == 0

    def test_penalty_votes(self):
        add_penalty_vote(self.game_id, self.p1["id"], "clue1")
        penalties = get_penalty_votes(self.game_id)
        assert penalties[self.p1["id"]] == 2

    def test_penalty_accumulates(self):
        add_penalty_vote(self.game_id, self.p1["id"], "clue1")
        add_penalty_vote(self.game_id, self.p1["id"], "clue2")
        penalties = get_penalty_votes(self.game_id)
        assert penalties[self.p1["id"]] == 4

    def test_clear_penalty(self):
        add_penalty_vote(self.game_id, self.p1["id"], "clue1")
        clear_penalty_votes(self.game_id)
        assert get_penalty_votes(self.game_id) == {}

    def test_consent_votes(self):
        save_consent(self.game_id, self.p1["id"], True)
        save_consent(self.game_id, self.p2["id"], True)
        assert get_consent_count(self.game_id) == 2
        save_consent(self.game_id, self.p2["id"], False)  # change mind
        assert get_consent_count(self.game_id) == 1  # only p1

    def test_clear_consent(self):
        save_consent(self.game_id, self.p1["id"], True)
        clear_consent_votes(self.game_id)
        assert get_consent_count(self.game_id) == 0

    def test_votes_history(self):
        save_vote_to_history(self.game_id, self.p1["id"], self.p2["id"], 1)
        save_vote_to_history(self.game_id, self.p3["id"], self.p4["id"], 1)
        history = get_votes_history(self.game_id)
        assert len(history) == 2
        assert history[0]["voter_id"] == self.p1["id"]
        assert history[0]["target_id"] == self.p2["id"]


class TestResetForNewGame:
    def test_full_reset(self):
        reset_for_new_game()
        game = get_active_game()
        # No active game should exist
        assert game is None
        # All players active with empty clues
        players = get_active_players()
        for p in players:
            assert json.loads(p["clues_found"]) == []
        # All clues available
        assert len(get_available_clues()) == 15
