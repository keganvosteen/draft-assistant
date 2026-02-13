"""Tests for the suggestion engine including FLEX needs and gradient logic."""
import unittest

from draft_assistant.models import LeagueConfig, Player
from draft_assistant.suggest import (
    needs_by_position,
    suggest_players,
    _position_need_multiplier,
    _bye_week_penalty,
    FILLED_BASE,
    NEED_CEILING,
)


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


class TestGradientNeedMultiplier(unittest.TestCase):
    def test_filled_position_gets_low_multiplier(self):
        needs = {"QB": 0, "RB": 0, "FLEX": 0}
        m = _position_need_multiplier("QB", needs, _config(), {}, 0, 15)
        self.assertAlmostEqual(m, FILLED_BASE)

    def test_needed_position_gets_boost(self):
        needs = {"QB": 1, "RB": 2, "FLEX": 1}
        m = _position_need_multiplier("QB", needs, _config(), {}, 0, 15)
        self.assertGreater(m, 1.0)

    def test_more_need_means_higher_multiplier(self):
        needs_low = {"RB": 1, "FLEX": 0}
        needs_high = {"RB": 2, "FLEX": 1}
        m_low = _position_need_multiplier("RB", needs_low, _config(), {}, 0, 15)
        m_high = _position_need_multiplier("RB", needs_high, _config(), {}, 0, 15)
        self.assertGreater(m_high, m_low)

    def test_urgency_rises_with_draft_progress(self):
        needs = {"QB": 1, "FLEX": 0}
        m_early = _position_need_multiplier("QB", needs, _config(), {}, 10, 15)
        m_late = _position_need_multiplier("QB", needs, _config(), {}, 140, 15)
        self.assertGreater(m_late, m_early)


class TestByeWeekPenalty(unittest.TestCase):
    def test_no_penalty_without_bye(self):
        p = _make_player("RB1", "RB", {}, bye=None)
        pen = _bye_week_penalty(p, {})
        self.assertEqual(pen, 0.0)

    def test_penalty_for_stacking(self):
        p = _make_player("RB1", "RB", {}, bye=7)
        roster = {"RB": [_make_player("RB2", "RB", {}, bye=7)]}
        pen = _bye_week_penalty(p, roster)
        self.assertGreater(pen, 0.0)

    def test_no_penalty_different_byes(self):
        p = _make_player("RB1", "RB", {}, bye=7)
        roster = {"RB": [_make_player("RB2", "RB", {}, bye=9)]}
        pen = _bye_week_penalty(p, roster)
        self.assertEqual(pen, 0.0)


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

    def test_flex_eligible_not_penalized_when_flex_open(self):
        # RB starters filled, but FLEX open — RBs should still get a boost
        # Need multiple RBs so the top one has positive VOR
        players = [
            _make_player("RB3", "RB", {"rush_yd": 800, "rush_td": 6, "rec": 25, "rec_yd": 200}),
            _make_player("RB4", "RB", {"rush_yd": 400, "rush_td": 2, "rec": 10, "rec_yd": 80}),
            _make_player("RB5", "RB", {"rush_yd": 300, "rush_td": 1, "rec": 5, "rec_yd": 40}),
        ]
        roster = {"RB": [_make_player(f"RB{i}", "RB", {}) for i in range(2)]}
        needs = needs_by_position(_config(), roster)
        # RB starters filled but FLEX still open
        self.assertEqual(needs["RB"], 0)
        self.assertEqual(needs["FLEX"], 1)
        # The need multiplier for RB should reflect the open FLEX slot
        m = _position_need_multiplier("RB", needs, _config(), roster, 0, 15)
        self.assertGreater(m, FILLED_BASE)  # should NOT be penalized


if __name__ == "__main__":
    unittest.main()
