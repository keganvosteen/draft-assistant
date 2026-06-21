"""Tests for the rest-of-draft Monte Carlo rollout engine.

The headline guarantee is the scarcity test: when one position has a steep
talent cliff and another is deep, the engine should prefer taking the scarce
player now even if the deep-position player scores MORE points in isolation,
because that yields more total season points across the finished roster.
"""
import unittest

from draft_assistant.models import DraftState, LeagueConfig, Player
from draft_assistant.rollout import rollout_values, RolloutResult


def _p(name, pos, pts, adp=None, bye=None):
    # scoring below maps rush_yd / rec_yd 1:1 to points, so `pts` is exact.
    stat = "rush_yd" if pos == "RB" else "rec_yd" if pos == "WR" else "rush_yd"
    return Player(id=f"{name}|{pos}", name=name, position=pos,
                  projections={stat: float(pts)}, adp=adp, bye_week=bye)


SCORING = {"rush_yd": 1.0, "rec_yd": 1.0, "rec": 0.0, "fg_0_39": 3}


def _config(roster, teams=2, slot=1, sims=24, noise=1.0):
    return LeagueConfig(
        teams=teams, roster=roster, scoring=SCORING, provider={},
        draft={"slot": slot, "rollout_sims": sims, "adp_noise": noise},
    )


class TestScarcity(unittest.TestCase):
    def test_prefers_scarce_position_over_higher_points(self):
        # WR position is a cliff (300 then 100); RB is deep (310/300/295).
        # The higher-scoring player at pick 1 is the RB (310 > 300), but taking
        # the elite WR now is worth more season points because a near-equal RB
        # is still there at the next pick while the WR drops off a cliff.
        available = [
            _p("WR_elite", "WR", 300, adp=1.0),
            _p("RB_good", "RB", 310, adp=1.5),
            _p("RB_ok", "RB", 300, adp=2.0),
            _p("RB_ok2", "RB", 295, adp=2.5),
            _p("WR_bad", "WR", 100, adp=3.0),
            _p("RB_fill", "RB", 50, adp=6.0),
            _p("WR_fill", "WR", 50, adp=7.0),
            _p("RB_fill2", "RB", 45, adp=8.0),
        ]
        cfg = _config({"RB": 1, "WR": 1, "BN": 1})
        res = rollout_values(cfg, available, {}, state=None, top_n=8)
        by_name = {r.player.name: r for r in res}

        # Sanity: the RB really does score more in isolation.
        self.assertGreater(by_name["RB_good"].points, by_name["WR_elite"].points)
        # But the engine ranks the scarce WR first and gives it higher impact.
        self.assertEqual(res[0].player.name, "WR_elite")
        self.assertGreater(by_name["WR_elite"].impact, by_name["RB_good"].impact)

    def test_deep_position_is_replaceable(self):
        # Two equal RBs, one elite WR. With RB deep, the engine should not panic
        # over RB; the WR (scarce) should out-rank both RBs.
        available = [
            _p("WR_elite", "WR", 280, adp=1.0),
            _p("RB_a", "RB", 285, adp=1.5),
            _p("RB_b", "RB", 282, adp=2.0),
            _p("WR_bad", "WR", 90, adp=3.0),
            _p("RB_fill", "RB", 60, adp=6.0),
            _p("WR_fill", "WR", 55, adp=7.0),
        ]
        cfg = _config({"RB": 1, "WR": 1, "BN": 1})
        res = rollout_values(cfg, available, {}, state=None, top_n=6)
        self.assertEqual(res[0].player.position, "WR")


