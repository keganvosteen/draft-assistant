"""Provider and HTTP regressions for league access, seating, and draft history."""
import json
import unittest
from copy import deepcopy
from urllib.error import HTTPError
from unittest.mock import patch

from draft_assistant.importers import free_sources as espn, sleeper
from draft_assistant.models import Player
from draft_assistant.platform_sync import SyncedDraftPick, SyncedRosterPlayer, SyncedRosterTeam, synced_draft_to_picks, synced_rosters_to_picks
from tests.test_web_server import _ServerFixture


def espn_data():
    return {
        "seasonId": 2026,
        "settings": {"name": "Test league", "size": 2,
                     "draftSettings": {"type": "SNAKE", "pickOrder": [9, 3]},
                     "rosterSettings": {"lineupSlotCounts": {"0": 1, "20": 2}},
                     "scoringSettings": {"scoringItems": [{"statId": 53, "points": 0.5}]}},
        "teams": [{"id": 3, "name": "Same name"}, {"id": 9, "name": "Same name"}],
        "draftDetail": {"drafted": True, "picks": [
            {"overallPickNumber": 1, "roundId": 1, "roundPickNumber": 1, "teamId": 3, "playerId": 42},
            {"overallPickNumber": 2, "roundId": 1, "roundPickNumber": 2, "teamId": 9, "playerId": 43},
        ]},
    }


