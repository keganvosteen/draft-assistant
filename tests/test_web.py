import os
import tempfile
import unittest

from draft_assistant.web import build_snapshot, record_pick, reset_draft, update_config


class TestWebSnapshot(unittest.TestCase):
    def test_snapshot_uses_real_scoring_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            cwd = os.getcwd()
            try:
                os.chdir(tmp)
                snapshot = build_snapshot("default")
            finally:
                os.chdir(cwd)

        self.assertTrue(snapshot["ok"])
        self.assertGreater(len(snapshot["players"]), 0)
        self.assertGreater(len(snapshot["recommendations"]), 0)
        top = snapshot["recommendations"][0]
        self.assertIn("score", top)
        self.assertIn("lineupGain", top)
        self.assertIn("scarcity", top)
        self.assertIn("needMultiplier", top)

    def test_record_pick_and_reset_round_trip_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            cwd = os.getcwd()
            try:
                os.chdir(tmp)
                snapshot = build_snapshot("default")
                key = snapshot["recommendations"][0]["key"]

                after_pick = record_pick("default", {"key": key, "mine": True})
                self.assertEqual(after_pick["state"]["pickCount"], 1)
                self.assertEqual(after_pick["state"]["myPicks"], [key])

                after_reset = reset_draft("default")
                self.assertEqual(after_reset["state"]["pickCount"], 0)
                self.assertEqual(after_reset["state"]["myPicks"], [])
            finally:
                os.chdir(cwd)

    def test_update_config_changes_dynamic_roster_settings(self):
        with tempfile.TemporaryDirectory() as tmp:
            cwd = os.getcwd()
            try:
                os.chdir(tmp)
                updated = update_config("default", {
                    "teams": 10,
                    "roster": {
                        "QB": 1,
                        "RB": 2,
                        "WR": 3,
                        "TE": 1,
                        "FLEX": 2,
                        "K": 1,
                        "DST": 1,
                        "BN": 5,
                    },
                    "draft": {
                        "slot": 7,
                        "monte_carlo_sims": 0,
                        "adp_noise": 9.5,
                    },
                })
            finally:
                os.chdir(cwd)

        self.assertEqual(updated["config"]["teams"], 10)
        self.assertEqual(updated["config"]["roster"]["WR"], 3)
        self.assertEqual(updated["config"]["roster"]["FLEX"], 2)
        self.assertEqual(updated["draft"]["slot"], 7)


if __name__ == "__main__":
    unittest.main()
