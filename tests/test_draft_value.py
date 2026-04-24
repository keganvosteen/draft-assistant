"""Tests for draft_value.py — Monte Carlo draft-aware scoring."""
import unittest

from draft_assistant.draft_value import (
    _snake_pick_numbers,
    _draft_slot,
    _bench_multiplier,
    draft_window,
    roster_value,
    draft_aware_values,
)
from draft_assistant.models import DraftState, LeagueConfig, Player


def _make_player(name, pos, projections=None, bye=None, adp=None):
    return Player(
        id=f"{name}|{pos}", name=name, position=pos,
        projections=projections or {}, bye_week=bye, adp=adp,
    )


SCORING = {"pass_yd": 0.04, "pass_td": 4, "rush_yd": 0.1, "rush_td": 6,
           "rec": 0.5, "rec_yd": 0.1, "rec_td": 6, "fumbles": -2}
ROSTER = {"QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 1, "K": 0, "DST": 0, "BN": 5}


def _config(teams=10, draft=None):
    return LeagueConfig(
        teams=teams, roster=ROSTER, scoring=SCORING, provider={},
        draft=draft or {"slot": 1, "monte_carlo_sims": 0},
    )


class TestSnakePickNumbers(unittest.TestCase):
    def test_slot_1_ten_teams(self):
        picks = _snake_pick_numbers(10, 1, rounds=3)
        self.assertEqual(picks, [1, 20, 21])

    def test_slot_5_ten_teams(self):
        picks = _snake_pick_numbers(10, 5, rounds=3)
        # R1 pick 5, R2 pick 6 (from end: 10-5+1=6), R3 pick 5
        self.assertEqual(picks, [5, 16, 25])

    def test_slot_10_ten_teams(self):
        picks = _snake_pick_numbers(10, 10, rounds=3)
        self.assertEqual(picks, [10, 11, 30])


class TestDraftWindow(unittest.TestCase):
    def test_empty_state_uses_config_slot(self):
        cfg = _config(teams=10, draft={"slot": 5})
        window = draft_window(cfg, None)
        self.assertEqual(window.draft_slot, 5)
        self.assertEqual(window.current_pick, 1)
        self.assertEqual(window.next_my_pick, 5)

    def test_mid_draft_computes_next_pick(self):
        cfg = _config(teams=10, draft={"slot": 3})
        state = DraftState(my_team_name="Me", league_teams=[f"T{i}" for i in range(10)])
        # First 4 picks happened, pick 5 is next
        state.picks = ["a", "b", "c", "d"]
        window = draft_window(cfg, state)
        self.assertEqual(window.current_pick, 5)


class TestBenchMultiplier(unittest.TestCase):
    def test_rb_wr_higher_than_qb(self):
        rb = _make_player("R", "RB")
        qb = _make_player("Q", "QB")
        self.assertGreater(_bench_multiplier(rb), _bench_multiplier(qb))

    def test_k_dst_zero(self):
        self.assertEqual(_bench_multiplier(_make_player("K", "K")), 0.0)
        self.assertEqual(_bench_multiplier(_make_player("D", "DST")), 0.0)


class TestRosterValue(unittest.TestCase):
    def test_fills_starter_slots(self):
        qb = _make_player("QB1", "QB")
        rb1 = _make_player("RB1", "RB")
        rb2 = _make_player("RB2", "RB")
        pts_map = {qb.key(): 350, rb1.key(): 300, rb2.key(): 250}
        result = roster_value([qb, rb1, rb2], pts_map, {"QB": 1, "RB": 2, "FLEX": 0, "BN": 0})
        self.assertIn(qb, result.starters)
        self.assertIn(rb1, result.starters)
        self.assertIn(rb2, result.starters)


class TestDraftAwareValues(unittest.TestCase):
    def test_returns_ranked_list(self):
        players = [
            _make_player("QB1", "QB", {"pass_yd": 4500, "pass_td": 35}),
            _make_player("RB1", "RB", {"rush_yd": 1200, "rush_td": 10, "rec": 50, "rec_yd": 400}),
            _make_player("RB2", "RB", {"rush_yd": 900, "rush_td": 6}),
            _make_player("WR1", "WR", {"rec": 100, "rec_yd": 1400, "rec_td": 10}),
        ]
        cfg = _config(draft={"slot": 1, "monte_carlo_sims": 0})
        values = draft_aware_values(cfg, players, {}, None, top_n=5)
        self.assertGreater(len(values), 0)
        for v in values:
            self.assertIsInstance(v.player, Player)


if __name__ == "__main__":
    unittest.main()
