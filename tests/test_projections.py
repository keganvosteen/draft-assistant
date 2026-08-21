"""Tests for VOR and replacement level calculation."""
import unittest

from draft_assistant.models import Player
from draft_assistant.projections import compute_points, replacement_levels


def _make_player(name, pos, pts_dict):
    return Player(id=f"{name}|{pos}", name=name, position=pos, projections=pts_dict)


SCORING = {"pass_yd": 0.04, "pass_td": 4, "rush_yd": 0.1, "rush_td": 6, "rec": 0.5, "rec_yd": 0.1, "rec_td": 6, "fumbles": -2}


class TestComputePoints(unittest.TestCase):
    def test_computes_for_all_players(self):
        players = [
            _make_player("QB1", "QB", {"pass_yd": 4000, "pass_td": 30}),
            _make_player("RB1", "RB", {"rush_yd": 1200, "rush_td": 10, "rec": 40, "rec_yd": 300}),
        ]
        pts = compute_points(players, SCORING, use_historical=False)
        self.assertEqual(len(pts), 2)
        self.assertGreater(pts["QB1|QB"], 0)
        self.assertGreater(pts["RB1|RB"], 0)


class TestReplacementLevels(unittest.TestCase):
    def test_basic_replacement(self):
        # 2-team league, 1 QB each = replacement is the 2nd-best QB
        players = [
            _make_player("QB1", "QB", {"pass_yd": 4500, "pass_td": 35}),
            _make_player("QB2", "QB", {"pass_yd": 4000, "pass_td": 28}),
            _make_player("QB3", "QB", {"pass_yd": 3500, "pass_td": 22}),
        ]
        roster = {"QB": 1, "RB": 0, "WR": 0, "TE": 0, "FLEX": 0, "K": 0, "DST": 0}
        repl = replacement_levels(players, SCORING, teams=2, roster=roster)
        # QB2 is the replacement level (2nd QB drafted out of 2 teams)
        pts = compute_points(players, SCORING, use_historical=False)
        self.assertAlmostEqual(repl["QB"], pts["QB2|QB"], places=1)

    def test_flex_allocation(self):
        players = [
            _make_player("RB1", "RB", {"rush_yd": 1500, "rush_td": 14, "rec": 50, "rec_yd": 400}),
            _make_player("RB2", "RB", {"rush_yd": 1200, "rush_td": 10, "rec": 40, "rec_yd": 300}),
            _make_player("WR1", "WR", {"rec": 100, "rec_yd": 1400, "rec_td": 10}),
            _make_player("TE1", "TE", {"rec": 80, "rec_yd": 900, "rec_td": 7}),
        ]
        roster = {"QB": 0, "RB": 1, "WR": 1, "TE": 1, "FLEX": 1, "K": 0, "DST": 0}
        # With 1 team, 1 FLEX: replacement should account for flex usage
        repl = replacement_levels(players, SCORING, teams=1, roster=roster)
        self.assertIn("RB", repl)
        self.assertIn("WR", repl)

    def test_flex_allocation_uses_players_after_mandatory_starters(self):
        scoring = {"rush_yd": 1.0, "rec_yd": 1.0}
        players = [
            _make_player("RB1", "RB", {"rush_yd": 100}),
            _make_player("RB2", "RB", {"rush_yd": 99}),
            _make_player("RB3", "RB", {"rush_yd": 10}),
            _make_player("WR1", "WR", {"rec_yd": 90}),
            _make_player("WR2", "WR", {"rec_yd": 89}),
            _make_player("WR3", "WR", {"rec_yd": 88}),
            _make_player("WR4", "WR", {"rec_yd": 87}),
        ]
        roster = {"RB": 1, "WR": 1, "FLEX": 1}

        repl = replacement_levels(
            players, scoring, teams=2, roster=roster, use_historical=False,
        )

        self.assertEqual(repl["RB"], 99.0)
        self.assertEqual(repl["WR"], 87.0)

    def test_live_replacement_counts_only_unfilled_starter_demand(self):
        scoring = {"rush_yd": 1.0}
        players = [
            _make_player(f"RB{i}", "RB", {"rush_yd": 110 - i * 10})
            for i in range(1, 9)
        ]
        drafted = players[:3]
        available = players[3:]

        repl = replacement_levels(
            available,
            scoring,
            teams=4,
            roster={"RB": 1},
            use_historical=False,
            occupied_players=drafted,
        )

        # Three teams already filled RB.  The only remaining league-wide RB
        # starter is RB4, so RB7 must not become the replacement baseline.
        self.assertEqual(repl["RB"], 70.0)

    def test_filled_position_uses_best_available_as_replacement(self):
        scoring = {"rush_yd": 1.0}
        drafted = [_make_player("RB1", "RB", {"rush_yd": 100})]
        available = [
            _make_player("RB2", "RB", {"rush_yd": 90}),
            _make_player("RB3", "RB", {"rush_yd": 80}),
        ]

        repl = replacement_levels(
            available,
            scoring,
            teams=1,
            roster={"RB": 1},
            use_historical=False,
            occupied_players=drafted,
        )

        self.assertEqual(repl["RB"], 90.0)


if __name__ == "__main__":
    unittest.main()
