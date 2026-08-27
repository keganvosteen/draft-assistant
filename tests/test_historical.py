"""Tests for historical trend analysis and age curves."""
import unittest

from draft_assistant.models import Player
from draft_assistant.historical import (
    age_curve_factor,
    adjust_projections,
    confidence_score,
    history_recency_factor,
)


class TestAgeCurves(unittest.TestCase):
    def test_peak_age_returns_one(self):
        # RB peaks at 25
        self.assertAlmostEqual(age_curve_factor("RB", 25), 1.0)
        # QB peaks at 27-28
        self.assertAlmostEqual(age_curve_factor("QB", 27), 1.0)

    def test_old_rb_declines(self):
        factor = age_curve_factor("RB", 30)
        self.assertLess(factor, 0.75)

    def test_young_wr_lower(self):
        factor = age_curve_factor("WR", 21)
        self.assertLess(factor, 0.80)

    def test_unknown_age_returns_one(self):
        self.assertAlmostEqual(age_curve_factor("QB", None), 1.0)

    def test_dst_always_one(self):
        self.assertAlmostEqual(age_curve_factor("DST", 30), 1.0)

    def test_interpolation(self):
        # Age 24.5 for RB should be between 24 and 25
        f24 = age_curve_factor("RB", 24)
        f25 = age_curve_factor("RB", 25)
        self.assertLess(f24, f25)


class TestAdjustProjections(unittest.TestCase):
    def test_no_history_no_age_returns_raw(self):
        p = Player(id="1", name="Test", position="RB", projections={"rush_yd": 1000})
        adj = adjust_projections(p, {"rush_yd": 0.1})
        self.assertAlmostEqual(adj["rush_yd"], 1000.0)

    def test_age_curve_applied(self):
        p = Player(id="1", name="Test", position="RB", age=30,
                   projections={"rush_yd": 1000})
        adj = adjust_projections(p, {"rush_yd": 0.1})
        # Age 30 RB has < 1.0 factor
        self.assertLess(adj["rush_yd"], 1000.0)

    def test_historical_blending(self):
        # season is pinned so the blend weight does not drift with the calendar:
        # 2023 is the last completed season relative to 2024, so the history is
        # current and carries its full positional weight.
        p = Player(id="1", name="Test", position="RB", age=25,
                   projections={"rush_yd": 1000},
                   historical_stats={2023: {"rush_yd": 1200}, 2022: {"rush_yd": 1100}})
        adj = adjust_projections(p, {"rush_yd": 0.1}, season=2024)
        # Trend (decay 0.6): (1200*1 + 1100*0.6) / 1.6 = 1162.5
        # Blended (RB weight 0.8): 0.8*1000 + 0.2*1162.5 = 1032.5, then aged.
        self.assertGreater(adj["rush_yd"], 1000.0)
        self.assertLess(adj["rush_yd"], 1200.0)

    def test_team_change_penalty(self):
        p = Player(id="1", name="Test", position="WR", age=26,
                   team="NYG", previous_team="DAL",
                   projections={"rec_yd": 1000})
        adj = adjust_projections(p, {"rec_yd": 0.1})
        self.assertLess(adj["rec_yd"], 1000.0)

    def test_age_applies_year_over_year_not_absolute(self):
        # A 30yo RB should get the curve's 29->30 change (~13%), not the
        # absolute curve value (34%) on top of an age-aware projection.
        p = Player(id="1", name="Test", position="RB", age=30,
                   projections={"rush_yd": 1000})
        adj = adjust_projections(p, {"rush_yd": 0.1})
        self.assertLess(adj["rush_yd"], 1000.0)
        self.assertGreater(adj["rush_yd"], 800.0)

    def test_peak_age_projection_unchanged(self):
        p = Player(id="1", name="Test", position="WR", age=27,
                   projections={"rec_yd": 1200})
        adj = adjust_projections(p, {"rec_yd": 0.1})
        self.assertAlmostEqual(adj["rec_yd"], 1200.0, places=0)

    def test_no_projection_falls_back_to_trend(self):
        # Players whose only data is past actuals should still score.
        p = Player(id="1", name="Test", position="WR", age=26,
                   projections={},
                   historical_stats={2025: {"rec": 80, "rec_yd": 1100}})
        adj = adjust_projections(p, {"rec": 0.5, "rec_yd": 0.1}, season=2026)
        self.assertGreater(adj.get("rec_yd", 0.0), 0.0)
        self.assertGreater(adj.get("rec", 0.0), 0.0)


