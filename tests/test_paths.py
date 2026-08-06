"""Tests for paths.py — where an installed build reads and writes.

The invariant under test: in a source checkout every path stays relative
(what the rest of the suite and the CLI docs assume), and only a packaged
build or an explicit DRAFT_ASSISTANT_HOME redirects to a per-user directory.
"""
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from draft_assistant import paths


class TestResolveInCheckout(unittest.TestCase):
    """No override, not frozen — paths must be untouched."""

    def setUp(self):
        self._env = mock.patch.dict(os.environ, {}, clear=False)
        self._env.start()
        os.environ.pop("DRAFT_ASSISTANT_HOME", None)

    def tearDown(self):
        self._env.stop()

    def test_mutable_root_is_none(self):
        self.assertIsNone(paths.mutable_root())

    def test_resolve_is_identity(self):
        self.assertEqual(paths.resolve("league.config.yaml"), "league.config.yaml")
        self.assertEqual(paths.resolve("data/projections.json"), "data/projections.json")

    def test_seed_is_a_noop(self):
        # Nothing to seed into: a checkout already has its files in place.
        paths.seed_user_data()  # must not raise

    def test_resource_dir_is_repo_root(self):
        self.assertTrue((paths.resource_dir() / "draft_assistant").is_dir())


class TestResolveWithOverride(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self._env = mock.patch.dict(os.environ, {"DRAFT_ASSISTANT_HOME": self._tmp})
        self._env.start()

    def tearDown(self):
        self._env.stop()
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_user_data_dir_follows_override(self):
        self.assertEqual(paths.user_data_dir(), Path(self._tmp))

    def test_resolve_is_absolute_and_rooted(self):
        resolved = Path(paths.resolve("data/projections.json"))
        self.assertTrue(resolved.is_absolute())
        self.assertEqual(resolved, Path(self._tmp) / "data" / "projections.json")

    def test_seed_copies_bundled_files(self):
        paths.seed_user_data()
        board = Path(self._tmp) / "data" / "projections.json"
        self.assertTrue(board.is_file(), "player board was not seeded")
        self.assertTrue((Path(self._tmp) / "league.config.yaml").is_file())

    def test_seed_never_overwrites_existing_state(self):
        """An upgrade must not clobber a league config or a draft in progress."""
        config = Path(self._tmp) / "league.config.yaml"
        config.parent.mkdir(parents=True, exist_ok=True)
        config.write_text('{"teams": 14}', encoding="utf-8")

        paths.seed_user_data()

        self.assertEqual(config.read_text(encoding="utf-8"), '{"teams": 14}')


class TestPlatformDataDirs(unittest.TestCase):
    """Each OS gets its conventional location when no override is set."""

    def setUp(self):
        self._env = mock.patch.dict(os.environ, {}, clear=False)
        self._env.start()
        os.environ.pop("DRAFT_ASSISTANT_HOME", None)

    def tearDown(self):
        self._env.stop()

    def test_windows_uses_localappdata(self):
        with mock.patch.object(paths.sys, "platform", "win32"):
            with mock.patch.dict(os.environ, {"LOCALAPPDATA": r"C:\Users\x\AppData\Local"}):
                self.assertEqual(
                    paths.user_data_dir(),
                    Path(r"C:\Users\x\AppData\Local") / "DraftAssistant",
                )

    def test_macos_uses_application_support(self):
        with mock.patch.object(paths.sys, "platform", "darwin"):
            expected = Path.home() / "Library" / "Application Support" / "DraftAssistant"
            self.assertEqual(paths.user_data_dir(), expected)

    def test_linux_honours_xdg(self):
        with mock.patch.object(paths.sys, "platform", "linux"):
            with mock.patch.dict(os.environ, {"XDG_DATA_HOME": "/tmp/xdg"}):
                self.assertEqual(paths.user_data_dir(), Path("/tmp/xdg") / "DraftAssistant")


class TestFrozenBuild(unittest.TestCase):
    def setUp(self):
        self._env = mock.patch.dict(os.environ, {}, clear=False)
        self._env.start()
        os.environ.pop("DRAFT_ASSISTANT_HOME", None)

    def tearDown(self):
        self._env.stop()

    def test_frozen_redirects_away_from_cwd(self):
        with mock.patch.object(paths.sys, "frozen", True, create=True):
            self.assertTrue(paths.is_frozen())
            self.assertIsNotNone(paths.mutable_root())
            self.assertTrue(Path(paths.resolve("draft_state.json")).is_absolute())

    def test_resource_dir_uses_pyinstaller_unpack_dir(self):
        with mock.patch.object(paths.sys, "frozen", True, create=True):
            with mock.patch.object(paths.sys, "_MEIPASS", "/unpacked", create=True):
                self.assertEqual(paths.resource_dir(), Path("/unpacked"))


if __name__ == "__main__":
    unittest.main()
