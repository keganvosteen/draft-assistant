import unittest

from draft_assistant.free_agents import free_agent_recommendations, rank_recommendations
from draft_assistant.models import LeagueConfig, Player, PlayerContext, PlayerSignal


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

    def test_starter_upgrade_without_drop_is_not_called_an_open_slot(self):
        # A positive starter gain with no drop does not mean an empty slot: the
        # roster has room, and the add is simply better than an incumbent.
        rb1 = _p("Roster RB", "RB", 60)
        wr1 = _p("Roster WR", "WR", 90)
        better = _p("Free RB", "RB", 100)
        cfg = _config({"RB": 1, "WR": 1, "BN": 1})

        rows = free_agent_recommendations(cfg, [better], {"RB": [rb1], "WR": [wr1]}, top_n=1)

        self.assertEqual(rows[0].player, better)
        self.assertIsNone(rows[0].drop_player)
        self.assertGreater(rows[0].starter_gain, 0)
        self.assertNotIn("open starting slot", rows[0].reason)
        self.assertIn("Improves your starting lineup", rows[0].reason)

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

    def test_weekly_and_ros_points_are_derived_independently(self):
        add = Player(
            id="source:add", name="Free WR", position="WR",
            projections={"rec_yd": 180}, metadata={"sleeper_id": "1"},
        )
        context = PlayerContext(
            season=2026, selected_week=5,
            weekly_projections={"sleeper:1": {"rec_yd": 20}},
            actual_stats={"sleeper:1": {"rec_yd": 40}},
        )
        rows = free_agent_recommendations(
            _config({"WR": 1}), [add], {}, context=context, week=5,
        )
        self.assertEqual(rows[0].weekly_points, 20)
        self.assertEqual(rows[0].ros_points, 140)
        self.assertEqual(rows[0].weekly_projection_origin, "Sleeper weekly projection")

    def test_out_player_is_zero_this_week_but_not_ros(self):
        add = Player(
            id="source:add", name="Free WR", position="WR",
            projections={"rec_yd": 180}, metadata={"sleeper_id": "1"},
        )
        context = PlayerContext(
            season=2026, selected_week=1,
            weekly_projections={"sleeper:1": {"rec_yd": 20}},
            signals=[PlayerSignal(
                player_id="sleeper:1", kind="injury", value="Out",
                source="Sleeper", observed_at="2098-01-01T00:00:00+00:00",
                effective_week=1, expires_at="2099-01-01T00:00:00+00:00",
            )],
        )
        row = free_agent_recommendations(
            _config({"WR": 1}), [add], {}, context=context, week=1,
        )[0]
        self.assertEqual(row.weekly_points, 0)
        self.assertEqual(row.ros_points, 180)

    def test_weekly_and_ros_sorting_can_disagree(self):
        now = Player(
            id="source:now", name="Weekly Star", position="WR",
            projections={"rec_yd": 100}, metadata={"sleeper_id": "1"},
        )
        later = Player(
            id="source:later", name="ROS Star", position="WR",
            projections={"rec_yd": 200}, metadata={"sleeper_id": "2"},
        )
        context = PlayerContext(2026, 1, weekly_projections={
            "sleeper:1": {"rec_yd": 30}, "sleeper:2": {"rec_yd": 10},
        })
        rows = free_agent_recommendations(
            _config({"WR": 2}), [now, later], {}, top_n=None, context=context,
        )
        self.assertEqual(rank_recommendations(rows, "weekly", 1)[0].player, now)
        self.assertEqual(rank_recommendations(rows, "ros", 1)[0].player, later)

    def test_soft_context_does_not_change_weekly_projection(self):
        add = Player(
            id="source:add", name="Trending WR", position="WR",
            projections={"rec_yd": 180}, metadata={"sleeper_id": "1"},
        )
        context = PlayerContext(
            2026, 1, weekly_projections={"sleeper:1": {"rec_yd": 12}},
            signals=[
                PlayerSignal("sleeper:1", "depth_chart", "WR1", "nflverse", "2098-01-01T00:00:00+00:00"),
                PlayerSignal("sleeper:1", "trend_add", "50", "Sleeper", "2098-01-01T00:00:00+00:00"),
            ],
        )
        row = free_agent_recommendations(
            _config({"WR": 1}), [add], {}, context=context,
        )[0]
        self.assertEqual(row.weekly_points, 12)
        self.assertEqual(row.urgency, 50)


if __name__ == "__main__":
    unittest.main()
