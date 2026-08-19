"""Tests for the combined collector and FFC ADP module."""
import unittest
from unittest import mock

from draft_assistant.collectors import combined
from draft_assistant.collectors.combined import (
    _align_names,
    _match_key,
    _normalize_name,
    _pair_fuzzy_keys,
    collect_all_result,
)
from draft_assistant.importers.free_sources import (
    FreeDataResult,
    SourceReport,
    _merge_key,
)
from draft_assistant.models import Player


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


def _player(name, pos, **kw):
    return Player(id=f"{name}-{pos}", name=name, position=pos, **kw)


class TestAlignNames(unittest.TestCase):
    def test_renames_near_miss_onto_pool_spelling(self):
        pool = {_merge_key(p): p for p in [_player("D'Andre Swift", "RB")]}
        aligned = _align_names(pool, [_player("Deandre Swift", "RB", age=26)])
        self.assertEqual(aligned[0].name, "D'Andre Swift")

    def test_leaves_exact_and_unrelated_names_alone(self):
        pool = {_merge_key(p): p for p in [_player("Josh Allen", "QB")]}
        aligned = _align_names(pool, [
            _player("Josh Allen", "QB"),
            _player("Davante Adams", "WR"),
        ])
        self.assertEqual([p.name for p in aligned], ["Josh Allen", "Davante Adams"])


class TestCollectAllIsSupersetOfFree(unittest.TestCase):
    """Full Collect must never return fewer players than the free pull.

    It used to run a narrower nflverse-roster-plus-Sleeper pipeline instead of
    the free sources, so "Full" came back several hundred players short of
    "Free" on the very same board.
    """

    FREE = [
        _player("Josh Allen", "QB"),
        _player("D'Andre Swift", "RB"),
        _player("Ja'Marr Chase", "WR"),
    ]

    def _run(self, nflverse=(), sleeper=()):
        free_result = FreeDataResult(
            players=list(self.FREE),
            reports=[SourceReport("Fantasy Football Calculator ADP", 3)],
            consensus_players=2,
            warnings=[],
        )
        with mock.patch.object(combined, "pull_free_data", return_value=free_result),              mock.patch.object(combined, "_collect_nflverse", return_value=list(nflverse)),              mock.patch.object(combined, "_collect_sleeper_history", return_value=list(sleeper)):
            return collect_all_result(current_season=2026, history_seasons=1)

    def test_keeps_every_free_player_when_enrichment_is_empty(self):
        result = self._run()
        self.assertEqual({p.name for p in result.players},
                         {p.name for p in self.FREE})

    def test_enrichment_adds_players_rather_than_replacing_the_pool(self):
        result = self._run(nflverse=[_player("Bijan Robinson", "RB")])
        self.assertEqual(len(result.players), len(self.FREE) + 1)
        self.assertIn("Bijan Robinson", {p.name for p in result.players})

    def test_enrichment_merges_metadata_onto_a_near_miss_name(self):
        result = self._run(nflverse=[_player(
            "Deandre Swift", "RB", age=26, draft_capital="2nd-round",
            injury_history=["hamstring"], historical_stats={2025: {"rush_yd": 900.0}},
        )])
        self.assertEqual(len(result.players), len(self.FREE))
        swift = next(p for p in result.players if p.name == "D'Andre Swift")
        self.assertEqual(swift.age, 26)
        self.assertEqual(swift.draft_capital, "2nd-round")
        self.assertEqual(swift.injury_history, ["hamstring"])
        self.assertEqual(swift.historical_stats[2025], {"rush_yd": 900.0})

    def test_carries_the_free_pull_reports_and_warnings(self):
        result = self._run()
        self.assertEqual(result.consensus_players, 2)
        self.assertIn("Fantasy Football Calculator ADP",
                      [r.source for r in result.reports])

    def test_survives_a_failed_free_pull(self):
        with mock.patch.object(combined, "pull_free_data", side_effect=OSError("offline")),              mock.patch.object(combined, "_collect_nflverse",
                               return_value=[_player("Bijan Robinson", "RB")]),              mock.patch.object(combined, "_collect_sleeper_history", return_value=[]),              mock.patch.object(combined, "_fill_adp_gaps"):
            result = collect_all_result(current_season=2026, history_seasons=1)
        self.assertEqual([p.name for p in result.players], ["Bijan Robinson"])
        self.assertIn("Free sources", [r.source for r in result.reports if not r.ok])


if __name__ == "__main__":
    unittest.main()
