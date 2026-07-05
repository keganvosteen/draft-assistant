import unittest

from draft_assistant.models import LeagueConfig, Player
from draft_assistant.strategy_sim import compare_slot, simulate_draft, snake_team, web_league_config


def _p(name, pos, pts, adp):
    stat = "rec_yd" if pos == "WR" else "rush_yd"
    return Player(
        id=f"{name}|{pos}",
        name=name,
        position=pos,
        adp=adp,
        projections={stat: float(pts)},
    )


class TestStrategySimulation(unittest.TestCase):
    def test_snake_team(self):
        self.assertEqual([snake_team(i, 4) for i in range(1, 9)], [1, 2, 3, 4, 4, 3, 2, 1])

    def test_rollout_strategy_can_beat_adp_slot(self):
        players = [
            _p("RB_high", "RB", 310, 1.0),
            _p("WR_elite", "WR", 300, 2.0),
            _p("RB_ok", "RB", 305, 3.0),
            _p("WR_bad", "WR", 100, 4.0),
            _p("RB_fill", "RB", 250, 5.0),
        ]
        config = LeagueConfig(
            teams=2,
            roster={"RB": 1, "WR": 1, "BN": 0},
            scoring={"rush_yd": 1.0, "rec_yd": 1.0},
            provider={},
            draft={"slot": 1, "rollout_sims": 4, "adp_noise": 0.0},
        )

        comparison = compare_slot(config, players, 1)

        self.assertEqual(comparison.score_draft.user_team.picks[0], "WR_elite|WR")
        self.assertEqual(comparison.adp_draft.user_team.picks[0], "RB_high|RB")
        self.assertGreater(comparison.starter_delta, 0)

    def test_adp_autodraft_fills_required_special_team_slot(self):
        players = [
            _p("RB_high", "RB", 100, 1.0),
            Player(id="K|K", name="K", position="K", adp=99.0, projections={"fg_0_39": 10}),
            _p("RB_extra", "RB", 90, 2.0),
        ]
        config = LeagueConfig(
            teams=1,
            roster={"RB": 1, "K": 1, "BN": 0},
            scoring={"rush_yd": 1.0, "fg_0_39": 3.0},
            provider={},
            draft={"slot": 1, "rollout_sims": 0},
        )

        draft = simulate_draft(config, players, 1, user_strategy="adp")

        self.assertEqual(draft.user_team.picks, ["RB_high|RB", "K|K"])

    def test_web_league_config_maps_slots_and_scoring(self):
        base = LeagueConfig(
            teams=10,
            roster={"QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 1, "BN": 6},
            scoring={"rec": 0.5, "rush_yd": 0.1},
            provider={},
            draft={"slot": 1},
        )
        league = {
            "numTeams": 12,
            "draftPosition": 7,
            "scoringType": "ppr",
            "rosterSlots": {"FLEX": 2, "K": 0, "DST": 0},
        }

        config = web_league_config(league, base)

        self.assertEqual(config.teams, 12)
        self.assertEqual(config.draft["slot"], 7)
        self.assertEqual(config.roster["FLEX"], 2)
        self.assertEqual(config.scoring["rec"], 1.0)


if __name__ == "__main__":
    unittest.main()
