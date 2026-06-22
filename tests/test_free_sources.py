"""Tests for the no-dependency free data collector's field mapping and merge."""
import unittest

from draft_assistant.models import Player
from draft_assistant.importers.free_sources import (
    _fill_missing_byes,
    _merge_player,
    _players_from_nflverse_stats,
    _players_from_sleeper_projection_rows,
)


class TestSleeperProjectionPlayers(unittest.TestCase):
    def test_age_and_experience_land_on_player_fields(self):
        rows = {"123": {"pts_ppr": 250.0, "rec": 80, "rec_yd": 1000, "adp_half_ppr": 12.0}}
        meta = {"123": {"position": "WR", "full_name": "Test Receiver",
                        "team": "KC", "age": 27, "years_exp": 5, "bye_week": 6}}
        players = _players_from_sleeper_projection_rows(rows, meta, "half-ppr")
        self.assertEqual(len(players), 1)
        p = players[0]
        self.assertEqual(p.age, 27)
        self.assertEqual(p.experience, 5)


class TestNflverseStatsPlayers(unittest.TestCase):
    def test_actuals_become_historical_stats_not_projections(self):
        rows = [{
            "player_id": "00-001", "position": "RB",
            "player_display_name": "Test Back", "recent_team": "DET",
            "rushing_yards": "1200", "rushing_tds": "10", "receptions": "40",
        }]
        meta = {"00-001": {"birth_date": "1999-05-01", "years_of_experience": "4"}}
        players = _players_from_nflverse_stats(rows, meta, 2025)
        self.assertEqual(len(players), 1)
        p = players[0]
        self.assertEqual(p.projections, {})
        self.assertIn(2025, p.historical_stats)
        self.assertEqual(p.historical_stats[2025]["rush_yd"], 1200.0)
        self.assertIsNotNone(p.age)
        self.assertEqual(p.experience, 4)


class TestFillMissingByes(unittest.TestCase):
    def test_teammates_inherit_known_bye(self):
        a = Player(id="a", name="A", position="WR", team="KC", bye_week=6)
        b = Player(id="b", name="B", position="RB", team="KC")
        c = Player(id="c", name="C", position="QB", team="DET")  # no source bye
        _fill_missing_byes([a, b, c])
        self.assertEqual(b.bye_week, 6)
        self.assertIsNone(c.bye_week)

    def test_existing_byes_not_overwritten(self):
        a = Player(id="a", name="A", position="WR", team="KC", bye_week=6)
        b = Player(id="b", name="B", position="RB", team="KC", bye_week=7)
        _fill_missing_byes([a, b])
        self.assertEqual(b.bye_week, 7)


class TestMergePlayer(unittest.TestCase):
    def test_merge_carries_age_experience_and_history(self):
        base = Player(id="a", name="Test Back", position="RB", team="DET",
                      projections={"rush_yd": 1100.0})
        incoming = Player(id="b", name="Test Back", position="RB",
                          age=26, experience=4,
                          historical_stats={2025: {"rush_yd": 1200.0}})
        _merge_player(base, incoming, "nflverse_stats_2025")
        self.assertEqual(base.age, 26)
        self.assertEqual(base.experience, 4)
        self.assertEqual(base.historical_stats[2025]["rush_yd"], 1200.0)
        # Actuals must not leak into the projection
        self.assertEqual(base.projections, {"rush_yd": 1100.0})

    def test_merge_does_not_overwrite_existing_fields(self):
        base = Player(id="a", name="Test Back", position="RB", age=25,
                      historical_stats={2025: {"rush_yd": 1000.0}})
        incoming = Player(id="b", name="Test Back", position="RB", age=30,
                          historical_stats={2025: {"rush_yd": 999.0},
                                            2024: {"rush_yd": 900.0}})
        _merge_player(base, incoming, "other")
        self.assertEqual(base.age, 25)
        self.assertEqual(base.historical_stats[2025]["rush_yd"], 1000.0)
        self.assertEqual(base.historical_stats[2024]["rush_yd"], 900.0)


if __name__ == "__main__":
    unittest.main()
