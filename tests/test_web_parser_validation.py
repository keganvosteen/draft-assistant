"""Pasted input validation returns actionable HTTP errors before expensive work."""
import json
from unittest.mock import patch

from draft_assistant.input_limits import (
    MAX_DRAFT_CANDIDATES, MAX_PASTED_LINE_CHARS, MAX_PASTED_LINES,
    MAX_PASTED_TEXT_CHARS,
)
from draft_assistant.models import Player
from draft_assistant.web.server import MAX_PICKS, MAX_TEAMS
from tests.test_web_server import _ServerFixture


class TestParserAPIValidation(_ServerFixture):
    candidate = {"id": "sleeper:1", "name": "Bijan Robinson", "pos": "RB", "team": "ATL"}

    def draft_request(self, **extra):
        body = {"text": "Bijan Robinson", "players": [self.candidate], **extra}
        status, raw = self.request("POST", "/api/parse-draft-text", body)
        return status, json.loads(raw)

    def test_valid_draft_text_preserves_pick_and_match(self):
        status, body = self.draft_request(text="Pick 5: Bijan Robinson", numTeams="12", startPick=5)
        self.assertEqual(status, 200, body)
        self.assertEqual(body["items"][0]["matchedPlayerId"], "sleeper:1")
        self.assertEqual(body["items"][0]["pickNum"], 5)

    def test_invalid_text_type_size_or_line_count_is_400_for_both_endpoints(self):
        for endpoint in ("/api/parse-draft-text", "/api/yahoo/parse-settings"):
            for text in (None, [], {}, 42, True, "", " " * (MAX_PASTED_TEXT_CHARS + 1),
                         "x" * (MAX_PASTED_LINE_CHARS + 1), "x\n" * (MAX_PASTED_LINES + 1)):
                with self.subTest(endpoint=endpoint, type=type(text)):
                    with patch("draft_assistant.web.server._load_players") as load:
                        status, raw = self.request("POST", endpoint, {"text": text})
                    self.assertEqual(status, 400, raw)
                    self.assertIn("error", json.loads(raw))
                    load.assert_not_called()

    def test_invalid_candidate_shapes_are_400(self):
        candidates = (
            None, {}, "players", ["bad"], [None], [{}],
            [{**self.candidate, "name": 3}], [{**self.candidate, "name": "x" * 257}],
            [{**self.candidate, "name": "   "}], [{**self.candidate, "id": []}],
            [{**self.candidate, "id": "x" * 257}], [{**self.candidate, "pos": {}}],
            [{**self.candidate, "pos": ""}], [{**self.candidate, "position": []}],
            [{**self.candidate, "team": ["ATL"]}], [{**self.candidate, "team": "x" * 33}],
        )
        with patch("draft_assistant.draft_paste_parser.parse_draft_text") as parse:
            for players in candidates:
                with self.subTest(players=players):
                    status, body = self.draft_request(players=players)
                    self.assertEqual(status, 400, body)
            parse.assert_not_called()

    def test_candidate_count_bound_is_400_before_matching(self):
        with patch("draft_assistant.draft_paste_parser.parse_draft_text") as parse:
            status, body = self.draft_request(players=[self.candidate] * (MAX_DRAFT_CANDIDATES + 1))
        self.assertEqual(status, 400, body)
        parse.assert_not_called()

    def test_empty_explicit_candidates_do_not_load_unrequested_players(self):
        with patch("draft_assistant.web.server._load_players") as load:
            status, body = self.draft_request(players=[])
        self.assertEqual(status, 200, body)
        self.assertIsNone(body["items"][0]["matchedPlayerId"])
        load.assert_not_called()

    def test_omitted_candidates_load_board(self):
        with patch("draft_assistant.web.server._load_players", return_value=(
            [Player("sleeper:1", "Bijan Robinson", "RB", team="ATL")], None,
        )):
            status, raw = self.request("POST", "/api/parse-draft-text", {"text": "Bijan Robinson"})
        self.assertEqual(status, 200, raw)
        self.assertEqual(json.loads(raw)["items"][0]["matchedPlayerId"], "sleeper:1")

    def test_invalid_numeric_options_and_explicit_picks_are_400(self):
        for field, values in (
            ("numTeams", (None, True, 1, MAX_TEAMS + 1, 2.5, [], "no")),
            ("startPick", (None, False, 0, MAX_PICKS + 1, 1.5, {}, "no")),
        ):
            for value in values:
                with self.subTest(field=field, value=value):
                    status, body = self.draft_request(**{field: value})
                    self.assertEqual(status, 400, body)
        for text in (f"Pick {MAX_PICKS + 1}: Bijan Robinson", "Pick 0: Bijan Robinson"):
            status, body = self.draft_request(text=text)
            self.assertEqual(status, 400, body)
        status, body = self.draft_request(text="Bijan Robinson\nBijan Robinson", startPick=MAX_PICKS)
        self.assertEqual(status, 400, body)

    def test_yahoo_numeric_configuration_bounds_are_400(self):
        for extra in ("Max Teams: 1000", "Max Teams: 0", "Bench: 1000",
                      "Bench: 30\nQuarterback: 30", "Passing Touchdowns: 999999"):
            with self.subTest(extra=extra):
                status, raw = self.request("POST", "/api/yahoo/parse-settings", {
                    "text": "League Name: Test League\n" + extra,
                })
                self.assertEqual(status, 400, raw)

    def test_valid_yahoo_settings_remain_200(self):
        status, raw = self.request("POST", "/api/yahoo/parse-settings", {"text": (
            "League Name: Test League\nMax Teams: 12\nReceptions: .25\n"
            "Roster Positions: QB, RB, WR, TE, W/R/T, K, DEF, BN, IR\n"
        )})
        self.assertEqual(status, 200, raw)
        parsed = json.loads(raw)
        self.assertEqual(parsed["numTeams"], 12)
        self.assertEqual(parsed["scoring"]["rec"], .25)
