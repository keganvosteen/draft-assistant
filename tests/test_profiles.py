"""Tests for profiles.py — multi-league profile management."""
import json
import os
import shutil
import tempfile
import unittest

from draft_assistant.config import LEGACY_CONFIG_FILENAME, load_config
from draft_assistant.profiles import (
    DEFAULT_PROFILE,
    PROFILE_ROOT,
    SHARED_PROJECTIONS_PATH,
    normalize_profile_name,
    get_profile_paths,
    ensure_profile,
    list_profiles,
)


class TestNormalizeProfileName(unittest.TestCase):
    def test_default(self):
        self.assertEqual(normalize_profile_name(""), DEFAULT_PROFILE)
        self.assertEqual(normalize_profile_name("default"), DEFAULT_PROFILE)
        self.assertEqual(normalize_profile_name(None), DEFAULT_PROFILE)

    def test_basic(self):
        self.assertEqual(normalize_profile_name("league-a"), "league-a")
        self.assertEqual(normalize_profile_name("Home League"), "home-league")

    def test_strips_special_chars(self):
        self.assertEqual(normalize_profile_name("My League!"), "my-league")


class TestGetProfilePaths(unittest.TestCase):
    def test_default_uses_root_files(self):
        paths = get_profile_paths(DEFAULT_PROFILE)
        self.assertEqual(paths.config_path, "league.config.json")
        self.assertEqual(paths.state_path, "draft_state.json")
        self.assertEqual(paths.projections_path, SHARED_PROJECTIONS_PATH)

    def test_named_profile_uses_subdir(self):
        paths = get_profile_paths("league-a")
        self.assertIn(".draft_assistant_profiles", paths.config_path)
        self.assertIn("league-a", paths.config_path)
        # Projections are shared
        self.assertEqual(paths.projections_path, SHARED_PROJECTIONS_PATH)


class TestEnsureProfile(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self._orig = os.getcwd()
        os.chdir(self._tmp)

    def tearDown(self):
        os.chdir(self._orig)
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_creates_config_and_state(self):
        paths = ensure_profile("test-league")
        self.assertTrue(os.path.exists(paths.config_path))
        self.assertTrue(os.path.exists(paths.state_path))

    def test_idempotent(self):
        paths1 = ensure_profile("test-league")
        paths2 = ensure_profile("test-league")
        self.assertEqual(paths1.config_path, paths2.config_path)

    def test_profile_written_before_the_rename_keeps_its_settings(self):
        # A profile created by an older build has league.config.yaml. It must
        # be adopted, not shadowed by a freshly defaulted league.config.json.
        paths = get_profile_paths("old-league")
        os.makedirs(paths.base_dir, exist_ok=True)
        legacy = os.path.join(paths.base_dir, LEGACY_CONFIG_FILENAME)
        with open(legacy, "w", encoding="utf-8") as f:
            json.dump({"teams": 14}, f)

        ensure_profile("old-league")

        self.assertFalse(os.path.exists(legacy))
        self.assertTrue(os.path.exists(paths.config_path))
        self.assertEqual(load_config(paths.config_path).teams, 14)


class TestListProfiles(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self._orig = os.getcwd()
        os.chdir(self._tmp)

    def tearDown(self):
        os.chdir(self._orig)
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_includes_default(self):
        profiles = list_profiles()
        self.assertIn(DEFAULT_PROFILE, profiles)

    def test_includes_created_profile(self):
        ensure_profile("my-league")
        profiles = list_profiles()
        self.assertIn("my-league", profiles)


if __name__ == "__main__":
    unittest.main()
