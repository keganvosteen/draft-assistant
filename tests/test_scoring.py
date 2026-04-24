"""Tests for fantasy point calculation."""
import unittest

from draft_assistant.scoring import fantasy_points


class TestFantasyPoints(unittest.TestCase):
    def test_basic_qb_scoring(self):
        proj = {"pass_yd": 4000, "pass_td": 30, "pass_int": 10, "rush_yd": 200, "rush_td": 3}
        scoring = {"pass_yd": 0.04, "pass_td": 4, "pass_int": -2, "rush_yd": 0.1, "rush_td": 6}
        pts = fantasy_points(proj, scoring)
        # 4000*0.04 + 30*4 + 10*(-2) + 200*0.1 + 3*6 = 160+120-20+20+18 = 298
        self.assertAlmostEqual(pts, 298.0, places=1)

    def test_ppr_receiver(self):
        proj = {"rec": 100, "rec_yd": 1200, "rec_td": 8}
        scoring = {"rec": 1.0, "rec_yd": 0.1, "rec_td": 6}
        pts = fantasy_points(proj, scoring)
        # 100*1 + 1200*0.1 + 8*6 = 100+120+48 = 268
        self.assertAlmostEqual(pts, 268.0, places=1)

    def test_half_ppr(self):
        proj = {"rec": 80, "rec_yd": 1000, "rec_td": 6}
        scoring = {"rec": 0.5, "rec_yd": 0.1, "rec_td": 6}
        pts = fantasy_points(proj, scoring)
        # 80*0.5 + 1000*0.1 + 6*6 = 40+100+36 = 176
        self.assertAlmostEqual(pts, 176.0, places=1)

    def test_missing_stats_default_zero(self):
        proj = {"pass_yd": 300}
        scoring = {"pass_yd": 0.04, "pass_td": 4, "rec": 1.0}
        pts = fantasy_points(proj, scoring)
        # 300*0.04 + 0*4 + 0*1 = 12
        self.assertAlmostEqual(pts, 12.0, places=1)

    def test_negative_scoring(self):
        proj = {"fumbles": 5, "pass_int": 12}
        scoring = {"fumbles": -2, "pass_int": -2}
        pts = fantasy_points(proj, scoring)
        # 5*(-2) + 12*(-2) = -10 + -24 = -34
        self.assertAlmostEqual(pts, -34.0, places=1)

    def test_kicker_scoring(self):
        proj = {"pat_made": 35, "fg_0_39": 15, "fg_40_49": 8, "fg_50_59": 3, "fg_miss": 4}
        scoring = {"pat_made": 1, "fg_0_39": 3, "fg_40_49": 4, "fg_50_59": 5, "fg_miss": -1}
        pts = fantasy_points(proj, scoring)
        # 35*1 + 15*3 + 8*4 + 3*5 + 4*(-1) = 35+45+32+15-4 = 123
        self.assertAlmostEqual(pts, 123.0, places=1)

    def test_empty_projections(self):
        pts = fantasy_points({}, {"pass_yd": 0.04, "pass_td": 4})
        self.assertAlmostEqual(pts, 0.0)


if __name__ == "__main__":
    unittest.main()
