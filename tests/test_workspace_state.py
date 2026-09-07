"""Upgrade persistence and failure boundaries for complete league state."""
import json
import errno
import multiprocessing
import os
import queue
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from draft_assistant import workspace_state as workspace
from tests.test_web_server import _ServerFixture


def initial_state():
    return {
        "schemaVersion": 1, "revision": 0,
        "leagues": [{"id": "league-a", "name": "Keeper league", "espnLeagueId": "123",
                     "teamIds": ["9", "3"], "teamNames": ["Me", "You"], "draftSlot": 1,
                     "scoring": {"rec": 0.5}, "keepers": [{"playerId": "keeper", "round": 3}],
                     "futureMetadata": {"seasons": [2026, 2027], "enabled": True}},
                    {"id": "league-b", "name": "Second league"}],
        "picks": {"league-a": [{"playerId": "keeper", "teamNum": 1, "keeper": True,
                                 "unknownProviderField": {"value": 42}},
                                {"playerId": "unknown-1", "teamNum": 2, "name": "Unmatched player"}],
                  "league-b": [{"playerId": "different", "teamNum": 1}]},
        "preferences": {"draftTweaks": {"rolloutSims": 24}, "future": {"display": ["weekly", "ros"]}},
    }


def _save_in_process(value, read_started, release_read, results):
    """Hold the first writer after reading to expose cross-process lost updates."""
    read = workspace._read
    def pause_after_read(path):
        state = read(path)
        read_started.put(True)
        if not release_read.wait(10):
            raise RuntimeError("Timed out waiting to finish test save")
        return state
    try:
        with patch.object(workspace, "_read", side_effect=pause_after_read):
            results.put(workspace.save_workspace(value)["revision"])
    except workspace.WorkspaceConflictError:
        results.put("conflict")
    except Exception as exc:
        results.put(type(exc).__name__)


class _WorkspaceFixture:
    def setUp(self):
        super().setUp()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "user-data"
        self.path = self.root / "workspace-state.json"
        env = patch.dict(os.environ, {"DRAFT_ASSISTANT_HOME": str(self.root)})
        env.start()
        self.addCleanup(env.stop)


