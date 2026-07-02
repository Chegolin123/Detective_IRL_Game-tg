"""Data integrity tests — validates ROLES, CLUES, FINALS_META consistency."""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from data import ROLES, CLUES, FINALS_META, FINALS
from game_logic import select_final


class TestRolesIntegrity:
    def test_all_roles_have_required_fields(self):
        for r in ROLES:
            assert "name" in r
            assert "role" in r
            assert "alibi" in r
            assert "type" in r
            assert "clue" in r

    def test_unique_role_names(self):
        names = [r["name"] for r in ROLES]
        assert len(names) == len(set(names))

    def test_role_types_are_valid(self):
        for r in ROLES:
            assert r["type"] in ("парное", "одиночное")

    def test_alibi_is_non_empty(self):
        for r in ROLES:
            assert len(r["alibi"]) > 5

    def test_clue_is_non_empty(self):
        for r in ROLES:
            assert len(r["clue"]) > 5

    def test_exactly_15_roles(self):
        assert len(ROLES) == 15

    def test_paired_roles_have_partner(self):
        pair_type = chr(1087) + chr(1072) + chr(1088) + chr(1085) + chr(1086) + chr(1077)  # парное
        solo_type = chr(1086) + chr(1076) + chr(1080) + chr(1085) + chr(1086) + chr(1095) + chr(1085) + chr(1086) + chr(1077)  # одиночное
        arkadiy = chr(1040) + chr(1088) + chr(1082) + chr(1072) + chr(1076) + chr(1080) + chr(1081)  # Аркадий

        valid_types = {pair_type, solo_type}
        for r in ROLES:
            assert r["type"] in valid_types

        def name_in_alibi(name, alibi):
            if name in alibi:
                return True
            # Handle Russian inflected cases: last character changes (Анна → Анной)
            if len(name) >= 3 and name[:-1] in alibi:
                return True
            if len(name) >= 4 and name[:4] in alibi:
                return True
            if len(name) >= 3 and name[:3] in alibi:
                return True
            return False

        matched_pairs = set()
        for r in ROLES:
            if r["type"] != pair_type:
                continue
            alibi = r["alibi"]
            found = False
            for other in ROLES:
                if other["name"] != r["name"] and name_in_alibi(other["name"], alibi):
                    matched_pairs.add(tuple(sorted([r["name"], other["name"]])))
                    found = True
                    break
            if not found:
                assert r["name"] == arkadiy, f"{r['name']} (pair) has no alibi partner"

        num_paired = sum(1 for r in ROLES if r["type"] == pair_type and r["name"] != arkadiy)
        assert len(matched_pairs) == num_paired // 2

    def test_role_names_no_empty(self):
        for r in ROLES:
            assert r["name"].strip()


class TestCluesIntegrity:
    def test_all_clues_have_required_fields(self):
        for cid, c in CLUES.items():
            assert "text" in c
            assert "target" in c
            assert len(c["text"]) > 10

    def test_exactly_15_clues(self):
        assert len(CLUES) == 15

    def test_all_clue_ids_sequential(self):
        expected = {f"clue{i}" for i in range(1, 16)}
        assert set(CLUES.keys()) == expected

    def test_all_clue_targets_are_valid_roles(self):
        role_names = {r["name"] for r in ROLES}
        for cid, c in CLUES.items():
            targets = c["target"] if isinstance(c["target"], list) else [c["target"]]
            for t in targets:
                assert t in role_names, f"{cid} target '{t}' not in ROLES"

    def test_some_clues_for_each_finale_candidate(self):
        candidate_roles = {m["killer_role"] for m in FINALS_META.values()}
        clue_targets = set()
        for c in CLUES.values():
            t = c["target"]
            clue_targets.update(t if isinstance(t, list) else [t])
        for role in candidate_roles:
            assert role in clue_targets, f"Killer '{role}' has no clue targeting them"

    def test_unique_clue_texts(self):
        texts = [c["text"] for c in CLUES.values()]
        assert len(texts) == len(set(texts))


class TestFinalsMetaIntegrity:
    def test_all_meta_keys_have_corresponding_final(self):
        for key in FINALS_META:
            assert key in FINALS, f"{key} in FINALS_META but not in FINALS"

    def test_meta_killer_roles_are_valid(self):
        role_names = {r["name"] for r in ROLES}
        for key, meta in FINALS_META.items():
            assert meta["killer_role"] in role_names, f"{key}: killer '{meta['killer_role']}' not in ROLES"

    def test_meta_required_clues_exist(self):
        for key, meta in FINALS_META.items():
            assert meta["required_clue"] in CLUES, f"{key}: clue '{meta['required_clue']}' not in CLUES"

    def test_all_finals_have_text(self):
        for key in ("victor", "roman", "maxim", "arkadiy", "default"):
            assert key in FINALS
            assert len(FINALS[key]) > 50

    def test_no_extra_finals_keys(self):
        valid = {"victor", "roman", "maxim", "arkadiy", "default"}
        for key in FINALS:
            assert key in valid, f"Unexpected key '{key}' in FINALS"
        for key in FINALS_META:
            assert key in valid, f"Unexpected key '{key}' in FINALS_META"

    def test_priority_order_matches_finals_meta(self):
        keys_in_order = list(FINALS_META.keys())
        expected = ["victor", "roman", "maxim", "arkadiy"]
        assert keys_in_order == expected, f"Priority order changed: {keys_in_order}"


class TestCrossReference:
    def test_initial_clues_reference_existing_roles(self):
        """Each role's initial clue should mention an existing role or be about the role itself."""
        role_names = {r["name"] for r in ROLES}
        for r in ROLES:
            clue = r["clue"]
            # Every clue must contain at least one role name (the target or other)
            mentioned = [name for name in role_names if name in clue]
            assert mentioned, f"Role '{r['name']}' initial clue mentions no roles: '{clue}'"

    def test_paired_roles_clues_are_unique(self):
        """Paired roles should have different initial clues."""
        clues = [r["clue"] for r in ROLES]
        assert len(clues) == len(set(clues)), "Duplicate initial clues found"
