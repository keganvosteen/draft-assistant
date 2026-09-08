"""Exercise saved Yahoo connections without real credentials or network access."""
import copy
import io
import json
import time
import unittest
from email.message import Message
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlparse
from unittest.mock import Mock, patch

from draft_assistant.importers import yahoo
from draft_assistant.web.server import DraftAPIHandler


def _saved_connection():
    return {
        "client_id": "test-client", "client_secret": "test-secret",
        "redirect_uri": "https://localhost/",
        "token": {"access_token": "test-access", "refresh_token": "test-refresh",
                  "obtained_at": int(time.time()), "expires_in": 3600},
    }


def _handler(saved=None, body=None):
    # Skip HTTP transport setup; retain the real endpoint and token helpers.
    handler = object.__new__(DraftAPIHandler)
    handler._read_body = Mock(return_value=body or {})
    handler._yahoo_load = Mock(return_value=copy.deepcopy(saved or {}))
    handler._yahoo_save = Mock()
    handler._send_json = Mock()
    return handler


def _response(handler):
    args = handler._send_json.call_args.args
    return args[0], args[1] if len(args) > 1 else 200


class TestYahooSavedConnection(unittest.TestCase):
    def test_lists_leagues_with_saved_token_without_exchanging_another_code(self):
        handler = _handler(_saved_connection())
        payload = {"fantasy_content": {"leagues": [{"league": {
            "league_key": "461.l.123", "name": "Test league", "season": "2026",
        }}]}}
        with patch.object(yahoo, "urlopen", return_value=io.BytesIO(json.dumps(payload).encode())) as get, \
             patch.object(yahoo, "exchange_code") as exchange:
            handler._handle_yahoo_leagues()

        response, status = _response(handler)
        self.assertEqual(status, 200)
        self.assertEqual(response["leagues"], [
            {"league_key": "461.l.123", "name": "Test league", "season": "2026"},
        ])
        request = get.call_args.args[0]
        self.assertEqual(request.get_header("Authorization"), "Bearer test-access")
        self.assertIn("users;use_login=1/games;game_keys=nfl/leagues", request.full_url)
        exchange.assert_not_called()
        handler._yahoo_save.assert_not_called()

    def test_changing_credentials_or_redirect_discards_token_for_previous_app(self):
        changes = [
            ("clientId", "client_id", "replacement-client"),
            ("clientSecret", "client_secret", "replacement-secret"),
            ("redirectUri", "redirect_uri", "https://localhost/new-callback"),
        ]
        for field, stored_field, value in changes:
            with self.subTest(field=field):
                handler = _handler(_saved_connection(), {field: value})
                handler._handle_yahoo_connect()

                response, status = _response(handler)
                self.assertEqual(status, 200)
                saved = handler._yahoo_save.call_args.args[0]
                self.assertNotIn("token", saved)
                self.assertEqual(saved[stored_field], value)
                auth = parse_qs(urlparse(response["authUrl"]).query)
                self.assertEqual(auth["client_id"], [saved["client_id"]])
                self.assertEqual(auth["redirect_uri"], [saved["redirect_uri"]])
                self.assertNotIn(saved["client_secret"], response["authUrl"])

    def test_reauthorizing_same_app_can_reuse_saved_credentials(self):
        saved = _saved_connection()
        handler = _handler(saved)

        handler._handle_yahoo_connect()

        response, status = _response(handler)
        self.assertEqual(status, 200)
        self.assertEqual(handler._yahoo_save.call_args.args[0], saved)
        self.assertEqual(parse_qs(urlparse(response["authUrl"]).query)["client_id"], ["test-client"])

    def test_refresh_retains_old_refresh_token_unless_provider_rotates_it(self):
        for rotated in (None, "replacement-refresh"):
            with self.subTest(rotated=rotated is not None):
                saved = _saved_connection()
                saved["token"]["obtained_at"] = 0
                handler = _handler(saved)
                refreshed = {"access_token": "replacement-access", "expires_in": 3600}
                if rotated is not None:
                    refreshed["refresh_token"] = rotated
                replies = [
                    io.BytesIO(json.dumps(refreshed).encode()),
                    io.BytesIO(b'{"fantasy_content":{"leagues":[]}}'),
                ]
                with patch.object(yahoo, "urlopen", side_effect=replies) as requests:
                    handler._handle_yahoo_leagues()

                response, status = _response(handler)
                self.assertEqual((status, response["leagues"]), (200, []))
                refreshed_saved = handler._yahoo_save.call_args.args[0]
                self.assertEqual(refreshed_saved["token"]["refresh_token"], rotated or "test-refresh")
                self.assertEqual(refreshed_saved["token"]["access_token"], "replacement-access")
                refresh_request = requests.call_args_list[0].args[0]
                self.assertEqual(parse_qs(refresh_request.data.decode()), {
                    "grant_type": ["refresh_token"], "redirect_uri": ["https://localhost/"],
                    "refresh_token": ["test-refresh"],
                })
                self.assertEqual(requests.call_args_list[1].args[0].get_header("Authorization"),
                                 "Bearer replacement-access")

    def test_missing_or_unrefreshable_token_requires_authorization_before_api_call(self):
        expired = _saved_connection()
        expired["token"].update(obtained_at=0)
        expired["token"].pop("refresh_token")
        for saved in ({}, expired):
            with self.subTest(has_token=bool(saved.get("token"))):
                handler = _handler(saved)
                with patch.object(yahoo, "urlopen") as request:
                    handler._handle_yahoo_leagues()
                response, status = _response(handler)
                self.assertEqual(status, 401)
                self.assertEqual(response["code"], "yahoo_auth_required")
                request.assert_not_called()
                handler._yahoo_save.assert_not_called()

    def test_saved_connection_distinguishes_auth_failure_from_permission_failure(self):
        for provider_status, expected_code in ((401, "yahoo_auth_required"),
                                               (403, "yahoo_access_denied")):
            with self.subTest(provider_status=provider_status):
                handler = _handler(_saved_connection())
                error = HTTPError(yahoo.API_BASE, provider_status, "Denied", {},
                                  io.BytesIO(b'{"description":"sensitive-provider-detail"}'))
                with patch.object(yahoo, "urlopen", side_effect=error):
                    handler._handle_yahoo_leagues()
                response, status = _response(handler)
                self.assertEqual(status, provider_status)
                self.assertEqual(response["code"], expected_code)
                self.assertNotIn("needsApproval", response)
                self.assertNotIn("sensitive-provider-detail", json.dumps(response))
                handler._yahoo_save.assert_not_called()

    def test_permission_marker_survives_long_body_or_authenticate_header(self):
        long_body = (b'{"description":"' + b'x' * 1200
                     + b' oauth_problem=additional_authorization_required sensitive-provider-detail"}')
        header = Message()
        header["WWW-Authenticate"] = 'OAuth oauth_problem="additional_authorization_required"'
        for body, headers in ((long_body, {}), (b'x' * 12000, header)):
            with self.subTest(marker_in_header=bool(headers)):
                handler = _handler(_saved_connection())
                error = HTTPError(yahoo.API_BASE, 401, "Unauthorized", headers, io.BytesIO(body))
                with patch.object(yahoo, "urlopen", side_effect=error):
                    handler._handle_yahoo_leagues()
                response, status = _response(handler)
                self.assertEqual(status, 403)
                self.assertEqual(response["code"], "yahoo_additional_authorization_required")
                self.assertTrue(response["needsApproval"])
                self.assertEqual(response["approvalUrl"], yahoo.APPROVAL_URL)
                self.assertNotIn("sensitive-provider-detail", json.dumps(response))
                handler._yahoo_save.assert_not_called()


if __name__ == "__main__":
    unittest.main()