class TestWorkspace(_WorkspaceFixture, unittest.TestCase):
    def test_initial_read_does_not_seed_or_create_files(self):
        self.assertEqual(workspace.load_workspace(), {
            "exists": False, "revision": 0, "schemaVersion": 1, "leagues": [], "picks": {}, "preferences": {}})
        self.assertFalse(self.root.exists())

    def test_complete_metadata_survives_reopening_after_install_path_changes(self):
        original = initial_state()
        with patch("sys.frozen", True, create=True), patch("sys._MEIPASS", "old-install", create=True):
            saved = workspace.save_workspace(original)
        # Simulate another installation, independent of browser cache and bundle.
        with patch("sys.frozen", True, create=True), patch("sys._MEIPASS", "new-install", create=True):
            reopened = workspace.load_workspace()
        self.assertEqual(reopened, saved)
        self.assertEqual(reopened["leagues"], original["leagues"])
        self.assertEqual(reopened["picks"], original["picks"])
        self.assertEqual(reopened["preferences"], original["preferences"])
        original["leagues"][0]["keepers"].clear()
        self.assertEqual(len(saved["leagues"][0]["keepers"]), 1)

    def test_one_league_update_keeps_other_league_roster_and_revision(self):
        current = workspace.save_workspace(initial_state())
        current["picks"]["league-a"].append({"playerId": "waiver-add", "teamNum": 1})
        next_state = workspace.save_workspace(current)
        self.assertEqual(next_state["revision"], 2)
        self.assertEqual(next_state["picks"]["league-b"], initial_state()["picks"]["league-b"])
        self.assertEqual(json.loads((self.root / "backups/workspace-state.1.json").read_bytes())["picks"], initial_state()["picks"])

    def test_stale_browser_cannot_overwrite_current_leagues(self):
        saved = workspace.save_workspace(initial_state())
        with self.assertRaises(workspace.WorkspaceConflictError) as raised:
            workspace.save_workspace({"schemaVersion": 1, "revision": 0, "leagues": [], "picks": {}})
        self.assertEqual(raised.exception.revision, 1)
        self.assertEqual(workspace.load_workspace(), saved)

    def test_concurrent_saves_only_accept_one_writer_per_revision(self):
        def save():
            try:
                return workspace.save_workspace(initial_state())["revision"]
            except workspace.WorkspaceConflictError:
                return "conflict"
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: save(), range(2)))
        self.assertCountEqual(results, [1, "conflict"])
        self.assertEqual(workspace.load_workspace()["revision"], 1)

    def test_separate_processes_cannot_read_and_replace_the_same_revision(self):
        context = multiprocessing.get_context("spawn")
        read_started, results = context.Queue(), context.Queue()
        release = context.Event()
        processes = [context.Process(target=_save_in_process, args=(initial_state(), read_started, release, results)) for _ in range(2)]
        try:
            for process in processes:
                process.start()
            read_started.get(timeout=10)
            # While the first writer holds its snapshot, a second process may
            # not read that same old revision and later overwrite its update.
            with self.assertRaises(queue.Empty):
                read_started.get(timeout=0.2)
            release.set()
            self.assertCountEqual([results.get(timeout=10), results.get(timeout=10)], [1, "conflict"])
            self.assertEqual(workspace.load_workspace()["revision"], 1)
        finally:
            release.set()
            for process in processes:
                process.join(timeout=10)
                if process.is_alive():
                    process.terminate()
                    process.join(timeout=5)
            read_started.close()
            results.close()

    def test_lock_timeout_leaves_the_current_file_and_backups_unchanged(self):
        saved = workspace.save_workspace(initial_state())
        original = self.path.read_bytes()
        with patch.object(workspace, "LOCK_TIMEOUT_SECONDS", 0), patch.object(
                workspace, "_try_lock", side_effect=BlockingIOError(errno.EACCES, "locked")):
            with self.assertRaises(workspace.WorkspaceStorageError):
                workspace.save_workspace(saved)
        self.assertEqual(self.path.read_bytes(), original)
        self.assertFalse((self.root / "backups").exists())

    def test_corrupt_or_future_file_is_never_replaced(self):
        self.root.mkdir()
        for raw, error in (
            (b"{not json", workspace.WorkspaceStorageError),
            (b'{"schemaVersion":2,"revision":1}', workspace.WorkspaceVersionError),
            (b'{"schemaVersion":1,"schemaVersion":2}', workspace.WorkspaceStorageError),
            (b'{"schemaVersion":1,"revision":0,"leagues":[],"picks":{}}', workspace.WorkspaceStorageError),
        ):
            with self.subTest(raw=raw):
                self.path.write_bytes(raw)
                with self.assertRaises(error):
                    workspace.load_workspace()
                with self.assertRaises(error):
                    workspace.save_workspace(initial_state())
                self.assertEqual(self.path.read_bytes(), raw)
                self.assertFalse((self.root / "backups").exists())

    def test_replace_failure_keeps_current_file_and_complete_backup(self):
        saved = workspace.save_workspace(initial_state())
        original = self.path.read_bytes()
        replace = os.replace
        def fail_main(source, destination):
            if Path(destination) == self.path:
                raise OSError("disk failure")
            replace(source, destination)
        with patch.object(workspace.os, "replace", side_effect=fail_main):
            with self.assertRaises(workspace.WorkspaceStorageError):
                workspace.save_workspace(saved)
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual((self.root / "backups/workspace-state.1.json").read_bytes(), original)
        self.assertEqual(list(self.root.rglob("*.tmp")), [])

    def test_fsync_failure_does_not_create_partial_first_save(self):
        with patch.object(workspace.os, "fsync", side_effect=OSError("disk failure")):
            with self.assertRaises(workspace.WorkspaceStorageError):
                workspace.save_workspace(initial_state())
        self.assertFalse(self.path.exists())
        self.assertEqual(list(self.root.rglob("*.tmp")), [])

    def test_backup_retention_keeps_first_migration_and_recent_ten(self):
        current = workspace.save_workspace(initial_state())
        for _ in range(15):
            current = workspace.save_workspace(current)
        backups = {int(path.stem.split(".")[-1]) for path in (self.root / "backups").glob("*.json")}
        self.assertEqual(backups, {1, *range(6, 16)})
        self.assertEqual(json.loads((self.root / "backups/workspace-state.1.json").read_bytes())["leagues"], initial_state()["leagues"])

    def test_credentials_rejected_at_every_depth_without_echoing_secret(self):
        for key in ("espn_s2", "espnS2", "SWID", "accessToken", "access_token", "refresh-token", "token"):
            value = initial_state()
            value["picks"]["league-a"][0]["future"] = [{key: "private-secret"}]
            with self.subTest(key=key), self.assertRaises(workspace.WorkspaceValidationError) as raised:
                workspace.save_workspace(value)
            self.assertNotIn("private-secret", str(raised.exception))
        self.assertFalse(self.path.exists())

    def test_invalid_ids_and_collections_cannot_damage_saved_state(self):
        saved = workspace.save_workspace(initial_state())
        invalid = []
        for change in (
            {"leagues": [{"id": "same"}, {"id": "same"}]},
            {"leagues": [{"id": 1}]}, {"leagues": [{"id": ""}]},
            {"picks": {"missing-league": []}}, {"picks": {"league-a": ["player-key"]}},
            {"revision": True}, {"schemaVersion": True},
            {"preferences": []},
        ):
            invalid.append({**deepcopy(saved), **change})
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(workspace.WorkspaceValidationError):
                workspace.save_workspace(value)
        self.assertEqual(workspace.load_workspace(), saved)


