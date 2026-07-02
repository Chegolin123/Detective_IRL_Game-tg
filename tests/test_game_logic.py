"""Tests for game_logic.py — pure functions, no Telegram dependencies."""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from game_logic import (
    select_final,
    get_final_text,
    determine_winners,
    calculate_results,
    is_majority_reached,
)


class TestSelectFinal:
    def test_victor_wins(self):
        key, killer = select_final(["Виктор", "Анна"], ["clue4", "clue1"])
        assert key == "victor"
        assert killer == "Виктор"

    def test_roman_wins(self):
        key, killer = select_final(["Роман", "Анна"], ["clue3"])
        assert key == "roman"
        assert killer == "Роман"

    def test_maxim_wins(self):
        key, killer = select_final(["Максим", "Анна"], ["clue1"])
        assert key == "maxim"
        assert killer == "Максим"

    def test_arkadiy_wins(self):
        key, killer = select_final(["Аркадий", "Анна"], ["clue7", "clue9"])
        assert key == "arkadiy"
        assert killer == "Аркадий"

    def test_priority_order(self):
        # Both Victor and Roman qualify — Victor wins (higher priority)
        key, killer = select_final(["Виктор", "Роман"], ["clue4", "clue3"])
        assert key == "victor"
        assert killer == "Виктор"

    def test_default_when_no_match(self):
        key, killer = select_final(["Анна", "Валентина"], ["clue11"])
        assert key == "default"
        assert killer is None

    def test_default_when_killer_missing(self):
        # Victor not in remaining even though clue4 found
        key, killer = select_final(["Анна"], ["clue4"])
        assert key == "default"
        assert killer is None

    def test_default_when_clue_missing(self):
        # Victor in remaining but no clue4
        key, killer = select_final(["Виктор", "Анна"], ["clue1"])
        assert key == "default"
        assert killer is None

    def test_empty_remaining(self):
        key, killer = select_final([], [])
        assert key == "default"

    def test_all_finals_have_text(self):
        for key in ["victor", "roman", "maxim", "arkadiy", "default"]:
            text = get_final_text(key)
            assert text
            assert "Спасибо за игру" in text or len(text) > 50


class TestDetermineWinners:
    def test_single_winner(self):
        history = [
            {"voter_id": 1, "target_id": 5, "round": 1},
            {"voter_id": 2, "target_id": 3, "round": 1},
        ]
        winners = determine_winners(history, 5)
        assert winners == [1]

    def test_multiple_winners(self):
        history = [
            {"voter_id": 1, "target_id": 5, "round": 1},
            {"voter_id": 2, "target_id": 5, "round": 1},
            {"voter_id": 3, "target_id": 5, "round": 2},
        ]
        winners = determine_winners(history, 5)
        assert sorted(winners) == [1, 2, 3]

    def test_no_winners(self):
        history = [
            {"voter_id": 1, "target_id": 3, "round": 1},
            {"voter_id": 2, "target_id": 4, "round": 1},
        ]
        winners = determine_winners(history, 5)
        assert winners == []

    def test_deduplicate_voter(self):
        history = [
            {"voter_id": 1, "target_id": 5, "round": 1},
            {"voter_id": 1, "target_id": 5, "round": 2},  # same voter, same target
        ]
        winners = determine_winners(history, 5)
        assert winners == [1]

    def test_empty_history(self):
        winners = determine_winners([], 5)
        assert winners == []


class TestCalculateResults:
    def test_basic_count(self):
        votes = [
            {"target_id": 1},
            {"target_id": 1},
            {"target_id": 2},
        ]
        result = calculate_results(votes, {}, 5)
        assert result["counter"] == {1: 2, 2: 1}
        assert result["total_votes"] == 3
        assert result["max_votes"] == 2
        assert result["candidates"] == [1]
        assert not result["unanimous"]
        assert result["turnout_ok"]  # 3 > 2.5
        assert result["has_votes"]

    def test_turnout_check(self):
        # 3 out of 5 voted -> 3 > 2.5 = True
        votes = [{"target_id": 1}, {"target_id": 2}, {"target_id": 3}]
        result = calculate_results(votes, {}, 5)
        assert result["turnout_ok"]

    def test_turnout_below_50(self):
        # 2 out of 5 voted -> 2 > 2.5 = False
        votes = [{"target_id": 1}, {"target_id": 2}]
        result = calculate_results(votes, {}, 5)
        assert not result["turnout_ok"]

    def test_turnout_exact_50(self):
        # 3 out of 6 voted -> 3 > 3.0 = False (must be >, not >=)
        votes = [{"target_id": 1}, {"target_id": 2}, {"target_id": 3}]
        result = calculate_results(votes, {}, 6)
        assert not result["turnout_ok"]

    def test_unanimous(self):
        votes = [{"target_id": 1}, {"target_id": 1}, {"target_id": 1}]
        result = calculate_results(votes, {}, 5)
        assert result["unanimous"]
        assert result["candidates"] == [1]

    def test_tie(self):
        votes = [{"target_id": 1}, {"target_id": 2}]
        result = calculate_results(votes, {}, 5)
        assert len(result["candidates"]) == 2
        assert result["max_votes"] == 1

    def test_tie_three_way(self):
        votes = [{"target_id": 1}, {"target_id": 2}, {"target_id": 3}]
        result = calculate_results(votes, {}, 5)
        assert len(result["candidates"]) == 3
        assert result["max_votes"] == 1

    def test_penalty_votes_included(self):
        votes = [{"target_id": 1}, {"target_id": 2}]
        penalties = {1: 2}
        result = calculate_results(votes, penalties, 5)
        assert result["counter"][1] == 3  # 1 vote + 2 penalty
        assert result["counter"][2] == 1
        assert result["candidates"] == [1]

    def test_penalty_votes_break_tie(self):
        votes = [{"target_id": 1}, {"target_id": 2}]
        penalties = {1: 2}
        result = calculate_results(votes, penalties, 5)
        assert result["candidates"] == [1]
        assert result["max_votes"] == 3

    def test_no_votes(self):
        result = calculate_results([], {}, 5)
        assert not result["has_votes"]
        assert result["candidates"] == []

    def test_all_vote_for_same_turnout_ignored(self):
        # 2 out of 10 voted, but both voted for 1 -> unanimous
        votes = [{"target_id": 1}, {"target_id": 1}]
        result = calculate_results(votes, {}, 10)
        assert result["unanimous"]
        assert not result["turnout_ok"]


class TestIsMajorityReached:
    def test_majority_yes(self):
        assert is_majority_reached(6, 10)  # 6 > 5

    def test_majority_no(self):
        assert not is_majority_reached(5, 10)  # 5 is not > 5

    def test_majority_exact_half(self):
        assert not is_majority_reached(5, 10)

    def test_one_above_half(self):
        assert is_majority_reached(6, 10)

    def test_small_numbers(self):
        assert is_majority_reached(2, 3)  # 2 > 1.5
        assert not is_majority_reached(1, 3)  # 1 is not > 1.5
