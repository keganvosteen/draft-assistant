"""Provider credential lifecycle with temporary profiles and synthetic tokens."""
import contextlib
import io
import json
import os
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock, patch

from draft_assistant import secret_store
from draft_assistant.web.server import DraftAPIHandler
from tests.test_secret_store import unreadable


class _Handlers:
    """Request handlers pointed at a temporary profile directory."""

    def handler(self, body=None, profile="one"):
        handler = DraftAPIHandler.__new__(DraftAPIHandler)
        handler.profile = profile
        handler._secret_dir = lambda: os.path.join(self.directory, profile)
        handler._read_body = MagicMock(return_value=body or {})
        handler._send_json = MagicMock()
        return handler

    def result(self, handler):
        payload = handler._send_json.call_args[0][0]
        self.assertNotIn("error", payload)
        return payload

    def token(self, access="access", expired=False):
        return {"access_token": access, "refresh_token": "refresh",
                "obtained_at": 0 if expired else time.time(), "expires_in": 3600}


class TestCredentialSessions(_Handlers, unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = directory.name
        backend = patch.object(secret_store, "backend", return_value="none")
        backend.start()
        self.addCleanup(backend.stop)
        self.addCleanup(secret_store._session.clear)
        self.addCleanup(secret_store._plaintext_removed.clear)

    def test_a_status_request_announces_the_plaintext_file_it_removes_once(self):
        # Asking whether credentials are saved is enough to consume a legacy
        # file. With no keystore that deletes the only durable copy, so it has
        # to be said: once on stderr, and in the line the UI shows as "storage".
        store = os.path.join(self.directory, "one", "yahoo.json")
        os.makedirs(os.path.dirname(store))
        with open(store, "w", encoding="utf-8") as handle:
            json.dump({"client_id": "synthetic-id", "client_secret": "synthetic-secret"}, handle)
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            for _ in range(2):
                status = self.handler()
                status._handle_yahoo_status()
                payload = self.result(status)
                self.assertTrue(payload["hasCredentials"])
                self.assertFalse(payload["canSave"])
                self.assertIn("memory only", payload["storage"])
                self.assertIn("re-entered after the app restarts", payload["storage"])
        self.assertFalse(os.path.exists(store))
        notices = stderr.getvalue().splitlines()
        self.assertEqual(len(notices), 1, notices)
        self.assertIn(os.path.abspath(store), notices[0])
        self.assertIn("re-entered after the app restarts", notices[0])
        self.assertNotIn("synthetic-secret", stderr.getvalue())
        self.assertTrue(secret_store.plaintext_removed(store, "yahoo"))
        # The next process starts with nothing, exactly as the notice warned.
        secret_store._session.clear()
        self.assertEqual(self.handler()._yahoo_load(), {})

    def test_yahoo_connect_exchange_status_refresh_and_disconnect_stay_in_memory(self):
        connect = self.handler({"clientId": "synthetic-id", "clientSecret": "synthetic-secret"})
        connect._handle_yahoo_connect()
        self.assertIn("authUrl", self.result(connect))
        status = self.handler()
        status._handle_yahoo_status()
        payload = self.result(status)
        self.assertTrue(payload["hasCredentials"])
        self.assertFalse(payload["hasToken"])
        self.assertFalse(payload["canSave"])
        self.assertIn("memory", payload["storage"])
        self.assertNotIn("synthetic-secret", str(payload))
        self.assertEqual(self.handler(profile="two")._yahoo_load(), {})

        exchange = self.handler({"code": "synthetic-code"})
        with patch("draft_assistant.importers.yahoo.exchange_code", return_value=self.token(expired=True)), \
             patch("draft_assistant.importers.yahoo.list_leagues", return_value=[]):
            exchange._handle_yahoo_exchange()
        self.assertTrue(self.result(exchange)["ok"])
        with patch("draft_assistant.importers.yahoo.refresh_access_token", return_value=self.token("renewed")) as refresh:
            self.assertEqual(self.handler()._yahoo_access_token(), "renewed")
            self.assertEqual(self.handler()._yahoo_access_token(), "renewed")
            self.assertEqual(refresh.call_count, 1)

        disconnect = self.handler()
        disconnect._handle_yahoo_disconnect()
        self.assertTrue(self.result(disconnect)["hasCredentials"])
        self.assertNotIn("token", self.handler()._yahoo_load())
        forget = self.handler({"forgetCredentials": True})
        forget._handle_yahoo_disconnect()
        self.assertFalse(self.result(forget)["hasCredentials"])
        self.assertEqual(self.handler()._yahoo_load(), {})
        self.assertEqual(os.listdir(self.directory), [])

    def test_yahoo_changing_client_credentials_clears_old_authorization(self):
        handler = self.handler({"clientId": "new-id", "clientSecret": "new-secret"})
        handler._yahoo_save({"client_id": "old-id", "client_secret": "old-secret",
                             "redirect_uri": "https://localhost/", "token": self.token()})
        handler._handle_yahoo_connect()
        self.result(handler)
        self.assertNotIn("token", self.handler()._yahoo_load())

    def test_parallel_yahoo_requests_refresh_only_once(self):
        self.handler()._yahoo_save({"client_id": "id", "client_secret": "secret",
                                   "token": self.token(expired=True)})
        barrier = threading.Barrier(4)

        def access():
            barrier.wait(timeout=5)
            return self.handler()._yahoo_access_token()

        def refresh(*args):
            time.sleep(0.03)  # Keep the other requests overlapping the refresh.
            return self.token("renewed")

        with patch("draft_assistant.importers.yahoo.refresh_access_token", side_effect=refresh) as call, \
             ThreadPoolExecutor(max_workers=4) as pool:
            results = [future.result(timeout=5) for future in [pool.submit(access) for _ in range(4)]]
        self.assertEqual(results, ["renewed"] * 4)
        self.assertEqual(call.call_count, 1)

    def test_disconnect_waits_for_refresh_and_cannot_be_undone_by_it(self):
        self.handler()._yahoo_save({"client_id": "id", "client_secret": "secret",
                                   "token": self.token(expired=True)})
        started, release, disconnecting = threading.Event(), threading.Event(), threading.Event()

        def refresh(*args):
            started.set()
            self.assertTrue(release.wait(timeout=5))
            return self.token("renewed")

        def disconnect():
            disconnecting.set()
            handler = self.handler({"forgetCredentials": True})
            handler._handle_yahoo_disconnect()
            return self.result(handler)

        with patch("draft_assistant.importers.yahoo.refresh_access_token", side_effect=refresh), \
             ThreadPoolExecutor(max_workers=2) as pool:
            refreshing = pool.submit(self.handler()._yahoo_access_token)
            self.assertTrue(started.wait(timeout=5))
            forgetting = pool.submit(disconnect)
            try:
                self.assertTrue(disconnecting.wait(timeout=5))
            finally:
                release.set()
            self.assertEqual(refreshing.result(timeout=5), "renewed")
            self.assertFalse(forgetting.result(timeout=5)["hasToken"])
        self.assertEqual(self.handler()._yahoo_load(), {})

    def test_espn_session_is_shared_between_requests_but_not_profiles(self):
        supplied = self.handler()._espn_access({"leagueId": "123", "espnS2": "cookie", "swid": "swid"}, {})
        self.assertEqual(supplied, ("cookie", "swid"))
        self.assertEqual(self.handler()._espn_access({}, {"espnLeagueId": "123"}), supplied)
        self.assertEqual(self.handler(profile="two")._espn_access({}, {"espnLeagueId": "123"}), (None, None))
        status = self.handler({"leagueId": "123"})
        status._handle_espn_credentials()
        self.assertTrue(self.result(status)["saved"])
        self.assertFalse(self.result(status)["canSave"])
        forget = self.handler({"leagueId": "123", "forget": True})
        forget._handle_espn_credentials()
        self.assertEqual(self.handler()._espn_saved("123"), {})
        self.assertEqual(os.listdir(self.directory), [])

    def test_parallel_espn_remember_keeps_all_leagues(self):
        barrier = threading.Barrier(4)

        def remember(league):
            barrier.wait(timeout=5)
            self.handler()._espn_remember(str(league), "cookie", "swid")

        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = [pool.submit(remember, league) for league in range(4)]
            for future in futures:
                future.result(timeout=5)
        for league in range(4):
            self.assertEqual(self.handler()._espn_saved(str(league)), {"espnS2": "cookie", "swid": "swid"})


class TestKeychainCredentialSessions(_Handlers, unittest.TestCase):
    """The same handlers against a stand-in Keychain, where the file is a marker."""

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = directory.name
        self.entries = {}
        for name, options in (
                ("backend", {"return_value": "keychain"}),
                ("_keychain_read", {"side_effect": self.entries.get}),
                ("_keychain_write", {"side_effect": self.entries.__setitem__}),
                ("_keychain_delete", {"side_effect": lambda key: self.entries.pop(key, None)})):
            mock = patch.object(secret_store, name, **options)
            mock.start()
            self.addCleanup(mock.stop)

    def test_yahoo_authorization_survives_moving_the_profile_directory(self):
        # Renaming a profile (or relocating the data directory) used to drop
        # the authorization and strand its Keychain item, because the item was
        # named after the path the marker happened to sit at.
        saved = {"client_id": "synthetic-id", "client_secret": "synthetic-secret",
                 "redirect_uri": "https://localhost/", "token": self.token()}
        self.handler(profile="one")._yahoo_save(saved)
        os.rename(os.path.join(self.directory, "one"), os.path.join(self.directory, "two"))
        self.assertEqual(self.handler(profile="two")._yahoo_load(), saved)
        status = self.handler(profile="two")
        status._handle_yahoo_status()
        self.assertTrue(self.result(status)["hasToken"])
        self.assertEqual(self.handler(profile="two")._yahoo_access_token(), "access")
        self.assertEqual(len(self.entries), 1)
        forget = self.handler({"forgetCredentials": True}, profile="two")
        forget._handle_yahoo_disconnect()
        self.assertFalse(self.result(forget)["hasCredentials"])
        self.assertEqual(self.entries, {})
        self.assertEqual(os.listdir(os.path.join(self.directory, "two")), [])

    def test_disconnect_with_the_marker_out_of_reach_fails_instead_of_stranding_the_item(self):
        # Disconnect loads the store, drops the token and saves what is left.
        # A marker that cannot be read loads as empty, and saving "nothing" is
        # a forget: it deleted the marker, lost the Client ID and Secret with
        # it, and left the item in the Keychain where nothing could find it.
        saved = {"client_id": "synthetic-id", "client_secret": "synthetic-secret", "token": self.token()}
        self.handler()._yahoo_save(saved)
        store = os.path.join(self.directory, "one", "yahoo.json")
        for body in ({}, {"forgetCredentials": True}):
            with self.subTest(body=body), unreadable(store):
                disconnect = self.handler(body)
                disconnect._handle_yahoo_disconnect()
                payload, status = disconnect._send_json.call_args[0]
                self.assertEqual(status, 500)
                self.assertIn("credential marker", payload["error"])
                self.assertNotIn("synthetic-secret", payload["error"])
        self.assertEqual(self.handler()._yahoo_load(), saved)
        self.assertEqual(len(self.entries), 1)

    def test_parallel_first_saves_share_one_keychain_item(self):
        # Each first save mints a random item id. Racing ones must agree on a
        # single id rather than each stranding an item of its own.
        barrier = threading.Barrier(4)

        def remember(league):
            barrier.wait(timeout=5)
            self.handler()._espn_remember(str(league), "cookie", "swid")

        with ThreadPoolExecutor(max_workers=4) as pool:
            for future in [pool.submit(remember, league) for league in range(4)]:
                future.result(timeout=5)
        for league in range(4):
            self.assertEqual(self.handler()._espn_saved(str(league)), {"espnS2": "cookie", "swid": "swid"})
        self.assertEqual(len(self.entries), 1)
        self.assertEqual(self.handler(profile="two")._espn_saved("0"), {})

    def test_forgetting_one_profile_leaves_the_other_authorized(self):
        for profile in ("one", "two"):
            self.handler(profile=profile)._yahoo_save(
                {"client_id": profile, "client_secret": "synthetic-secret", "token": self.token(profile)})
        forget = self.handler({"forgetCredentials": True}, profile="one")
        forget._handle_yahoo_disconnect()
        self.result(forget)
        self.assertEqual(self.handler(profile="one")._yahoo_load(), {})
        self.assertEqual(self.handler(profile="two")._yahoo_access_token(), "two")
        self.assertEqual(len(self.entries), 1)


if __name__ == "__main__":
    unittest.main()
