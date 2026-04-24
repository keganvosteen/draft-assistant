"""Tests for the combined collector and FFC ADP module."""
import unittest

from draft_assistant.collectors.combined import _normalize_name, _match_key


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


if __name__ == "__main__":
    unittest.main()