class TestEspnLeagueImport(unittest.TestCase):
    def test_private_import_and_real_order_survive_duplicate_names(self):
        with patch.object(espn, "_fetch_json", return_value=espn_data()) as fetch:
            info = espn.fetch_espn_league(2026, "123", espn_s2="session", swid="{owner}")
        self.assertEqual(info["teamIds"], ["9", "3"])
        self.assertTrue(info["draftOrderReady"])
        self.assertEqual(info["scoring"]["rec"], 0.5)
        self.assertEqual(fetch.call_args.kwargs["extra_headers"]["Cookie"], "espn_s2=session; SWID={owner}")
        self.assertNotIn("espnS2", info)

    def test_missing_order_is_marked_unknown_without_guessing_team_ids(self):
        data = espn_data()
        data["settings"]["draftSettings"].pop("pickOrder")
        info = espn._parse_espn_league(data, "123")
        self.assertFalse(info["draftOrderReady"])
        self.assertEqual(info["teamIds"], ["3", "9"])

    def test_dropped_drafted_players_resolve_through_one_filtered_lookup(self):
        cards = {"players": [
            {"player": {"id": 42, "fullName": "A Runner", "defaultPositionId": 2}},
            {"player": {"id": 43, "fullName": "A Receiver", "defaultPositionId": 3}},
        ]}
        with patch.object(espn, "_fetch_json", side_effect=[espn_data(), cards]) as fetch:
            info = espn.fetch_espn_draft(2026, "123")
        self.assertEqual(fetch.call_count, 2)
        self.assertEqual(info["draftPicks"][0].player.name, "A Runner")
        self.assertEqual(info["draftPicks"][0].team_num, 2)
        self.assertEqual(info["draftPicks"][0].provider_team_id, "3")
        self.assertFalse(info["liveAvailable"])

    def test_cookie_header_rejects_multiple_cookie_values(self):
        for value in ("s2; unauthorized=1", "s2\r\nOther: 1"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                espn._espn_cookie_headers(value, "")


class TestDraftIdentity(unittest.TestCase):
    def test_traded_sleeper_pick_belongs_to_roster_owner(self):
        draft = {"slot_to_roster_id": {"1": 9, "2": 3}}
        picks = sleeper._parse_draft_picks([
            {"pick_no": 1, "draft_slot": 1, "roster_id": 3, "player_id": "42", "metadata": {}}
        ], draft)
        self.assertEqual(picks[0].team_num, 2)

    def test_poll_refreshes_seats_by_id_without_swapping_names(self):
        draft = {"draft_id": "1", "type": "snake", "slot_to_roster_id": {"1": 3, "2": 9}}
        info = sleeper.draft_order_patch(draft, {"numTeams": 2, "teamIds": ["9", "3"], "teamNames": ["A", "B"]})
        self.assertEqual(info["teamIds"], ["3", "9"])
        self.assertEqual(info["teamNames"], ["B", "A"])
        self.assertTrue(info["draftOrderReady"])
        draft["settings"] = {"reversal_round": 3}
        self.assertEqual(sleeper.draft_order_patch(draft, {"numTeams": 2})["draftType"], "third_round_reversal")

    def test_partial_history_and_duplicate_numbers_do_not_shift_the_clock(self):
        for numbers in ([2], [1, 3], [1, 1]):
            with self.subTest(numbers=numbers), self.assertRaises(ValueError):
                synced_draft_to_picks([SyncedDraftPick(n, 1, SyncedRosterPlayer("Unknown", "WR")) for n in numbers], [], {"numTeams": 2})

    def test_duplicate_player_placeholder_cannot_claim_a_real_player_twice(self):
        player = Player(id="A|WR", name="A", position="WR")
        rows = [SyncedDraftPick(n, n, SyncedRosterPlayer("A", "WR")) for n in (1, 2)]
        result = synced_draft_to_picks(rows, [player], {"numTeams": 2})
        self.assertNotEqual(result["picks"][0]["playerId"], result["picks"][1]["playerId"])
        self.assertEqual(result["matched"], 1)

    def test_roster_mapping_uses_ids_even_when_names_are_identical(self):
        rosters = [SyncedRosterTeam("Same", [], "9"), SyncedRosterTeam("Same", [], "3")]
        result = synced_rosters_to_picks(rosters, [], {"teamIds": ["3", "9"], "teamNames": ["Same", "Same"]})
        self.assertEqual([team["teamNum"] for team in result["teams"]], [2, 1])


class TestLeagueSyncApi(_ServerFixture):
    def test_two_imports_keep_access_and_leagues_separate(self):
        info = espn._parse_espn_league(espn_data(), "123")
        with patch.object(espn, "fetch_espn_league", return_value=info) as fetch:
            status, raw = self.request("POST", "/api/import-espn", {
                "leagueId": "https://fantasy.espn.com/football/league?leagueId=123", "season": 2026,
                "espnS2": "first-secret", "swid": "first-owner"})
            self.assertEqual(status, 200)
            self.assertNotIn(b"first-secret", raw)
            self.assertEqual(json.loads(raw)["scoringType"], "half-ppr")
            status, raw = self.request("POST", "/api/import-espn", {"leagueId": "456", "season": 2026})
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(raw)["espnLeagueId"], "456")
            self.assertIsNone(fetch.call_args.kwargs["espn_s2"])
            self.assertIsNone(fetch.call_args.kwargs["swid"])

    def test_401_explains_how_to_authenticate_without_echoing_exception(self):
        with patch.object(espn, "fetch_espn_league", side_effect=HTTPError("url", 401, "secret", {}, None)):
            status, raw = self.request("POST", "/api/import-espn", {"leagueId": "123"})
        self.assertEqual(status, 401)
        data = json.loads(raw)
        self.assertEqual(data["code"], "espn_auth_required")
        self.assertIn("SWID", data["error"])
        self.assertNotIn(b"secret", raw)

    def test_refresh_preserves_selected_team_by_id_after_order_changes(self):
        info = espn._parse_espn_league(espn_data(), "123")
        league = {"espnLeagueId": "123", "season": 2026, "teamIds": ["3", "9"],
                  "teamNames": ["Same name", "Same name"], "draftPosition": 1}
        before = deepcopy(league)
        with patch.object(espn, "fetch_espn_league", return_value=info):
            status, raw = self.request("POST", "/api/league-settings", {"league": league})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(raw)["draftPosition"], 2)
        self.assertEqual(league, before)

    def test_unpublished_espn_feed_never_returns_empty_replacement_picks(self):
        with patch.object(espn, "fetch_espn_draft", return_value={"status": "drafting", "draftPicks": []}):
            status, raw = self.request("POST", "/api/draft-sync", {"league": {"espnLeagueId": "123"}})
        self.assertEqual(status, 409)
        self.assertEqual(json.loads(raw)["code"], "espn_live_unavailable")
        self.assertNotIn("picks", json.loads(raw))

    def test_completed_espn_sync_maps_real_picks_and_selected_team(self):
        info = {**espn._espn_draft_settings(espn_data()), "status": "complete",
                "draftPicks": [SyncedDraftPick(1, 2, SyncedRosterPlayer("A", "WR"), "3")]}
        league = {"id": "league-two", "espnLeagueId": "123", "teamIds": ["3", "9"], "draftPosition": 1}
        with patch.object(espn, "fetch_espn_draft", return_value=info), patch(
            "draft_assistant.web.server._load_players", return_value=([Player(id="a", name="A", position="WR")], None)):
            status, raw = self.request("POST", "/api/draft-sync", {"league": league})
        self.assertEqual(status, 200)
        result = json.loads(raw)
        self.assertEqual(result["leagueId"], "league-two")
        self.assertEqual(result["picks"][0]["teamNum"], 2)
        self.assertEqual(result["leaguePatch"]["draftPosition"], 2)
        self.assertFalse(result["liveAvailable"])
        self.assertTrue(result["leaguePatch"]["draftHasTradedPicks"])

    def test_sleeper_polls_with_current_seats(self):
        league = {"id": "s", "sleeperDraftId": "draft", "teamIds": ["3", "9"],
                  "teamNames": ["A", "B"], "numTeams": 2, "draftPosition": 1}
        draft = {"draft_id": "draft", "type": "snake", "status": "drafting", "slot_to_roster_id": {"1": 9, "2": 3}}
        rows = [SyncedDraftPick(1, 2, SyncedRosterPlayer("A", "WR"), "3")]
        with patch.object(sleeper, "fetch_draft", return_value=draft), patch.object(sleeper, "fetch_draft_picks", return_value=rows), patch(
            "draft_assistant.web.server._load_players", return_value=([], None)):
            status, raw = self.request("POST", "/api/draft-sync", {"league": league})
        self.assertEqual(status, 200)
        result = json.loads(raw)
        self.assertTrue(result["liveAvailable"])
        self.assertEqual(result["leaguePatch"]["draftPosition"], 2)

    def test_invalid_inputs_are_client_errors(self):
        for path, body in (("/api/league-settings", {"league": []}), ("/api/draft-sync", {"league": "bad"}),
                           ("/api/import-espn", {"leagueId": "https://other.test/1"}),
                           ("/api/import-espn", {"leagueId": "123", "season": "bad"})):
            with self.subTest(path=path):
                status, _ = self.request("POST", path, body)
                self.assertEqual(status, 400)