class TestConfigDriven(unittest.TestCase):
    def test_points_follow_league_scoring(self):
        # A pass-catching back is worth more under PPR than standard — the
        # engine must read scoring from config, never hard-code it.
        catcher = Player(id="Catch|RB", name="Catch", position="RB",
                         projections={"rush_yd": 500, "rec": 80, "rec_yd": 600}, adp=1.0)
        field = [catcher,
                 Player(id="Rush|RB", name="Rush", position="RB",
                        projections={"rush_yd": 1100}, adp=1.2),
                 Player(id="Wr|WR", name="Wr", position="WR",
                        projections={"rec": 90, "rec_yd": 1200}, adp=1.5)]
        roster = {"RB": 2, "WR": 1, "BN": 1}
        std = LeagueConfig(teams=2, roster=roster, provider={},
                           scoring={"rush_yd": 0.1, "rec_yd": 0.1, "rec": 0.0},
                           draft={"slot": 1, "rollout_sims": 8})
        ppr = LeagueConfig(teams=2, roster=roster, provider={},
                           scoring={"rush_yd": 0.1, "rec_yd": 0.1, "rec": 1.0},
                           draft={"slot": 1, "rollout_sims": 8})
        std_pts = {r.player.name: r.points for r in rollout_values(std, [p for p in field], {}, top_n=3)}
        ppr_pts = {r.player.name: r.points for r in rollout_values(ppr, [p for p in field], {}, top_n=3)}
        # 80 receptions -> +80 points under full PPR.
        self.assertAlmostEqual(ppr_pts["Catch"] - std_pts["Catch"], 80.0, places=1)

    def test_roster_shape_changes_pick_structure(self):
        # Just assert the engine runs and ranks under a different roster shape
        # without any hard-coded assumptions blowing up.
        available = [_p(f"RB{i}", "RB", 300 - i * 5, adp=float(i + 1)) for i in range(6)]
        available += [_p(f"WR{i}", "WR", 290 - i * 5, adp=float(i + 1.3)) for i in range(6)]
        cfg = _config({"QB": 0, "RB": 2, "WR": 3, "FLEX": 1, "BN": 2}, teams=4)
        res = rollout_values(cfg, available, {}, state=None, top_n=10)
        self.assertGreater(len(res), 0)
        self.assertTrue(all(isinstance(r, RolloutResult) for r in res))


class TestPolicyDetails(unittest.TestCase):
    def test_kicker_not_recommended_early(self):
        available = [
            _p("RB1", "RB", 300, adp=1.0),
            _p("WR1", "WR", 290, adp=1.2),
            Player(id="K1|K", name="K1", position="K",
                   projections={"fg_0_39": 50}, adp=1.1),  # absurd kicker
            _p("RB2", "RB", 250, adp=2.0),
            _p("WR2", "WR", 240, adp=2.2),
        ]
        cfg = _config({"QB": 0, "RB": 2, "WR": 2, "K": 1, "BN": 1}, teams=2)
        res = rollout_values(cfg, available, {}, state=None, top_n=5)
        # The kicker should be deferred — never the top pick when skill is open.
        self.assertNotEqual(res[0].player.position, "K")

    def test_deterministic(self):
        available = [_p(f"RB{i}", "RB", 300 - i * 7, adp=float(i + 1)) for i in range(8)]
        cfg = _config({"RB": 2, "WR": 1, "BN": 1})
        a = rollout_values(cfg, [p for p in available], {}, top_n=5)
        b = rollout_values(cfg, [p for p in available], {}, top_n=5)
        self.assertEqual([(r.player.name, r.impact) for r in a],
                         [(r.player.name, r.impact) for r in b])


class TestDegenerate(unittest.TestCase):
    def test_zero_sims_falls_back(self):
        available = [_p("RB1", "RB", 300, adp=1.0), _p("WR1", "WR", 290, adp=1.2)]
        cfg = _config({"RB": 1, "WR": 1, "BN": 1}, sims=0)
        res = rollout_values(cfg, available, {}, top_n=5)
        self.assertGreater(len(res), 0)
        self.assertTrue(all(isinstance(r, RolloutResult) for r in res))
        self.assertEqual(res[0].sims, 0)

    def test_empty_board(self):
        cfg = _config({"RB": 1, "WR": 1, "BN": 1})
        self.assertEqual(rollout_values(cfg, [], {}, top_n=5), [])


if __name__ == "__main__":
    unittest.main()
