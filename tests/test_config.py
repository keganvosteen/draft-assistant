"""Tests for league config loading robustness."""
import json
import os
import shutil
import tempfile
import unittest

from draft_assistant.config import (
    CONFIG_FILENAME,
    DEFAULT_CONFIG,
    LEGACY_CONFIG_FILENAME,
    load_config,
    migrate_legacy_config,
    save_config,
)
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
            draft={"slot": 4, "rollout_sims": 100},
        )
        save_config(cfg, path)
        loaded = load_config(path)
        self.assertEqual(loaded.teams, 9)
        self.assertEqual(loaded.roster["WR"], 3)
        self.assertEqual(loaded.draft["slot"], 4)

    def test_legacy_draft_options_are_migrated(self):
        path = self._write(json.dumps({
            "draft": {"slot": 3, "monte_carlo_sims": 80,
                      "candidate_pool": 24, "snake": True}
        }))
        cfg = load_config(path)
        self.assertEqual(cfg.draft["rollout_sims"], 80)
        self.assertEqual(cfg.draft["rollout_candidates"], 24)
        self.assertNotIn("monte_carlo_sims", cfg.draft)
        self.assertNotIn("candidate_pool", cfg.draft)
        self.assertNotIn("snake", cfg.draft)


class TestLegacyConfigName(unittest.TestCase):
    """league.config.yaml was renamed to .json; the old name still works."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.path = os.path.join(self.dir, CONFIG_FILENAME)
        self.legacy = os.path.join(self.dir, LEGACY_CONFIG_FILENAME)

    def _write_legacy(self, teams: int) -> None:
        with open(self.legacy, "w", encoding="utf-8") as f:
            json.dump({"teams": teams}, f)

    def test_legacy_file_is_read_when_the_new_name_is_absent(self):
        self._write_legacy(14)
        self.assertEqual(load_config(self.path).teams, 14)

    def test_migration_renames_the_legacy_file(self):
        self._write_legacy(14)
        self.assertTrue(migrate_legacy_config(self.path))
        self.assertTrue(os.path.exists(self.path))
        self.assertFalse(os.path.exists(self.legacy))
        self.assertEqual(load_config(self.path).teams, 14)

    def test_migration_never_clobbers_an_existing_config(self):
        self._write_legacy(14)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump({"teams": 8}, f)
        self.assertFalse(migrate_legacy_config(self.path))
        self.assertEqual(load_config(self.path).teams, 8)

    def test_migration_is_a_no_op_without_a_legacy_file(self):
        self.assertFalse(migrate_legacy_config(self.path))
        self.assertFalse(os.path.exists(self.path))

    def test_save_writes_the_new_name(self):
        save_config(LeagueConfig(**DEFAULT_CONFIG), self.path)
        self.assertTrue(os.path.exists(self.path))
        self.assertFalse(os.path.exists(self.legacy))


if __name__ == "__main__":
    unittest.main()
