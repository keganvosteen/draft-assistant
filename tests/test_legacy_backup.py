"""Regression coverage for the one-time, non-destructive legacy rescue bridge."""
import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path

from scripts.backup_running_app import (
    Recovery, local_origin, receiver_handler, temporary_bridge,
    workspace_from_legacy,
)
from http.server import HTTPServer


def legacy():
    return {"fda_leagues": [{"id": "saved-league", "name": "My league", "keepers": ["test|RB"]}],
            "fda_picks": {"saved-league": [{"playerKey": "test|RB", "teamNum": 3}]},
            "fda_tweaks": {"sims": 48}}


class TestLegacyRecovery(unittest.TestCase):
    def test_preserves_league_details_and_does_not_replace_existing_workspace(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = root / "workspace-state.json"
            # Even an unreadable existing file must survive a rescue attempt.
            workspace.write_bytes(b"existing user data")
            recovery = Recovery(root, root / "recovery.json")
            result = recovery.capture(legacy())
            backup = json.loads((root / "recovery.json").read_bytes())
            self.assertFalse(result["workspaceCreated"])
            self.assertEqual(workspace.read_bytes(), b"existing user data")
            self.assertEqual(backup["leagues"], legacy()["fda_leagues"])
            self.assertEqual(backup["picks"], legacy()["fda_picks"])
            self.assertEqual(backup["preferences"], {"tweaks": {"sims": 48}})

    def test_empty_leagues_and_credentials_never_create_a_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            recovery = Recovery(root, root / "recovery.json")
            for payload in ({**legacy(), "fda_leagues": [], "fda_picks": {}},
                            {**legacy(), "fda_tweaks": {"espn_s2": "private"}}):
                with self.assertRaises(ValueError):
                    recovery.capture(payload)
            self.assertEqual(list(root.iterdir()), [])

    def test_valid_backup_initializes_complete_durable_state_once(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            recovery = Recovery(root, root / "recovery.json")
            result = recovery.capture(legacy())
            saved = json.loads((root / "workspace-state.json").read_bytes())
            self.assertTrue(result["workspaceCreated"])
            self.assertEqual(result["leagueCount"], 1)
            self.assertEqual(result["pickCount"], 1)
            self.assertEqual(saved["revision"], 1)
            self.assertTrue(saved["exists"])
            # A retry returns its receipt, even if the browser state changed.
            self.assertEqual(recovery.capture({}), result)

    def test_rejects_other_storage_and_nonlocal_origin(self):
        with self.assertRaises(ValueError):
            workspace_from_legacy({**legacy(), "unknown_storage": {}})
        for origin in ("https://127.0.0.1:8096", "http://example.com:8096", "http://127.0.0.1:8096/path"):
            with self.assertRaises(ValueError):
                local_origin(origin)
        self.assertEqual(local_origin("http://127.0.0.1:8096"), "http://127.0.0.1:8096")

    def test_restores_exact_index_after_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            index = root / "index.html"
            original = b"<!doctype html>\r\n<html><head><title>Draft Assistant</title></head></html>"
            index.write_bytes(original)
            with self.assertRaisesRegex(RuntimeError, "simulated failure"):
                with temporary_bridge(index, "http://127.0.0.1:9000/nonce/backup.js", root / "original.html"):
                    self.assertLess(index.read_bytes().index(b"backup.js"), index.read_bytes().index(b"<title>"))
                    raise RuntimeError("simulated failure")
            self.assertEqual(index.read_bytes(), original)
            self.assertEqual((root / "original.html").read_bytes(), original)

    def test_restore_refuses_to_clobber_an_external_index_change(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            index = root / "index.html"
            index.write_bytes(b"<head><title>Draft Assistant</title></head>")
            with self.assertRaisesRegex(RuntimeError, "changed during backup"):
                with temporary_bridge(index, "http://127.0.0.1:9000/nonce/backup.js", root / "original.html"):
                    index.write_bytes(b"new app update")
            self.assertEqual(index.read_bytes(), b"new app update")

    def test_receiver_rejects_wrong_origin_and_nonce_before_saving(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            recovery = Recovery(root, root / "recovery.json")
            origin = "http://127.0.0.1:8096"
            with HTTPServer(("127.0.0.1", 0), receiver_handler(origin, "nonce", recovery)) as server:
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                try:
                    for request_origin, path in (("http://other.example", "/nonce/capture"),
                                                 (origin, "/wrong/capture")):
                        connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
                        connection.request("POST", path, "",
                                           {"Origin": request_origin, "Content-Type": "application/json"})
                        self.assertEqual(connection.getresponse().status, 403)
                        connection.close()
                    self.assertEqual(list(root.iterdir()), [])
                    connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
                    connection.request("POST", "/nonce/capture", json.dumps(legacy()),
                                       {"Origin": origin, "Content-Type": "application/json"})
                    response = connection.getresponse()
                    self.assertEqual(response.status, 200)
                    self.assertEqual(response.getheader("Access-Control-Allow-Origin"), origin)
                    self.assertEqual(json.loads(response.read())["leagueCount"], 1)
                    connection.close()
                finally:
                    server.shutdown()
                    thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
