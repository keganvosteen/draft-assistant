"""Waiver availability follows current ownership, independently of draft history."""
import copy
import json
from unittest.mock import patch

from draft_assistant.models import LeagueConfig, Player, PlayerContext
from draft_assistant.platform_sync import SyncedRosterPlayer, SyncedRosterTeam
from tests.test_web_server import _ServerFixture


class TestWaiverRosterSync(_ServerFixture):
    def setUp(self):
        self.players = [
            Player("board:lloyd", "MarShawn Lloyd", "RB", projections={"rush_yd": 120},
                   metadata={"espn_id": "101"}),
            Player("board:dropped", "Dropped Runner", "RB", projections={"rush_yd": 110}),
            Player("board:traded", "Traded Runner", "RB", projections={"rush_yd": 90}),
            Player("board:mine", "My Runner", "RB", projections={"rush_yd": 50}),
        ]
        self.config = LeagueConfig(2, {"RB": 1, "BN": 4}, {"rush_yd": 1}, {})
        self.league = {
            "id": "league-a", "name": "Test league", "platform": "ESPN",
            "espnLeagueId": "123", "season": 2026, "numTeams": 2,
            "draftPosition": 1, "teamIds": ["1", "2"], "teamNames": ["Mine", "Theirs"],
        }
        self.draft = [
            {"playerId": "board:dropped", "teamNum": 1},
            {"playerId": "board:traded", "teamNum": 1},
        ]
        self.roster = [
            {"playerId": "board:mine", "teamNum": 1},
            {"playerId": "board:traded", "teamNum": 2},
            {"playerId": "board:lloyd", "teamNum": 2},
        ]
        self.loader = patch("draft_assistant.web.server._load_players",
                            return_value=(self.players, self.config))
        self.context = patch("draft_assistant.web.server.load_context",
                             return_value=PlayerContext(2026, 1))
        self.loader.start()
        self.context.start()
        self.addCleanup(self.loader.stop)
        self.addCleanup(self.context.stop)

    def scan(self, **extra):
        body = {"leagues": [self.league], "picks": {self.league["id"]: self.draft},
                "week": 1, "top": 30, **extra}
        status, raw = self.request("POST", "/api/free-agents", body)
        return status, json.loads(raw)

    def test_sync_excludes_undrafted_bench_ir_and_traded_players_but_frees_drops(self):
        before = copy.deepcopy(self.draft)
        rosters = [
            SyncedRosterTeam("Mine", [SyncedRosterPlayer("My Runner", "RB")], "1"),
            SyncedRosterTeam("Theirs", [
                SyncedRosterPlayer("MarShawn Lloyd", "RB", provider_id="espn:101"),
                SyncedRosterPlayer("Traded Runner", "RB"),
            ], "2"),
        ]
        with patch("draft_assistant.importers.free_sources.fetch_espn_rosters", return_value=rosters), \
                patch("draft_assistant.web.server.DraftAPIHandler._espn_access", return_value=(None, None)):
            status, raw = self.request("POST", "/api/sync-league", {"league": self.league})
        self.assertEqual(status, 200, raw)
        synced = json.loads(raw)
        status, result = self.scan(rosters={self.league["id"]: synced["picks"]})
        self.assertEqual(status, 200, result)
        row = result["leagues"][0]
        self.assertEqual(row["rostered"], 1)  # the traded player is no longer mine
        self.assertEqual(row["leagueRostered"], 3)
        self.assertEqual(row["available"], 1)
        for horizon in ("weeklyRecommendations", "rosRecommendations"):
            self.assertEqual([p["id"] for p in row[horizon]], ["board:dropped"])
        self.assertEqual(self.draft, before)

    def test_linked_league_cannot_scan_using_only_draft_picks(self):
        status, result = self.scan()
        self.assertEqual(status, 400)
        self.assertIn("Sync current rosters", result["error"])

    def test_saved_roster_snapshot_survives_reload_and_explicit_refresh_replaces_it(self):
        self.league["rosterSnapshot"] = {"picks": self.roster, "syncedAt": "2026-09-15"}
        status, result = self.scan()
        self.assertEqual(status, 200, result)
        self.assertEqual(result["leagues"][0]["available"], 1)
        # Empty is an authoritative roster too; never resurrect the saved snapshot.
        status, result = self.scan(rosters={self.league["id"]: []})
        self.assertEqual(status, 200, result)
        self.assertEqual(result["leagues"][0]["available"], 4)

    def test_unmatched_provider_identity_is_resolved_after_projection_refresh(self):
        entries = [{"playerId": "espn:101", "providerPlayerId": "espn:101",
                    "sourceName": "Old spelling", "sourcePosition": "RB",
                    "teamNum": 2, "unmatched": True}]
        status, result = self.scan(rosters={self.league["id"]: entries})
        self.assertEqual(status, 200, result)
        row = result["leagues"][0]
        self.assertEqual(row["available"], 3)
        self.assertEqual(row["rosterEntries"][0]["playerId"], "board:lloyd")
        self.assertNotIn("board:lloyd", [p["id"] for p in row["rosRecommendations"]])

    def test_rosters_are_scoped_to_their_league(self):
        other = {**self.league, "id": "league-b", "espnLeagueId": "456"}
        status, raw = self.request("POST", "/api/free-agents", {
            "leagues": [self.league, other], "week": 1,
            "rosters": {"league-a": self.roster, "league-b": []},
        })
        self.assertEqual(status, 200, raw)
        rows = json.loads(raw)["leagues"]
        self.assertEqual([row["available"] for row in rows], [1, 4])

    def test_manual_league_can_still_use_recorded_ownership(self):
        self.league.pop("espnLeagueId")
        status, result = self.scan()
        self.assertEqual(status, 200, result)
        self.assertEqual(result["leagues"][0]["available"], 2)

    def test_invalid_roster_payload_is_not_treated_as_an_empty_roster(self):
        for rosters in ([], {"league-a": None}, {"league-a": {}}):
            with self.subTest(rosters=rosters):
                status, _ = self.scan(rosters=rosters)
                self.assertEqual(status, 400)