class TestWorkspaceApi(_WorkspaceFixture, _ServerFixture):
    def test_browser_migration_then_reload_and_conflict(self):
        status, body = self.request("GET", "/api/workspace")
        self.assertEqual(status, 200)
        self.assertFalse(json.loads(body)["exists"])
        status, body = self.request("POST", "/api/workspace", initial_state())
        self.assertEqual(status, 200)
        saved = json.loads(body)
        self.assertEqual(saved["revision"], 1)
        status, body = self.request("GET", "/api/workspace")
        self.assertEqual((status, json.loads(body)), (200, saved))
        status, body = self.request("POST", "/api/workspace", initial_state())
        self.assertEqual(status, 409)
        self.assertEqual(json.loads(body)["code"], "workspace_conflict")
        self.assertEqual(json.loads(body)["currentRevision"], 1)

    def test_storage_failures_are_visible_and_do_not_erase_data(self):
        self.root.mkdir()
        for raw, expected_status, code in (
            (b"broken", 500, "workspace_storage_error"),
            (b'{"schemaVersion":2}', 409, "workspace_newer_version"),
        ):
            self.path.write_bytes(raw)
            for method in ("GET", "POST"):
                status, body = self.request(method, "/api/workspace", initial_state() if method == "POST" else None)
                self.assertEqual((status, json.loads(body)["code"]), (expected_status, code))
                self.assertEqual(self.path.read_bytes(), raw)

    def test_cross_origin_and_credentials_cannot_write_workspace(self):
        status, _ = self.request("POST", "/api/workspace", initial_state(), headers={"Sec-Fetch-Site": "cross-site"})
        self.assertEqual(status, 403)
        value = initial_state()
        value["leagues"][0]["espnS2"] = "private-secret"
        status, body = self.request("POST", "/api/workspace", value)
        self.assertEqual(status, 400)
        self.assertNotIn(b"private-secret", body)
        self.assertFalse(self.path.exists())


if __name__ == "__main__":
    unittest.main()
