"""Tests for historical trend analysis and age curves."""
import unittest

from draft_assistant.models import Player
from draft_assistant.historical import (
    age_curve_factor,
    adjust_projections,
    confidence_score,
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
        p = Player(id="1", name="Test", position="RB", age=25,
                   projections={"rush_yd": 1000},
                   historical_stats={2023: {"rush_yd": 1200}, 2022: {"rush_yd": 1100}})
        adj = adjust_projections(p, {"rush_yd": 0.1})
        # Blended: 60% raw + 40% historical trend, age factor ~1.0
        # Historical trend: (1200*3 + 1100*2) / 5 = 5800/5 = 1160
        # Blended: 0.6*1000 + 0.4*1160 = 600 + 464 = 1064
        self.assertGreater(adj["rush_yd"], 1000.0)
        self.assertLess(adj["rush_yd"], 1200.0)

    def test_team_change_penalty(self):
        p = Player(id="1", name="Test", position="WR", age=26,
                   team="NYG", previous_team="DAL",
                   projections={"rec_yd": 1000})
        adj = adjust_projections(p, {"rec_yd": 0.1})
        self.assertLess(adj["rec_yd"], 1000.0)


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
