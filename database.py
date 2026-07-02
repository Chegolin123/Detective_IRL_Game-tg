import sqlite3
import json
import os
from datetime import datetime

DB_PATH = os.getenv("DATABASE_PATH", "game.db")


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS players (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER UNIQUE NOT NULL,
            username TEXT,
            gender TEXT DEFAULT '',
            role TEXT DEFAULT '',
            role_description TEXT DEFAULT '',
            initial_clue TEXT DEFAULT '',
            personal_goal TEXT DEFAULT '',
            active BOOLEAN DEFAULT TRUE,
            alibi_protected BOOLEAN DEFAULT TRUE,
            clues_found TEXT DEFAULT '[]',
            pair_id TEXT,
            round_eliminated INTEGER
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS clues (
            id TEXT PRIMARY KEY,
            text TEXT NOT NULL,
            target TEXT,
            found BOOLEAN DEFAULT FALSE
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS games (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER NOT NULL,
            admin_id INTEGER NOT NULL,
            is_active BOOLEAN DEFAULT FALSE,
            phase TEXT DEFAULT 'setup',
            round INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS votes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            game_id INTEGER NOT NULL,
            voter_id INTEGER NOT NULL,
            target_id INTEGER NOT NULL,
            round INTEGER NOT NULL,
            FOREIGN KEY (game_id) REFERENCES games(id),
            FOREIGN KEY (voter_id) REFERENCES players(id),
            FOREIGN KEY (target_id) REFERENCES players(id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS penalty_votes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            game_id INTEGER NOT NULL,
            target_id INTEGER NOT NULL,
            count INTEGER DEFAULT 0,
            source_clue_id TEXT,
            FOREIGN KEY (game_id) REFERENCES games(id),
            FOREIGN KEY (target_id) REFERENCES players(id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS consent_votes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            game_id INTEGER NOT NULL,
            player_id INTEGER NOT NULL,
            agreed BOOLEAN DEFAULT FALSE,
            FOREIGN KEY (game_id) REFERENCES games(id),
            FOREIGN KEY (player_id) REFERENCES players(id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS votes_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            game_id INTEGER NOT NULL,
            voter_id INTEGER NOT NULL,
            target_id INTEGER NOT NULL,
            round INTEGER NOT NULL,
            FOREIGN KEY (game_id) REFERENCES games(id),
            FOREIGN KEY (voter_id) REFERENCES players(id),
            FOREIGN KEY (target_id) REFERENCES players(id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS game_stats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            game_id INTEGER NOT NULL UNIQUE,
            first_qr_scanner_id INTEGER,
            clues_found_total INTEGER DEFAULT 0,
            most_clues_player_id INTEGER,
            FOREIGN KEY (game_id) REFERENCES games(id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS achievements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            game_id INTEGER NOT NULL,
            player_id INTEGER NOT NULL,
            achievement TEXT NOT NULL,
            FOREIGN KEY (game_id) REFERENCES games(id),
            FOREIGN KEY (player_id) REFERENCES players(id)
        )
    """)

    # Add missing columns for migrations
    for col in ["gender", "role_description", "personal_goal", "pair_id", "round_eliminated"]:
        try:
            if col == "round_eliminated":
                cursor.execute(f"ALTER TABLE players ADD COLUMN {col} INTEGER")
            else:
                cursor.execute(f"ALTER TABLE players ADD COLUMN {col} TEXT DEFAULT ''")
        except sqlite3.OperationalError:
            pass  # column already exists

    conn.commit()
    conn.close()


# --- Players ---

def register_player(telegram_id: int, username: str, gender: str = "") -> bool:
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO players (telegram_id, username, gender, role, initial_clue, active, alibi_protected, clues_found) "
            "VALUES (?, ?, ?, '', '', TRUE, TRUE, '[]')",
            (telegram_id, username, gender)
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()


def get_player_by_telegram_id(telegram_id: int):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM players WHERE telegram_id = ?", (telegram_id,))
    row = cursor.fetchone()
    conn.close()
    return row


def get_player_by_id(player_id: int):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM players WHERE id = ?", (player_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def get_player_by_username(username: str):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM players WHERE username = ?", (username,))
    row = cursor.fetchone()
    conn.close()
    return row


def get_all_players() -> list:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM players")
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_unassigned_players() -> list:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM players WHERE role = '' OR role IS NULL")
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_assigned_roles() -> list:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT role FROM players WHERE role != '' AND role IS NOT NULL")
    rows = cursor.fetchall()
    conn.close()
    return [r["role"] for r in rows]


def assign_role(telegram_id: int, role_name: str, initial_clue: str,
                role_description: str = "", personal_goal: str = "",
                pair_id: str = None):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE players SET role = ?, role_description = ?, initial_clue = ?, "
        "personal_goal = ?, alibi_protected = TRUE, pair_id = ? WHERE telegram_id = ?",
        (role_name, role_description, initial_clue, personal_goal, pair_id, telegram_id)
    )
    conn.commit()
    conn.close()


def get_active_players():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM players WHERE active = TRUE")
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def count_active_players() -> int:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) as cnt FROM players WHERE active = TRUE")
    row = cursor.fetchone()
    conn.close()
    return row["cnt"] if row else 0


def deactivate_player(player_id: int):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE players SET active = FALSE WHERE id = ?", (player_id,))
    conn.commit()
    conn.close()


def get_player_clues(telegram_id: int) -> list:
    player = get_player_by_telegram_id(telegram_id)
    if not player:
        return []
    return json.loads(player["clues_found"])


def save_clue_for_player(telegram_id: int, clue_id: str):
    clues = get_player_clues(telegram_id)
    if clue_id not in clues:
        clues.append(clue_id)
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE players SET clues_found = ? WHERE telegram_id = ?",
                   (json.dumps(clues, ensure_ascii=False), telegram_id))
    conn.commit()
    conn.close()


def remove_clue_from_player(telegram_id: int, clue_id: str):
    clues = get_player_clues(telegram_id)
    if clue_id in clues:
        clues.remove(clue_id)
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE players SET clues_found = ? WHERE telegram_id = ?",
                   (json.dumps(clues, ensure_ascii=False), telegram_id))
    conn.commit()
    conn.close()


# --- Clues ---

def init_clues():
    from data import CLUES
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) as cnt FROM clues")
    row = cursor.fetchone()
    if row and row["cnt"] > 0:
        conn.close()
        return
    for cid, cdata in CLUES.items():
        target = cdata["target"]
        if isinstance(target, list):
            target = json.dumps(target, ensure_ascii=False)
        cursor.execute(
            "INSERT INTO clues (id, text, target, found) VALUES (?, ?, ?, FALSE)",
            (cid, cdata["text"], target)
        )
    conn.commit()
    conn.close()


def get_available_clues() -> list:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM clues WHERE found = FALSE")
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def mark_clue_found(clue_id: str):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE clues SET found = TRUE WHERE id = ?", (clue_id,))
    conn.commit()
    conn.close()


def get_found_clue_ids() -> list:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM clues WHERE found = TRUE")
    rows = cursor.fetchall()
    conn.close()
    return [r["id"] for r in rows]


# --- Games ---

def create_game(chat_id: int, admin_id: int) -> int:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO games (chat_id, admin_id, is_active, phase, round) VALUES (?, ?, TRUE, 'setup', 0)",
        (chat_id, admin_id)
    )
    conn.commit()
    game_id = cursor.lastrowid
    conn.close()
    return game_id


def get_active_game():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM games WHERE is_active = TRUE ORDER BY id DESC LIMIT 1")
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def update_game_phase(game_id: int, phase: str):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE games SET phase = ? WHERE id = ?", (phase, game_id))
    conn.commit()
    conn.close()


def increment_game_round(game_id: int):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE games SET round = round + 1 WHERE id = ?", (game_id,))
    conn.commit()
    conn.close()


def end_game(game_id: int):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE games SET is_active = FALSE, phase = 'finished' WHERE id = ?", (game_id,))
    conn.commit()
    conn.close()


def reset_all_games():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE games SET is_active = FALSE, phase = 'finished'")
    cursor.execute("UPDATE players SET active = FALSE")
    conn.commit()
    conn.close()


# --- Voting ---

def save_vote(game_id: int, voter_id: int, target_id: int, round_num: int):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "DELETE FROM votes WHERE game_id = ? AND voter_id = ? AND round = ?",
        (game_id, voter_id, round_num)
    )
    cursor.execute(
        "INSERT INTO votes (game_id, voter_id, target_id, round) VALUES (?, ?, ?, ?)",
        (game_id, voter_id, target_id, round_num)
    )
    conn.commit()
    conn.close()


def get_votes(game_id: int, round_num: int) -> list:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM votes WHERE game_id = ? AND round = ?",
        (game_id, round_num)
    )
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_vote_count(game_id: int, round_num: int) -> int:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT COUNT(*) as cnt FROM votes WHERE game_id = ? AND round = ?",
        (game_id, round_num)
    )
    row = cursor.fetchone()
    conn.close()
    return row["cnt"] if row else 0


def clear_votes(game_id: int, round_num: int):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM votes WHERE game_id = ? AND round = ?", (game_id, round_num))
    conn.commit()
    conn.close()


# --- Penalty Votes ---

def add_penalty_vote(game_id: int, target_id: int, clue_id: str):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM penalty_votes WHERE game_id = ? AND target_id = ? AND source_clue_id = ?",
        (game_id, target_id, clue_id)
    )
    existing = cursor.fetchone()
    if existing:
        cursor.execute(
            "UPDATE penalty_votes SET count = count + 2 WHERE id = ?",
            (existing["id"],)
        )
    else:
        cursor.execute(
            "INSERT INTO penalty_votes (game_id, target_id, count, source_clue_id) VALUES (?, ?, 2, ?)",
            (game_id, target_id, clue_id)
        )
    conn.commit()
    conn.close()


def get_penalty_votes(game_id: int) -> dict:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM penalty_votes WHERE game_id = ?", (game_id,))
    rows = cursor.fetchall()
    conn.close()
    result = {}
    for r in rows:
        result[r["target_id"]] = result.get(r["target_id"], 0) + r["count"]
    return result


def clear_penalty_votes(game_id: int):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM penalty_votes WHERE game_id = ?", (game_id,))
    conn.commit()
    conn.close()


# --- Consent Votes ---

def save_consent(game_id: int, player_id: int, agreed: bool):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "DELETE FROM consent_votes WHERE game_id = ? AND player_id = ?",
        (game_id, player_id)
    )
    cursor.execute(
        "INSERT INTO consent_votes (game_id, player_id, agreed) VALUES (?, ?, ?)",
        (game_id, player_id, agreed)
    )
    conn.commit()
    conn.close()


def get_consent_count(game_id: int) -> int:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT COUNT(*) as cnt FROM consent_votes WHERE game_id = ? AND agreed = TRUE",
        (game_id,)
    )
    row = cursor.fetchone()
    conn.close()
    return row["cnt"] if row else 0


def clear_consent_votes(game_id: int):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM consent_votes WHERE game_id = ?", (game_id,))
    conn.commit()
    conn.close()


# --- Votes History (for finale) ---

def save_vote_to_history(game_id: int, voter_id: int, target_id: int, round_num: int):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO votes_history (game_id, voter_id, target_id, round) VALUES (?, ?, ?, ?)",
        (game_id, voter_id, target_id, round_num)
    )
    conn.commit()
    conn.close()


def get_votes_history(game_id: int) -> list:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM votes_history WHERE game_id = ?", (game_id,)
    )
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


# --- Alibi ---

def mark_alibi_revealed(player_id: int):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE players SET alibi_protected = FALSE WHERE id = ?", (player_id,))
    conn.commit()
    conn.close()


# --- Maintenance ---

def get_stale_voting_games(timeout_seconds: int) -> list:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT * FROM games
        WHERE is_active = TRUE AND phase = 'voting'
        AND (julianday('now') - julianday(created_at)) * 86400 > ?
    """, (timeout_seconds,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def cleanup_old_games(days: int = 7):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        DELETE FROM votes_history WHERE game_id IN
        (SELECT id FROM games WHERE created_at < datetime('now', ?))
    """, (f'-{days} days',))
    cursor.execute("""
        DELETE FROM games WHERE created_at < datetime('now', ?)
    """, (f'-{days} days',))
    conn.commit()
    conn.close()


# --- Pair alibi ---

def get_players_by_pair_id(pair_id: str) -> list:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM players WHERE pair_id = ?", (pair_id,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def check_pair_alibi_on_elimination(eliminated_id: int) -> dict:
    """
    Check if the eliminated player has a pair partner who is still active.
    If so, mark the partner's alibi as lost and return info for notification.
    Returns dict with partner info or None.
    """
    eliminated = get_player_by_id(eliminated_id)
    if not eliminated or not eliminated.get("pair_id"):
        return None

    partners = get_players_by_pair_id(eliminated["pair_id"])
    for partner in partners:
        if partner["id"] != eliminated_id and partner["active"]:
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute("UPDATE players SET alibi_protected = FALSE WHERE id = ?", (partner["id"],))
            conn.commit()
            conn.close()
            return partner

    return None


def get_eliminated_this_round(game_id: int, round_num: int) -> list:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM players WHERE round_eliminated = ?",
        (round_num,)
    )
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def set_round_eliminated(player_id: int, round_num: int):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE players SET round_eliminated = ? WHERE id = ?", (round_num, player_id))
    conn.commit()
    conn.close()


def reactivate_player(player_id: int):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE players SET active = TRUE, round_eliminated = NULL WHERE id = ?", (player_id,))
    conn.commit()
    conn.close()


def set_group_chat_id(game_id: int, chat_id: int):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE games SET chat_id = ? WHERE id = ?", (chat_id, game_id))
    conn.commit()
    conn.close()


def set_player_gender(telegram_id: int, gender: str):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE players SET gender = ? WHERE telegram_id = ?", (gender, telegram_id))
    conn.commit()
    conn.close()


def get_players_by_gender(gender: str) -> list:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM players WHERE gender = ? AND active = TRUE AND role = ''", (gender,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_registered_players_count() -> int:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) as cnt FROM players WHERE active = TRUE")
    row = cursor.fetchone()
    conn.close()
    return row["cnt"] if row else 0


def get_unassigned_players_count() -> int:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) as cnt FROM players WHERE active = TRUE AND (role IS NULL OR role = '')")
    row = cursor.fetchone()
    conn.close()
    return row["cnt"] if row else 0


def init_game_stats(game_id: int):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT OR IGNORE INTO game_stats (game_id) VALUES (?)",
        (game_id,)
    )
    conn.commit()
    conn.close()


def set_first_qr_scanner(game_id: int, player_id: int):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE game_stats SET first_qr_scanner_id = ? WHERE game_id = ?",
        (player_id, game_id)
    )
    conn.commit()
    conn.close()


def increment_clues_found(game_id: int):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE game_stats SET clues_found_total = clues_found_total + 1 WHERE game_id = ?",
        (game_id,)
    )
    conn.commit()
    conn.close()


def set_most_clues_player(game_id: int, player_id: int):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE game_stats SET most_clues_player_id = ? WHERE game_id = ?",
        (player_id, game_id)
    )
    conn.commit()
    conn.close()


def get_game_stats(game_id: int):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM game_stats WHERE game_id = ?", (game_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def save_achievement(game_id: int, player_id: int, achievement: str):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO achievements (game_id, player_id, achievement) VALUES (?, ?, ?)",
        (game_id, player_id, achievement)
    )
    conn.commit()
    conn.close()


def get_player_achievements(game_id: int, player_id: int) -> list:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT achievement FROM achievements WHERE game_id = ? AND player_id = ?",
        (game_id, player_id)
    )
    rows = cursor.fetchall()
    conn.close()
    return [r["achievement"] for r in rows]


def reset_for_new_game():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE games SET is_active = FALSE, phase = 'finished'")
    cursor.execute("DELETE FROM votes")
    cursor.execute("DELETE FROM penalty_votes")
    cursor.execute("DELETE FROM consent_votes")
    cursor.execute("DELETE FROM votes_history")
    cursor.execute("DELETE FROM game_stats")
    cursor.execute("DELETE FROM achievements")
    cursor.execute("UPDATE players SET active = TRUE, role = '', role_description = '', "
                    "initial_clue = '', personal_goal = '', clues_found = '[]', alibi_protected = TRUE, "
                    "pair_id = NULL, round_eliminated = NULL")
    cursor.execute("UPDATE clues SET found = FALSE")
    conn.commit()
    conn.close()
