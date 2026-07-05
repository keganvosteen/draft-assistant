"""Tests for the web /api/suggest scoring bridge (scoring_for_league).

Ensures the web LeagueSetup scoring choice is faithfully translated into Python
scoring keys for the rollout engine, mirroring the frontend's calcProjection.
"""
import unittest

from draft_assistant.web.server import scoring_for_league


BASE = {
    "pass_yd": 0.04, "pass_td": 4, "rush_yd": 0.1, "rush_td": 6,
    "rec_yd": 0.1, "rec_td": 6, "rec": 0.5, "fumbles": -2,
    # K/DST weights that the UI never carries — must survive every overlay.
    "fg_0_39": 3, "sack": 1, "def_int": 2,
}


class TestScoringForLeague(unittest.TestCase):
    def test_no_type_returns_base_unchanged(self):
        self.assertIs(scoring_for_league({}, BASE), BASE)

    def test_presets_only_change_reception(self):
        for stype, rec in (("standard", 0.0), ("half-ppr", 0.5), ("ppr", 1.0)):
            s = scoring_for_league({"scoringType": stype}, BASE)
            self.assertEqual(s["rec"], rec, stype)
            # Everything else (incl. K/DST) is preserved.
            self.assertEqual(s["pass_td"], 4)
            self.assertEqual(s["fg_0_39"], 3)
            self.assertEqual(s["sack"], 1)

    def test_preset_does_not_mutate_base(self):
        scoring_for_league({"scoringType": "ppr"}, BASE)
        self.assertEqual(BASE["rec"], 0.5)  # unchanged

    def test_custom_maps_and_inverts_yardage(self):
        cs = {"passYds": 25, "passTD": 6, "rushYds": 10, "rushTD": 6,
              "recYds": 10, "recTD": 6, "reception": 1.0, "twoPt": 2,
              "fumbleLost": -2, "fumRetTD": 6}
        s = scoring_for_league({"scoringType": "custom", "customScoring": cs}, BASE)
        self.assertAlmostEqual(s["pass_yd"], 1 / 25)   # 25 yds-per-point -> 0.04
        self.assertAlmostEqual(s["rec_yd"], 0.1)        # 10 yds-per-point -> 0.1
        self.assertEqual(s["pass_td"], 6)               # custom 6pt pass TD
        self.assertEqual(s["rec"], 1.0)
        self.assertEqual(s["rec_2pt"], 2)
        # K/DST still preserved from base.
        self.assertEqual(s["fg_0_39"], 3)

    def test_custom_zero_yard_denominator_is_safe(self):
        s = scoring_for_league(
            {"scoringType": "custom", "customScoring": {"passYds": 0}}, BASE)
        self.assertEqual(s["pass_yd"], 0.0)

    def test_custom_missing_fumble_keeps_base_penalty(self):
        s = scoring_for_league(
            {"scoringType": "custom", "customScoring": {"reception": 1.0}}, BASE)
        self.assertEqual(s["fumbles"], -2)  # falls back to base, not 0


if __name__ == "__main__":
    unittest.main()
