"""Tests for the suggestion engine including FLEX needs and gradient logic."""
import unittest

from draft_assistant.models import LeagueConfig, Player
from draft_assistant.suggest import needs_by_position, suggest_players


def _make_player(name, pos, pts_dict, bye=None):
    return Player(id=f"{name}|{pos}", name=name, position=pos, projections=pts_dict, bye_week=bye)


SCORING = {"rush_yd": 0.1, "rush_td": 6, "rec": 0.5, "rec_yd": 0.1, "rec_td": 6, "pass_yd": 0.04, "pass_td": 4}
ROSTER = {"QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 1, "K": 0, "DST": 0, "BN": 5}


def _config():
    return LeagueConfig(teams=10, roster=ROSTER, scoring=SCORING, provider={})


class TestNeedsByPosition(unittest.TestCase):
    def test_empty_roster_needs_all(self):
        needs = needs_by_position(_config(), {})
        self.assertEqual(needs["QB"], 1)
        self.assertEqual(needs["RB"], 2)
        self.assertEqual(needs["WR"], 2)
        self.assertEqual(needs["TE"], 1)
        self.assertEqual(needs["FLEX"], 1)

    def test_flex_filled_by_overflow(self):
        # If I have 3 RBs and only need 2 starters, the extra fills 1 FLEX
        roster = {"RB": [_make_player(f"RB{i}", "RB", {}) for i in range(3)]}
        needs = needs_by_position(_config(), roster)
        self.assertEqual(needs["RB"], 0)
        self.assertEqual(needs["FLEX"], 0)  # 1 FLEX slot filled by 3rd RB

    def test_flex_partially_filled(self):
        # 2 RBs fill the starter slots, FLEX still open
        roster = {"RB": [_make_player(f"RB{i}", "RB", {}) for i in range(2)]}
        needs = needs_by_position(_config(), roster)
        self.assertEqual(needs["RB"], 0)
        self.assertEqual(needs["FLEX"], 1)  # no overflow to fill FLEX

    def test_wrte_flex_ignores_rb_overflow(self):
        cfg = LeagueConfig(
            teams=10,
            roster={"RB": 0, "WR": 1, "TE": 0, "WRTE": 1, "BN": 0},
            scoring=SCORING,
            provider={},
        )
        roster = {"RB": [_make_player("RB1", "RB", {})]}
        needs = needs_by_position(cfg, roster)
        self.assertEqual(needs["WRTE"], 1)

    def test_wrte_flex_filled_by_wr_overflow(self):
        cfg = LeagueConfig(
            teams=10,
            roster={"WR": 1, "TE": 0, "WRTE": 1, "BN": 0},
            scoring=SCORING,
            provider={},
        )
        roster = {"WR": [_make_player("WR1", "WR", {}), _make_player("WR2", "WR", {})]}
        needs = needs_by_position(cfg, roster)
        self.assertEqual(needs["WRTE"], 0)

    def test_superflex_filled_by_qb_overflow(self):
        cfg = LeagueConfig(
            teams=10,
            roster={"QB": 1, "SUPERFLEX": 1, "BN": 0},
            scoring=SCORING,
            provider={},
        )
        roster = {"QB": [_make_player("QB1", "QB", {}), _make_player("QB2", "QB", {})]}
        needs = needs_by_position(cfg, roster)
        self.assertEqual(needs["SUPERFLEX"], 0)


class TestSuggestPlayers(unittest.TestCase):
    def test_returns_ranked_list(self):
        players = [
            _make_player("QB1", "QB", {"pass_yd": 4000, "pass_td": 30}),
            _make_player("RB1", "RB", {"rush_yd": 1200, "rush_td": 10, "rec": 50, "rec_yd": 400}),
            _make_player("RB2", "RB", {"rush_yd": 900, "rush_td": 7, "rec": 30, "rec_yd": 250}),
        ]
        ranked = suggest_players(_config(), players, {}, top_n=10)
        self.assertGreater(len(ranked), 0)
        # Each entry is (player, pts, vor, score)
        for p, pts, vor, score in ranked:
            self.assertIsInstance(p, Player)

    def test_flex_eligible_still_ranked_when_only_flex_is_open(self):
        # RB starter slots are full but the FLEX is open, so another RB is still
        # a legitimate pick and must come back ranked rather than be excluded.
        players = [
            _make_player("RB3", "RB", {"rush_yd": 800, "rush_td": 6, "rec": 25, "rec_yd": 200}),
            _make_player("RB4", "RB", {"rush_yd": 400, "rush_td": 2, "rec": 10, "rec_yd": 80}),
            _make_player("RB5", "RB", {"rush_yd": 300, "rush_td": 1, "rec": 5, "rec_yd": 40}),
        ]
        roster = {"RB": [_make_player(f"RB{i}", "RB", {}) for i in range(2)]}
        needs = needs_by_position(_config(), roster)
        self.assertEqual(needs["RB"], 0)
        self.assertEqual(needs["FLEX"], 1)

        ranked = suggest_players(_config(), players, roster, top_n=5)
        self.assertEqual([p.name for p, _, _, _ in ranked][0], "RB3")


if __name__ == "__main__":
    unittest.main()
