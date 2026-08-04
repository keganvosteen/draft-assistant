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
        self.assertEqual(status, 500)  # handled as an error, not a crash


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
        self.assertEqual(status, 500)
        self.assertIn(b"error", body)

    def test_unknown_route_returns_404_json(self):
        status, body = self.request("POST", "/api/does-not-exist", {})
        self.assertEqual(status, 404)
        self.assertIn(b"not found", body)


if __name__ == "__main__":
    unittest.main()
