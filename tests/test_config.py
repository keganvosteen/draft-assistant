"""Tests for league config loading robustness."""
import json
import os
import tempfile
import unittest

from draft_assistant.config import DEFAULT_CONFIG, load_config, save_config
from draft_assistant.models import LeagueConfig


class TestLoadConfig(unittest.TestCase):
    def _write(self, content: str) -> str:
        fd, path = tempfile.mkstemp(suffix=".yaml")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        self.addCleanup(os.remove, path)
        return path

    def test_missing_file_returns_defaults(self):
        cfg = load_config("definitely-not-a-real-file.json")
        self.assertEqual(cfg.teams, DEFAULT_CONFIG["teams"])

    def test_invalid_json_falls_back_to_defaults_without_crashing(self):
        path = self._write("teams: 10\nroster:\n  QB: 1\n")  # actual YAML, not JSON
        cfg = load_config(path)
        self.assertEqual(cfg.teams, DEFAULT_CONFIG["teams"])

    def test_unknown_keys_ignored(self):
        path = self._write(json.dumps({
            "teams": 8,
            "roster": {"QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 1, "BN": 5},
            "scoring": {"rec": 1.0},
            "provider": {"type": "local_json", "options": {}},
            "my_note_to_self": "hello",
        }))
        cfg = load_config(path)
        self.assertEqual(cfg.teams, 8)

    def test_missing_keys_filled_from_defaults(self):
        path = self._write(json.dumps({"teams": 14}))
        cfg = load_config(path)
        self.assertEqual(cfg.teams, 14)
        self.assertEqual(cfg.scoring, DEFAULT_CONFIG["scoring"])
        self.assertIn("slot", cfg.draft)

    def test_save_load_round_trip(self):
        path = self._write("{}")
        cfg = LeagueConfig(
            teams=9,
            roster={"QB": 1, "RB": 2, "WR": 3, "TE": 1, "FLEX": 1, "K": 1, "DST": 1, "BN": 6},
            scoring={"rec": 0.5, "rush_yd": 0.1},
            provider={"type": "local_json", "options": {"path": "data/projections.json"}},
            draft={"slot": 4, "monte_carlo_sims": 100},
        )
        save_config(cfg, path)
        loaded = load_config(path)
        self.assertEqual(loaded.teams, 9)
        self.assertEqual(loaded.roster["WR"], 3)
        self.assertEqual(loaded.draft["slot"], 4)


if __name__ == "__main__":
    unittest.main()
