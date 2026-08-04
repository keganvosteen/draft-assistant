"""Tests for draft_value.py — lineup optimization and snake-draft pick math."""
import unittest

from draft_assistant.draft_value import (
    _snake_pick_numbers,
    _draft_slot,
    _bench_multiplier,
    _bye_week_penalty,
    roster_value,
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
        draft=draft or {"slot": 1, "rollout_sims": 0},
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


class TestDraftSlot(unittest.TestCase):
    def test_empty_state_uses_config_slot(self):
        cfg = _config(teams=10, draft={"slot": 5})
        self.assertEqual(_draft_slot(cfg, None), 5)

    def test_slot_inferred_from_my_picks(self):
        cfg = _config(teams=10, draft={"slot": 1})
        state = DraftState(my_team_name="Me", league_teams=[f"T{i}" for i in range(10)])
        # I own overall pick 3, so my slot is 3 regardless of the config default.
        state.picks = ["a", "b", "mine", "d"]
        state.my_picks = ["mine"]
        self.assertEqual(_draft_slot(cfg, state), 3)

    def test_slot_clamped_to_team_count(self):
        cfg = _config(teams=10, draft={"slot": 99})
        self.assertEqual(_draft_slot(cfg, None), 10)


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


class TestByeWeekPenalty(unittest.TestCase):
    def test_counts_starters_sharing_bye_when_candidate_is_bench(self):
        # Two locked-in starters share bye 9; the weak candidate lands on the
        # bench but still gets penalized for stacking the same bye.
        rb1 = _make_player("RB1", "RB", bye=9)
        rb2 = _make_player("RB2", "RB", bye=9)
        cand = _make_player("RB3", "RB", bye=9)
        pts = {rb1.key(): 200.0, rb2.key(): 190.0, cand.key(): 10.0}
        roster = {"RB": 2, "FLEX": 0, "BN": 3}
        penalty = _bye_week_penalty(cand, [rb1, rb2], pts, roster)
        # Two same-position starters share the bye: 2*0.75 + 2*0.75 = 3.0
        self.assertAlmostEqual(penalty, 3.0)

    def test_no_penalty_when_no_shared_bye(self):
        rb1 = _make_player("RB1", "RB", bye=5)
        cand = _make_player("RB2", "RB", bye=9)
        pts = {rb1.key(): 200.0, cand.key(): 150.0}
        penalty = _bye_week_penalty(cand, [rb1], pts, {"RB": 2, "BN": 2})
        self.assertEqual(penalty, 0.0)


class TestTypedFlex(unittest.TestCase):
    """A WR/TE flex must not be fillable by an RB; superflex can take a QB."""

    def test_wrte_flex_excludes_rb(self):
        rb1, rb2 = _make_player("RB1", "RB"), _make_player("RB2", "RB")
        wr1, te1 = _make_player("WR1", "WR"), _make_player("TE1", "TE")
        pts = {rb1.key(): 300, rb2.key(): 250, wr1.key(): 200, te1.key(): 150}
        players = [rb1, rb2, wr1, te1]
        wrte = roster_value(players, pts, {"RB": 1, "WRTE": 1, "BN": 0})
        flex = roster_value(players, pts, {"RB": 1, "FLEX": 1, "BN": 0})
        # The WR/TE slot takes WR1 (200), NOT the better RB2 (250).
        self.assertIn(wr1, wrte.starters)
        self.assertNotIn(rb2, wrte.starters)
        self.assertEqual(wrte.starter_value, 500.0)
        # A plain FLEX would have grabbed RB2 instead.
        self.assertIn(rb2, flex.starters)
        self.assertEqual(flex.starter_value, 550.0)

    def test_superflex_takes_second_qb(self):
        qb1, qb2 = _make_player("QB1", "QB"), _make_player("QB2", "QB")
        rb1 = _make_player("RB1", "RB")
        pts = {qb1.key(): 400, qb2.key(): 380, rb1.key(): 250}
        r = roster_value([qb1, qb2, rb1], pts, {"QB": 1, "SUPERFLEX": 1, "BN": 0})
        self.assertIn(qb2, r.starters)          # superflex prefers the 2nd QB
        self.assertEqual(r.starter_value, 780.0)


if __name__ == "__main__":
    unittest.main()
