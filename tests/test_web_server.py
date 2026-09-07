"""Tests for the local web server's request guard and error handling.

The server binds to loopback, which keeps other machines out but does nothing
about a page the user already has open in their browser — hence the same-origin
guard these tests pin down.
"""
import json
import threading
import unittest
from functools import partial
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer

from draft_assistant.web.server import MAX_BODY_BYTES, DraftAPIHandler


class _ServerFixture(unittest.TestCase):
    """Runs the real handler on an ephemeral loopback port."""

    @classmethod
    def setUpClass(cls):
        handler = partial(DraftAPIHandler, profile="default")
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)

    def request(self, method, path, body=None, headers=None, host=None):
        conn = HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            payload = None if body is None else json.dumps(body).encode()
            hdrs = {"Content-Type": "application/json"}
            hdrs.update(headers or {})
            if host is not None:
                hdrs["Host"] = host
            conn.request(method, path, body=payload, headers=hdrs)
            resp = conn.getresponse()
            return resp.status, resp.read()
        finally:
            conn.close()


class TestSameOriginGuard(_ServerFixture):
    def test_same_origin_post_is_allowed(self):
        status, _ = self.request(
            "POST", "/api/import-espn", {"leagueId": ""},
            headers={"Sec-Fetch-Site": "same-origin"},
        )
        self.assertEqual(status, 400)  # reached the handler, which rejects the empty id

    def test_cross_site_post_is_refused(self):
        # A cross-origin HTML form POST is a "simple request" — no preflight —
        # so without this guard it would reach the handler and mutate state.
        status, body = self.request(
            "POST", "/api/state", {"picks": []},
            headers={"Sec-Fetch-Site": "cross-site"},
        )
        self.assertEqual(status, 403)
        self.assertIn(b"cross-origin", body)

    def test_cross_site_get_is_refused(self):
        status, _ = self.request(
            "GET", "/api/state", headers={"Sec-Fetch-Site": "cross-site"})
        self.assertEqual(status, 403)

    def test_same_site_is_not_same_origin(self):
        status, _ = self.request(
            "POST", "/api/state", {"picks": []},
            headers={"Sec-Fetch-Site": "same-site"},
        )
        self.assertEqual(status, 403)

    def test_mismatched_origin_is_refused(self):
        status, _ = self.request(
            "POST", "/api/state", {"picks": []},
            headers={
                "Sec-Fetch-Site": "same-origin",
                "Origin": "http://localhost:1",
            },
            host=f"localhost:{self.port}",
        )
        self.assertEqual(status, 403)

    def test_exact_origin_is_allowed(self):
        status, _ = self.request(
            "POST", "/api/import-espn", {"leagueId": ""},
            headers={
                "Sec-Fetch-Site": "same-origin",
                "Origin": f"http://localhost:{self.port}",
            },
            host=f"localhost:{self.port}",
        )
        self.assertEqual(status, 400)

    def test_direct_navigation_is_allowed(self):
        # Sec-Fetch-Site: none means the user typed the URL / used a bookmark.
        status, _ = self.request(
            "POST", "/api/import-espn", {"leagueId": ""},
            headers={"Sec-Fetch-Site": "none"},
        )
        self.assertEqual(status, 400)

    def test_foreign_host_header_is_refused(self):
        # DNS rebinding: an attacker's name resolving to 127.0.0.1 looks
        # same-origin to the browser, so Sec-Fetch-Site alone would pass it.
        status, _ = self.request(
            "POST", "/api/state", {"picks": []},
            headers={"Sec-Fetch-Site": "same-origin"}, host="evil.example.com",
        )
        self.assertEqual(status, 403)

    def test_localhost_host_header_is_allowed(self):
        status, _ = self.request(
            "POST", "/api/import-espn", {"leagueId": ""},
            headers={"Sec-Fetch-Site": "same-origin"}, host=f"localhost:{self.port}",
        )
        self.assertEqual(status, 400)

    def test_non_browser_client_without_sec_fetch_is_allowed(self):
        # curl and the CLI send no Sec-Fetch-Site; the Host check still applies.
        status, _ = self.request("POST", "/api/import-espn", {"leagueId": ""})
        self.assertEqual(status, 400)

    def test_static_files_are_not_guarded(self):
        status, body = self.request(
            "GET", "/index.html", headers={"Sec-Fetch-Site": "cross-site"})
        self.assertEqual(status, 200)
        self.assertIn(b"Draft Assistant", body)


class TestRequestBodyLimits(_ServerFixture):
    def test_oversized_content_length_is_rejected(self):
        conn = HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            conn.putrequest("POST", "/api/import-espn")
            conn.putheader("Content-Type", "application/json")
            # Claim far more than the cap without sending it: the server must
            # refuse on the header rather than allocate what it was told.
            conn.putheader("Content-Length", str(MAX_BODY_BYTES + 1))
            conn.endheaders()
            conn.send(b"{}")
            status = conn.getresponse().status
        finally:
            conn.close()
        self.assertEqual(status, 413)

    def test_non_json_content_type_is_rejected(self):
        status, _ = self.request(
            "POST", "/api/state", {"picks": []},
            headers={"Content-Type": "text/plain"},
        )
        self.assertEqual(status, 415)

    def test_suggestion_top_is_bounded_before_work_runs(self):
        status, body = self.request("POST", "/api/suggest", {"top": 101})
        self.assertEqual(status, 400)
        self.assertIn(b"top", body)