if __name__ == "__main__":
    unittest.main()


class TestEspnCookieNormalization(unittest.TestCase):
    """Users paste cookies straight out of DevTools — with quotes, braces
    missing, name= prefixes, or the URL-decoded espn_s2 some guides show.
    All of those used to 401 silently; they must normalize instead."""

    def _cookie(self, s2=None, swid=None):
        return espn._espn_cookie_headers(s2, swid).get("Cookie", "")

    def test_devtools_quotes_are_stripped(self):
        self.assertEqual(
            self._cookie('"AEAw%2Fabc"', '"{C904188A-BE28}"'),
            "espn_s2=AEAw%2Fabc; SWID={C904188A-BE28}",
        )

    def test_copied_name_prefix_is_stripped(self):
        self.assertEqual(self._cookie("espn_s2=AEAwabc"), "espn_s2=AEAwabc")
        self.assertEqual(self._cookie(None, "SWID={ABC-123}"), "SWID={ABC-123}")

    def test_swid_gains_missing_braces(self):
        self.assertEqual(self._cookie(None, "C904188A-BE28"), "SWID={C904188A-BE28}")
        # Already-braced values pass through verbatim (case untouched).
        self.assertEqual(self._cookie(None, "{c904188a-be28}"), "SWID={c904188a-be28}")

    def test_decoded_espn_s2_is_reencoded(self):
        self.assertEqual(self._cookie("AEAw/ab+c="), "espn_s2=AEAw%2Fab%2Bc%3D")

    def test_encoded_espn_s2_is_left_alone(self):
        raw = "AEAwzmwW8Qgm%2F6e0aGK%2BB3W0%3D"
        self.assertEqual(self._cookie(raw), f"espn_s2={raw}")

    def test_clean_values_are_unchanged(self):
        self.assertEqual(self._cookie("session", "{owner}"),
                         "espn_s2=session; SWID={owner}")

    def test_devtools_colon_row_is_stripped(self):
        # Chrome's Application panel shows a cookie as name:"value". Pasting
        # that whole row sent the literal text 'espn_s2:"AEAw…' as the cookie
        # value, so ESPN 401'd and the league silently stayed on form defaults.
        self.assertEqual(
            self._cookie('espn_s2:"AEAw%2Fabc"', 'SWID:"{C904188A-BE28}"'),
            "espn_s2=AEAw%2Fabc; SWID={C904188A-BE28}",
        )

    def test_colon_row_with_space_after_the_name(self):
        self.assertEqual(
            self._cookie('espn_s2: "AEAw%2Fabc"', 'SWID: {C904188A-BE28}'),
            "espn_s2=AEAw%2Fabc; SWID={C904188A-BE28}",
        )

    def test_quotes_wrapping_the_whole_pair(self):
        self.assertEqual(self._cookie('"espn_s2=AEAwabc"'), "espn_s2=AEAwabc")

    def test_injection_still_rejected_after_cleaning(self):
        with self.assertRaises(ValueError):
            self._cookie('"s2; unauthorized=1"')
        with self.assertRaises(ValueError):
            self._cookie('espn_s2:"s2; unauthorized=1"')
