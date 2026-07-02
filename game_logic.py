from data import FINALS, FINALS_META


def select_final(remaining_roles: list, found_clue_ids: list) -> tuple:
    """
    Choose finale by priority.
    Returns (final_key: str, killer_role: str | None).
    """
    for key in ["victor", "roman", "maxim", "arkadiy"]:
        meta = FINALS_META[key]
        if meta["killer_role"] in remaining_roles and meta["required_clue"] in found_clue_ids:
            return key, meta["killer_role"]
    return "default", None


def get_final_text(final_key: str) -> str:
    return FINALS.get(final_key, FINALS["default"]).strip()


def determine_winners(votes_history: list, killer_player_id: int) -> list:
    """
    From votes_history determine who voted for the killer.
    votes_history: list of dicts with keys voter_id, target_id
    Returns list of unique voter names/IDs.
    """
    winner_ids = []
    seen = set()
    for record in votes_history:
        if record["target_id"] == killer_player_id and record["voter_id"] not in seen:
            winner_ids.append(record["voter_id"])
            seen.add(record["voter_id"])
    return winner_ids


def calculate_results(
    votes: list,
    penalties: dict,
    alive_count: int
) -> dict:
    """
    Calculate voting results.
    votes: list of dicts with target_id
    penalties: dict of {target_id: penalty_count}
    alive_count: number of active players

    Returns dict with keys:
        - counter: {player_id: total_votes}
        - total_votes: int
        - max_votes: int
        - candidates: list of player_ids with max votes
        - unanimous: bool
        - turnout_ok: bool
        - has_votes: bool
    """
    counter = {}
    for v in votes:
        tid = v["target_id"]
        counter[tid] = counter.get(tid, 0) + 1
    for tid, pcount in penalties.items():
        counter[tid] = counter.get(tid, 0) + pcount

    total_votes = sum(counter.values())
    has_votes = len(counter) > 0

    if not has_votes:
        return {
            "counter": counter,
            "total_votes": 0,
            "max_votes": 0,
            "candidates": [],
            "unanimous": False,
            "turnout_ok": False,
            "has_votes": False,
        }

    max_votes = max(counter.values())
    candidates = [pid for pid, cnt in counter.items() if cnt == max_votes]
    unanimous = len(candidates) == 1 and counter[candidates[0]] == total_votes
    turnout_ok = total_votes > alive_count * 0.5

    return {
        "counter": counter,
        "total_votes": total_votes,
        "max_votes": max_votes,
        "candidates": candidates,
        "unanimous": unanimous,
        "turnout_ok": turnout_ok,
        "has_votes": True,
    }


def is_majority_reached(consent_count: int, alive_count: int) -> bool:
    """Check if consent_count > alive_count / 2."""
    return consent_count > alive_count / 2