class TestEarlyRejectionsCloseCleanly(_ServerFixture):
    """The 403/413/415 replies land instead of being lost to a reset.

    Those three answer before reading the request body. Closing a socket with
    received-but-unread bytes still buffered is an *abortive* close on Windows:
    the RST makes the client discard the reply it had not read yet, and
    `getresponse()` raises ConnectionAbortedError instead of returning a
    status. It reproduced on roughly 3% of requests, which is what made the
    full suite intermittently red. The handler now drains the body first.

    These loop because the failure is a race — one request would usually pass
    even with the drain removed. At ~3% per request, 100 iterations catches a
    regression better than 95 times out of 100.
    """

    REPEATS = 100

    def _repeat(self, send):
        aborted = []
        for _ in range(self.REPEATS):
            try:
                send()
            except OSError as exc:  # the reset, surfacing as a client error
                aborted.append(exc)
        self.assertEqual(aborted, [], f"{len(aborted)}/{self.REPEATS} connections reset")

    def test_cross_origin_rejection_is_delivered(self):
        def send():
            status, _ = self.request(
                "POST", "/api/state", {"picks": []},
                headers={"Sec-Fetch-Site": "cross-site"},
            )
            self.assertEqual(status, 403)
        self._repeat(send)

    def test_oversized_rejection_is_delivered(self):
        def send():
            conn = HTTPConnection("127.0.0.1", self.port, timeout=10)
            try:
                conn.putrequest("POST", "/api/import-espn")
                conn.putheader("Content-Type", "application/json")
                conn.putheader("Content-Length", str(MAX_BODY_BYTES + 1))
                conn.endheaders()
                conn.send(b"{}")
                self.assertEqual(conn.getresponse().status, 413)
            finally:
                conn.close()
        self._repeat(send)

    def test_unsupported_media_type_rejection_is_delivered(self):
        def send():
            status, _ = self.request(
                "POST", "/api/state", {"picks": []},
                headers={"Content-Type": "text/plain"},
            )
            self.assertEqual(status, 415)
        self._repeat(send)


class TestMalformedBodyHandling(_ServerFixture):
    def test_malformed_json_returns_an_error_response(self):
        """Regression: this used to raise UnboundLocalError inside the handler's
        own except clause, dropping the connection instead of replying."""
        conn = HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            conn.request(
                "POST", "/api/import-espn", body=b"not json at all",
                headers={"Content-Type": "application/json"},
            )
            resp = conn.getresponse()
            status, body = resp.status, resp.read()
        finally:
            conn.close()
        self.assertEqual(status, 400)
        self.assertIn(b"error", body)

    def test_json_array_body_is_rejected(self):
        conn = HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            conn.request(
                "POST", "/api/state", body=b"[]",
                headers={"Content-Type": "application/json"},
            )
            resp = conn.getresponse()
            status, body = resp.status, resp.read()
        finally:
            conn.close()
        self.assertEqual(status, 400)
        self.assertIn(b"object", body)

    def test_unknown_route_returns_404_json(self):
        status, body = self.request("POST", "/api/does-not-exist", {})
        self.assertEqual(status, 404)
        self.assertIn(b"not found", body)


class TestContextAndUpdateEndpoints(_ServerFixture):
    def test_context_returns_freshness_contract(self):
        status, body = self.request("GET", "/api/context")
        payload = json.loads(body)
        self.assertEqual(status, 200)
        self.assertIn("season", payload)
        self.assertIn("week", payload)
        self.assertIn("stale", payload)
        self.assertIn("sources", payload)
        self.assertIn("signals", payload)

    def test_context_refresh_validates_week_before_background_work(self):
        status, body = self.request("POST", "/api/context/refresh", {"week": 19})
        self.assertEqual(status, 400)
        self.assertIn(b"week", body)

    def test_suggest_reports_news_freshness(self):
        # The eligibility filter is only as good as the feed behind it, so the
        # draft room has to be told when that feed is out of date rather than
        # being left to imply the news was checked.
        status, body = self.request("POST", "/api/suggest", {"top": 1})
        payload = json.loads(body)
        self.assertEqual(status, 200)
        self.assertIn("contextStale", payload)
        self.assertIsInstance(payload["contextStale"], bool)
        self.assertIsInstance(payload["contextFailedSources"], list)

    def test_update_endpoint_is_safe_in_source_checkout(self):
        status, body = self.request("GET", "/api/update")
        payload = json.loads(body)
        self.assertEqual(status, 200)
        self.assertFalse(payload["supported"])
        self.assertFalse(payload["updateAvailable"])


