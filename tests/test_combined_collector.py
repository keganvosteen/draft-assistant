"""Tests for the combined collector and FFC ADP module."""
import unittest

from draft_assistant.collectors.combined import (
    _match_key,
    _normalize_name,
    _pair_fuzzy_keys,
)


class TestNormalizeName(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(_normalize_name("Josh Allen"), "josh allen")

    def test_strips_suffix(self):
        self.assertEqual(_normalize_name("Patrick Mahomes II"), "patrick mahomes")
        self.assertEqual(_normalize_name("Marvin Harrison Jr."), "marvin harrison")
        self.assertEqual(_normalize_name("Odell Beckham Jr"), "odell beckham")

    def test_collapses_whitespace(self):
        self.assertEqual(_normalize_name("  De'Von   Achane  "), "de'von achane")


class TestMatchKey(unittest.TestCase):
    def test_creates_key(self):
        self.assertEqual(_match_key("Josh Allen", "QB"), "josh allen|QB")

    def test_suffix_removed(self):
        self.assertEqual(_match_key("Marvin Harrison Jr.", "WR"), "marvin harrison|WR")


class TestPairFuzzyKeys(unittest.TestCase):
    def test_pairs_small_typos_same_position(self):
        pairs = _pair_fuzzy_keys(
            {"deandre swift|RB"},
            {"d'andre swift|RB"},
        )
        self.assertEqual(pairs, {"deandre swift|RB": "d'andre swift|RB"})

    def test_does_not_pair_across_positions(self):
        pairs = _pair_fuzzy_keys(
            {"josh allen|QB"},
            {"josh allen|WR"},  # different player, different position
        )
        self.assertEqual(pairs, {})

    def test_exact_matches_excluded(self):
        pairs = _pair_fuzzy_keys(
            {"josh allen|QB", "joshh allen|QB"},
            {"josh allen|QB"},
        )
        # "josh allen|QB" matches exactly, so only the typo key may pair —
        # but its candidate is exact-matched and therefore unavailable.
        self.assertEqual(pairs, {})

    def test_each_sleeper_key_claimed_once(self):
        pairs = _pair_fuzzy_keys(
            {"jon smith|WR", "john smith|WR"},
            {"jhon smith|WR"},
        )
        self.assertEqual(len(pairs), 1)

    def test_distant_names_not_paired(self):
        pairs = _pair_fuzzy_keys(
            {"keenan allen|WR"},
            {"davante adams|WR"},
        )
        self.assertEqual(pairs, {})


if __name__ == "__main__":
    unittest.main()
