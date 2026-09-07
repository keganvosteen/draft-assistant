import unittest

from draft_assistant.models import LeagueConfig, Player
from draft_assistant.strategy_sim import (
    run_single_draft_sim,
    select_adp_pick,
)


def _p(pid, name, pos, pts, adp):
    stat = "pass_yd" if pos == "QB" else "rush_yd" if pos == "RB" else "rec_yd"
    return Player(id=pid, name=name, position=pos, projections={stat: float(pts)}, adp=adp)


class TestStrategySimulation(unittest.TestCase):
    def test_adp_pick_respects_typed_flex(self):
        roster = {"WR": [_p("provider-wr1", "Roster WR", "WR", 100, 1)]}
        slots = {"RB": 0, "WR": 1, "WRTE": 1, "BN": 0}
        rb = _p("provider-rb", "Free RB", "RB", 120, 1)
        te = _p("provider-te", "Free TE", "TE", 90, 2)

        self.assertEqual(select_adp_pick([rb, te], roster, slots, total_slots=2), te)

    def test_simulation_uses_player_keys_not_provider_ids(self):
        players = [
            _p("provider-rb1", "RB One", "RB", 100, 1),
            _p("provider-rb2", "RB Two", "RB", 95, 2),
            _p("provider-rb3", "RB Three", "RB", 90, 3),
            _p("provider-rb4", "RB Four", "RB", 85, 4),
        ]
        cfg = LeagueConfig(
            teams=2,
            roster={"RB": 1, "BN": 1},
            scoring={"rush_yd": 1.0},
            provider={},
            draft={"rollout_sims": 2, "adp_noise": 0.0},
        )

        result = run_single_draft_sim(cfg, 1, players, sims_per_pick=2)

        self.assertEqual(len(result.scores), 2)
        self.assertGreater(result.user_score, 0)
        self.assertIn(result.user_rank, {1, 2})


if __name__ == "__main__":
    unittest.main()