class TestYahooEndpoints(_ServerFixture):
    def test_yahoo_status_endpoint(self):
        status, body = self.request("GET", "/api/yahoo/status")
        self.assertEqual(status, 200)
        payload = json.loads(body)
        self.assertIn("hasCredentials", payload)
        self.assertIn("hasToken", payload)
        self.assertIn("redirectUri", payload)

    def test_yahoo_import_requires_league_key(self):
        status, body = self.request("POST", "/api/yahoo/import", {"leagueKey": ""})
        self.assertEqual(status, 400)
        self.assertIn(b"leagueKey required", body)

    def test_yahoo_draft_requires_league_key(self):
        status, body = self.request("POST", "/api/yahoo/draft", {"league": {}})
        self.assertEqual(status, 400)
        self.assertIn(b"missing yahooLeagueKey", body)

    def test_yahoo_draft_sync_requires_league_key(self):
        status, body = self.request("POST", "/api/draft-sync", {"league": {"platform": "Yahoo"}})
        self.assertEqual(status, 400)
        self.assertIn(b"missing yahooLeagueKey", body)

    def test_yahoo_draft_sync_success(self):
        from unittest.mock import patch
        with patch.object(DraftAPIHandler, "_yahoo_access_token", return_value="fake-token"), \
             patch("draft_assistant.importers.yahoo.fetch_draft_picks", return_value=[]):
            status, body = self.request("POST", "/api/draft-sync", {
                "league": {"platform": "Yahoo", "yahooLeagueKey": "nfl.l.12345", "numTeams": 10, "draftPosition": 1}
            })
            self.assertEqual(status, 200)
            payload = json.loads(body.decode("utf-8"))
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["source"], "Yahoo")
            self.assertEqual(payload["leagueKey"], "nfl.l.12345")

    def test_yahoo_parse_settings_empty(self):
        status, body = self.request("POST", "/api/yahoo/parse-settings", {"text": ""})
        self.assertEqual(status, 400)
        payload = json.loads(body.decode("utf-8"))
        self.assertIn("error", payload)

    def test_yahoo_parse_settings_valid(self):
        sample = (
            "League Name: Gridiron Greats\n"
            "Max Teams: 10\n"
            "Draft Type: Snake\n"
            "Roster Positions: QB, WR, WR, RB, RB, TE, W/R/T, K, DEF, BN, BN, BN, BN, BN, BN\n"
            "Passing Touchdowns: 6\n"
            "Receptions: 1\n"
        )
        status, body = self.request("POST", "/api/yahoo/parse-settings", {"text": sample})
        self.assertEqual(status, 200)
        payload = json.loads(body.decode("utf-8"))
        self.assertEqual(payload["name"], "Gridiron Greats")
        self.assertEqual(payload["numTeams"], 10)
        self.assertEqual(payload["scoringType"], "ppr")
        self.assertEqual(payload["scoring"]["pass_td"], 6.0)
        self.assertEqual(payload["scoring"]["rec"], 1.0)
        self.assertEqual(payload["rosterSlots"]["QB"], 1)

    def test_yahoo_exchange_needs_approval(self):
        from unittest.mock import patch
        with patch.object(DraftAPIHandler, "_yahoo_load", return_value={"client_id": "test_id", "client_secret": "test_secret"}), \
             patch.object(DraftAPIHandler, "_yahoo_save"), \
             patch("draft_assistant.importers.yahoo.exchange_code", return_value={"access_token": "fake"}), \
             patch("draft_assistant.importers.yahoo.list_leagues", side_effect=RuntimeError("additional_authorization_required")):
            status, body = self.request("POST", "/api/yahoo/exchange", {"code": "auth-code"})
            self.assertEqual(status, 403)
            payload = json.loads(body.decode("utf-8"))
            self.assertTrue(payload.get("needsApproval"))
            self.assertEqual(payload.get("code"), "yahoo_additional_authorization_required")
            self.assertEqual(payload.get("approvalUrl"), "https://sports.yahoo.com/developer/access/")

    def test_yahoo_import_needs_approval(self):
        from unittest.mock import patch
        with patch.object(DraftAPIHandler, "_yahoo_load", return_value={"token": {"access_token": "fake"}}), \
             patch.object(DraftAPIHandler, "_yahoo_access_token", return_value="fake-token"), \
             patch("draft_assistant.importers.yahoo.fetch_league", side_effect=RuntimeError("additional_authorization_required")):
            status, body = self.request("POST", "/api/yahoo/import", {"leagueKey": "nfl.l.12345"})
            self.assertEqual(status, 403)
            payload = json.loads(body.decode("utf-8"))
            self.assertTrue(payload.get("needsApproval"))
            self.assertEqual(payload.get("code"), "yahoo_additional_authorization_required")
            self.assertEqual(payload.get("approvalUrl"), "https://sports.yahoo.com/developer/access/")



if __name__ == "__main__":
    unittest.main()
