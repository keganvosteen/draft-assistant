import unittest

from draft_assistant.free_agents import free_agent_recommendations
from draft_assistant.models import LeagueConfig, Player


def _p(name, pos, pts, adp=None):
    stat = "rush_yd" if pos == "RB" else "rec_yd" if pos in {"WR", "TE"} else "pass_yd"
    return Player(
        id=f"{name}|{pos}",
        name=name,
        position=pos,
        projections={stat: float(pts)},
        adp=adp,
    )


SCORING = {"rush_yd": 1.0, "rec_yd": 1.0, "pass_yd": 1.0}


def _config(roster):
    return LeagueConfig(
        teams=10,
        roster=roster,
        scoring=SCORING,
        provider={},
        draft={},
    )


class TestFreeAgentRecommendations(unittest.TestCase):
    def test_full_roster_suggests_drop_for_best_upgrade(self):
        rb1 = _p("Roster RB1", "RB", 100)
        wr1 = _p("Roster WR1", "WR", 90)
        bench = _p("Bench RB", "RB", 70)
        add = _p("Free RB", "RB", 95, adp=80)
        weak = _p("Free WR", "WR", 60, adp=40)
        cfg = _config({"RB": 1, "WR": 1, "BN": 1})

        rows = free_agent_recommendations(
            cfg,
            [add, weak],
            {"RB": [rb1, bench], "WR": [wr1]},
            top_n=5,
        )

        self.assertEqual(rows[0].player, add)
        self.assertEqual(rows[0].drop_player, bench)
        self.assertGreater(rows[0].roster_gain, 0)

    def test_open_roster_slot_does_not_force_drop(self):
        rb1 = _p("Roster RB", "RB", 100)
        wr1 = _p("Free WR", "WR", 90)
        cfg = _config({"RB": 1, "WR": 1, "BN": 0})

        rows = free_agent_recommendations(cfg, [wr1], {"RB": [rb1]}, top_n=1)

        self.assertEqual(rows[0].player, wr1)
        self.assertIsNone(rows[0].drop_player)
        self.assertGreater(rows[0].starter_gain, 0)

    def test_full_roster_candidate_not_kept_is_suppressed(self):
        rostered = _p("Roster RB", "RB", 100)
        no_upgrade = _p("Free RB", "RB", 90, adp=1)
        cfg = _config({"RB": 1, "BN": 0})

        rows = free_agent_recommendations(cfg, [no_upgrade], {"RB": [rostered]}, top_n=5)

        self.assertEqual(rows, [])

    def test_scoring_changes_rankings(self):
        volume = Player(
            id="Volume|WR", name="Volume", position="WR",
            projections={"rec": 10, "rec_yd": 50},
        )
        yardage = Player(
            id="Yardage|WR", name="Yardage", position="WR",
            projections={"rec": 1, "rec_yd": 100},
        )
        roster = {"WR": 1, "BN": 0}
        standard = LeagueConfig(teams=10, roster=roster, scoring={"rec": 0, "rec_yd": 1}, provider={}, draft={})
        ppr = LeagueConfig(teams=10, roster=roster, scoring={"rec": 10, "rec_yd": 1}, provider={}, draft={})

        standard_rows = free_agent_recommendations(standard, [volume, yardage], {}, top_n=2)
        ppr_rows = free_agent_recommendations(ppr, [volume, yardage], {}, top_n=2)

        self.assertEqual(standard_rows[0].player, yardage)
        self.assertEqual(ppr_rows[0].player, volume)


if __name__ == "__main__":
    unittest.main()
