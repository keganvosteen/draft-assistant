"""Yahoo's real HTTP failures must reach the UI without exposing response data."""
import unittest
from io import BytesIO
from unittest.mock import patch
from urllib.error import HTTPError

from draft_assistant.importers import yahoo


class TestYahooHttpErrors(unittest.TestCase):
    def test_permission_error_survives_long_response_and_is_closed(self):
        body = BytesIO(b"prefix " * 100 + b"additional_authorization_required")
        error = HTTPError("https://fantasysports.yahooapis.com/fantasy/v2/users", 401,
                          "Unauthorized", {}, body)
        with patch.object(yahoo, "urlopen", side_effect=error):
            with self.assertRaises(yahoo.YahooAPIError) as raised:
                yahoo.list_leagues("token")
        self.assertEqual(raised.exception.code, "yahoo_additional_authorization_required")
        self.assertEqual(raised.exception.status, 403)
        self.assertTrue(body.closed)

    def test_invalid_token_is_distinct_from_missing_fantasy_permission(self):
        error = HTTPError("https://fantasysports.yahooapis.com/fantasy/v2/users", 401,
                          "Unauthorized", {}, BytesIO(b"token_expired private-response"))
        with patch.object(yahoo, "urlopen", side_effect=error):
            with self.assertRaises(yahoo.YahooAPIError) as raised:
                yahoo.list_leagues("token")
        self.assertEqual(raised.exception.code, "yahoo_auth_required")
        self.assertEqual(raised.exception.status, 401)
        self.assertNotIn("private-response", str(raised.exception))

    def test_reused_code_has_actionable_error_without_echoing_provider_body(self):
        error = HTTPError(yahoo.TOKEN_URL, 400, "Bad Request", {},
                          BytesIO(b'{"error":"invalid_grant","description":"private-response"}'))
        with patch.object(yahoo, "urlopen", side_effect=error):
            with self.assertRaises(yahoo.YahooAPIError) as raised:
                yahoo.exchange_code("client", "secret", "used-code")
        self.assertIn("new authorize link", str(raised.exception))
        self.assertNotIn("private-response", str(raised.exception))

    def test_token_response_without_access_token_is_not_a_success(self):
        with patch.object(yahoo, "urlopen", return_value=BytesIO(b'{"refresh_token":"refresh"}')):
            with self.assertRaises(yahoo.YahooAPIError):
                yahoo.exchange_code("client", "secret", "code")
