"""Tests for fuzzy string matching."""
import unittest

from draft_assistant.fuzzy import _levenshtein, fuzzy_match, best_match


class TestLevenshtein(unittest.TestCase):
    def test_identical(self):
        self.assertEqual(_levenshtein("hello", "hello"), 0)

    def test_single_edit(self):
        self.assertEqual(_levenshtein("cat", "bat"), 1)

    def test_insertion(self):
        self.assertEqual(_levenshtein("cat", "cats"), 1)

    def test_deletion(self):
        self.assertEqual(_levenshtein("cats", "cat"), 1)

    def test_empty(self):
        self.assertEqual(_levenshtein("", "abc"), 3)
        self.assertEqual(_levenshtein("abc", ""), 3)


class TestFuzzyMatch(unittest.TestCase):
    def test_exact_match(self):
        results = fuzzy_match("McCaffrey", ["McCaffrey", "Allen", "Lamb"])
        self.assertEqual(results[0][0], "McCaffrey")
        self.assertEqual(results[0][1], 0)

    def test_typo_match(self):
        results = fuzzy_match("Mcafrey", ["McCaffrey", "Allen", "Lamb"], max_distance=3)
        self.assertTrue(any(name == "McCaffrey" for name, _ in results))

    def test_no_match_beyond_distance(self):
        results = fuzzy_match("zzzzzzz", ["McCaffrey", "Allen"], max_distance=3)
        self.assertEqual(len(results), 0)

    def test_case_insensitive(self):
        results = fuzzy_match("mccaffrey", ["McCaffrey"])
        self.assertEqual(len(results), 1)


class TestBestMatch(unittest.TestCase):
    def test_returns_closest(self):
        # "Alen" is distance 1 from "Allen"
        result = best_match("Alen", ["Allen", "Lamb"], max_distance=2)
        self.assertIsNotNone(result)
        self.assertEqual(result, "Allen")

    def test_returns_none_when_no_match(self):
        result = best_match("xxxxxxxxx", ["Allen", "Lamb"], max_distance=2)
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
