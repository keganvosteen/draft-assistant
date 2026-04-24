"""Tests for auction draft dollar values."""
import unittest

from draft_assistant.models import LeagueConfig, Player
from draft_assistant.auction import compute_dollar_values, AuctionTracker


def _make_player(name, pos, pts_dict):
    return Player(id=f"{name}|{pos}", name=name, position=pos, projections=pts_dict)


SCORING = {"rush_yd": 0.1, "rush_td": 6, "rec": 0.5, "rec_yd": 0.1, "rec_td": 6, "pass_yd": 0.04, "pass_td": 4}
ROSTER = {"QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 1, "K": 0, "DST": 0, "BN": 3}


def _config():
    return LeagueConfig(teams=2, roster=ROSTER, scoring=SCORING, provider={})


class TestDollarValues(unittest.TestCase):
    def test_values_assigned(self):
        players = [
            _make_player("QB1", "QB", {"pass_yd": 4500, "pass_td": 35}),
            _make_player("QB2", "QB", {"pass_yd": 3500, "pass_td": 25}),
            _make_player("RB1", "RB", {"rush_yd": 1500, "rush_td": 14, "rec": 50, "rec_yd": 400}),
            _make_player("RB2", "RB", {"rush_yd": 1100, "rush_td": 9, "rec": 30, "rec_yd": 250}),
            _make_player("RB3", "RB", {"rush_yd": 800, "rush_td": 6, "rec": 20, "rec_yd": 180}),
            _make_player("WR1", "WR", {"rec": 110, "rec_yd": 1500, "rec_td": 12}),
            _make_player("WR2", "WR", {"rec": 90, "rec_yd": 1200, "rec_td": 8}),
            _make_player("TE1", "TE", {"rec": 80, "rec_yd": 900, "rec_td": 7}),
        ]
        values = compute_dollar_values(_config(), players, budget_per_team=200)
        self.assertGreater(len(values), 0)
        # Best player should have highest value
        max_key = max(values, key=values.get)
        self.assertGreater(values[max_key], 1.0)

    def test_only_positive_vor_gets_value(self):
        players = [
            _make_player("QB1", "QB", {"pass_yd": 4500, "pass_td": 35}),
            _make_player("QB2", "QB", {"pass_yd": 4400, "pass_td": 34}),
            _make_player("QB3", "QB", {"pass_yd": 100, "pass_td": 1}),  # well below replacement
        ]
        roster = {"QB": 1, "RB": 0, "WR": 0, "TE": 0, "FLEX": 0, "K": 0, "DST": 0, "BN": 0}
        config = LeagueConfig(teams=2, roster=roster, scoring=SCORING, provider={})
        values = compute_dollar_values(config, players, budget_per_team=200)
        # QB3 should have negative VOR and not appear (or have minimal value)
        self.assertNotIn("QB3|QB", values)


class TestAuctionTracker(unittest.TestCase):
    def test_budget_tracking(self):
        tracker = AuctionTracker(_config(), budget_per_team=200)
        self.assertEqual(tracker.remaining_budget("Team 1"), 200)
        tracker.record_win("Team 1", "QB1|QB", 50)
        self.assertEqual(tracker.remaining_budget("Team 1"), 150)

    def test_cannot_exceed_budget(self):
        tracker = AuctionTracker(_config(), budget_per_team=200)
        result = tracker.record_win("Team 1", "QB1|QB", 250)
        self.assertFalse(result)
        self.assertEqual(tracker.remaining_budget("Team 1"), 200)


if __name__ == "__main__":
    unittest.main()