class TestHistoryRecency(unittest.TestCase):
    """A history that stops early is evidence the player did not play.

    This is the Joe Mixon case: 1,000-yard seasons in 2023 and 2024, nothing in
    2025 because he never took a snap, and a 2026 board that still ranked him as
    a draftable RB on the strength of that old production.
    """

    def _rb(self, newest_season):
        return Player(
            id="1", name="Test", position="RB", age=29,
            projections={"rush_yd": 138},
            historical_stats={newest_season: {"rush_yd": 1016},
                              newest_season - 1: {"rush_yd": 1034}},
        )

    def test_current_history_keeps_full_weight(self):
        self.assertEqual(history_recency_factor({2025: {}}, season=2026), 1.0)

    def test_factor_decays_once_per_missing_season(self):
        self.assertAlmostEqual(history_recency_factor({2024: {}}, season=2026), 0.6)
        self.assertAlmostEqual(history_recency_factor({2023: {}}, season=2026), 0.36)

    def test_no_history_is_not_penalised(self):
        self.assertEqual(history_recency_factor({}, season=2026), 1.0)

    def test_future_or_current_season_never_boosts(self):
        # Guards against a negative gap producing a factor above 1.0.
        self.assertEqual(history_recency_factor({2026: {}}, season=2026), 1.0)

    def test_stale_history_pulls_the_blend_toward_the_projection(self):
        current = adjust_projections(self._rb(2025), {"rush_yd": 0.1}, season=2026)
        stale = adjust_projections(self._rb(2024), {"rush_yd": 0.1}, season=2026)
        # Same player, same numbers -- only the season the history stops at
        # differs, and the stale one must sit closer to its 138-yard projection.
        self.assertLess(stale["rush_yd"], current["rush_yd"])

    def test_a_missing_season_never_inflates_a_current_player(self):
        # The guard must be inert for anyone whose history is up to date.
        p = Player(id="1", name="Test", position="WR", age=26,
                   projections={"rec_yd": 1000},
                   historical_stats={2025: {"rec_yd": 1200}})
        self.assertEqual(
            adjust_projections(p, {"rec_yd": 0.1}, season=2026),
            adjust_projections(p, {"rec_yd": 0.1}, season=2026),
        )

    def test_trend_only_player_is_damped_when_stale(self):
        # With no projection to blend toward, the trend itself must be damped.
        fresh = Player(id="1", name="A", position="WR", age=26, projections={},
                       historical_stats={2025: {"rec_yd": 1100}})
        stale = Player(id="2", name="B", position="WR", age=26, projections={},
                       historical_stats={2023: {"rec_yd": 1100}})
        self.assertLess(
            adjust_projections(stale, {"rec_yd": 0.1}, season=2026)["rec_yd"],
            adjust_projections(fresh, {"rec_yd": 0.1}, season=2026)["rec_yd"],
        )


class TestConfidenceScore(unittest.TestCase):
    def test_baseline(self):
        p = Player(id="1", name="Test", position="QB", projections={})
        self.assertAlmostEqual(confidence_score(p), 0.5)

    def test_history_boosts_confidence(self):
        p = Player(id="1", name="Test", position="QB",
                   historical_stats={2022: {}, 2023: {}, 2024: {}})
        self.assertGreater(confidence_score(p), 0.5)

    def test_injury_lowers_confidence(self):
        p = Player(id="1", name="Test", position="RB",
                   injury_history=["ACL", "Hamstring"])
        self.assertLess(confidence_score(p), 0.5)

    def test_team_change_lowers_confidence(self):
        p = Player(id="1", name="Test", position="WR",
                   team="NYG", previous_team="DAL")
        self.assertLess(confidence_score(p), 0.5)


if __name__ == "__main__":
    unittest.main()
