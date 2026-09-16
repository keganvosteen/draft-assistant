"""Current ownership must survive draft history, reserve slots and data refreshes."""
import copy
import unittest
from unittest.mock import Mock, patch

from draft_assistant.importers.free_sources import _parse_espn_rosters
from draft_assistant.importers.sleeper import _parse_rosters
from draft_assistant.importers.yahoo import _parse_roster_players
from draft_assistant.models import Player
from draft_assistant.platform_sync import (
    SyncedRosterPlayer, SyncedRosterTeam, resolve_roster_entries,
    synced_rosters_to_picks,
)
from draft_assistant.web.server import DraftAPIHandler


class TestCurrentRosterSync(unittest.TestCase):
    def test_yahoo_sync_uses_current_adds_drops_and_trades_despite_draft_history(self):
        # The old draft has a released player and puts the traded player on
        # the first team. Neither describes ownership after transactions.
        players = [Player(id=name, name=name, position="RB")
                   for name in ("Released Player", "Traded Player", "MarShawn Lloyd")]
        current = [
            SyncedRosterTeam("Alpha", [
                SyncedRosterPlayer("MarShawn Lloyd", "RB", provider_id="yahoo:3"),
                SyncedRosterPlayer("Deep Rookie", "RB", provider_id="yahoo:4"),
            ], provider_id="t.1"),
            SyncedRosterTeam("Bravo", [
                SyncedRosterPlayer("Traded Player", "RB", provider_id="yahoo:2"),
            ], provider_id="t.2"),
        ]
        handler = DraftAPIHandler.__new__(DraftAPIHandler)
        handler.profile = None
        handler._read_body = Mock(return_value={"league": {
            "id": "league", "platform": "Yahoo", "yahooLeagueKey": "nfl.l.123",
            "teamIds": ["t.1", "t.2"],
        }})
        handler._yahoo_access_token = Mock(return_value="test-token")
        handler._send_json = Mock()
        handler._send_platform_error = Mock()
        with patch("draft_assistant.web.server._load_players", return_value=(players, None)), \
             patch("draft_assistant.importers.yahoo.fetch_league_rosters", return_value=current) as roster_fetch, \
             patch("draft_assistant.importers.yahoo.fetch_draft_picks", return_value=["old draft"]) as draft_fetch:
            handler._handle_sync_league()
        handler._send_platform_error.assert_not_called()
        roster_fetch.assert_called_once_with("test-token", "nfl.l.123")
        draft_fetch.assert_not_called()
        result = handler._send_json.call_args.args[0]
        ownership = {row["playerId"]: row["teamNum"] for row in result["picks"]}
        self.assertEqual(ownership, {"MarShawn Lloyd": 1, "yahoo:4": 1, "Traded Player": 2})
        self.assertEqual(result["rostered"], 3)
        self.assertEqual(result["matched"], 2)

    def test_espn_keeps_starters_bench_ir_and_players_without_projection_positions(self):
        entries = []
        for player_id, name, position, slot in (
            (1, "Starter", 1, 0), (2, "Bench Player", 3, 20),
            (3, "MarShawn Lloyd", 2, 21), (4, "Defender", 8, 20),
        ):
            entries.append({"lineupSlotId": slot, "playerPoolEntry": {"player": {
                "id": player_id, "fullName": name, "defaultPositionId": position,
            }}})
        teams = _parse_espn_rosters({"teams": [
            {"id": 1, "name": "Team", "roster": {"entries": entries}},
            {"id": 2, "name": "Opponent", "roster": {"entries": [
                {"lineupSlotId": 21, "playerPoolEntry": {"player": {"id": 5}}},
            ]}},
        ]})
        self.assertEqual([p.provider_id for t in teams for p in t.players],
                         [f"espn:{i}" for i in range(1, 6)])
        result = synced_rosters_to_picks(teams, [], {"teamIds": ["1", "2"]})
        self.assertEqual(len(result["picks"]), 5)
        self.assertEqual(result["picks"][2]["sourceName"], "MarShawn Lloyd")
        self.assertEqual(result["picks"][4]["teamNum"], 2)

    def test_yahoo_keeps_every_selected_slot_and_id_only_rows(self):
        raw = {"players": {str(i): {"player": [
            [{"player_id": str(i)}, {"name": {"full": f"Player {i}"}},
             {"display_position": "RB"}],
            {"selected_position": [{"position": slot}]},
        ]} for i, slot in enumerate(("RB", "BN", "IR", "IR+"), 1)}}
        raw["players"]["5"] = {"player": [[{"player_id": "5"}]]}
        players = _parse_roster_players(raw, "nfl.l.123")
        self.assertEqual([p.provider_id for p in players], [f"yahoo:{i}" for i in range(1, 6)])
        self.assertEqual([p.position for p in players[:4]], ["RB"] * 4)

    def test_sleeper_keeps_reserve_taxi_and_main_roster_without_double_counting(self):
        teams = _parse_rosters([], [{
            "roster_id": 1, "players": ["starter", "bench", "ir"],
            "starters": ["starter"], "reserve": ["ir", "ir-only"],
            "taxi": ["taxi-only"],
        }], None)
        self.assertEqual([p.provider_id for p in teams[0].players],
                         [f"sleeper:{i}" for i in ("starter", "bench", "ir", "ir-only", "taxi-only")])


class TestRosterIdentity(unittest.TestCase):
    def test_unknown_player_is_preserved_then_resolved_after_projection_refresh(self):
        synced = synced_rosters_to_picks([
            SyncedRosterTeam("Opponent", [SyncedRosterPlayer(
                "MarShawn Lloyd", "RB", "GB", "espn:42")], provider_id="7"),
        ], [], {"teamIds": ["7"]})
        entry = synced["picks"][0]
        self.assertTrue(entry["unmatched"])
        self.assertEqual(entry["playerId"], "espn:42")
        self.assertEqual(entry["providerTeamId"], "7")
        board = [Player(id="gsis:lloyd", name="MarShawn Lloyd", position="RB",
                        metadata={"espn_id": 42})]
        resolved = resolve_roster_entries(synced["picks"], board)
        self.assertEqual(resolved[0]["playerId"], "gsis:lloyd")
        self.assertNotIn("unmatched", resolved[0])
        self.assertEqual(resolved[0]["providerPlayerId"], "espn:42")
        self.assertTrue(entry["unmatched"], "Resolving must not mutate the stored snapshot")

    def test_projection_identity_change_can_resolve_by_source_name(self):
        original = [Player(id="old:lloyd", name="MarShawn Lloyd", position="RB")]
        entries = synced_rosters_to_picks([SyncedRosterTeam("Opponent", [
            SyncedRosterPlayer("Marshawn Lloyd", "RB", "GB", "yahoo:42"),
        ])], original, {})["picks"]
        current = [Player(id="gsis:lloyd", name="MarShawn Lloyd", position="RB")]
        self.assertEqual(resolve_roster_entries(entries, current)[0]["playerId"], "gsis:lloyd")

    def test_distinct_provider_players_with_same_name_match_are_preserved(self):
        result = synced_rosters_to_picks([SyncedRosterTeam("Team", [
            SyncedRosterPlayer("Marvin Harrison", "WR", provider_id="espn:1"),
            SyncedRosterPlayer("Marvin Harrison Jr.", "WR", provider_id="espn:2"),
        ])], [Player(id="harrison", name="Marvin Harrison", position="WR")], {})
        self.assertEqual(len(result["picks"]), 2)
        self.assertEqual(result["matched"], 1)
        self.assertEqual(result["picks"][1]["playerId"], "espn:2")
        self.assertTrue(result["picks"][1]["unmatched"])

    def test_old_strings_and_display_keys_resolve_without_mutation(self):
        rows = ["Josh Allen|QB", {"playerId": "Josh Allen|QB", "teamNum": 2}]
        original = copy.deepcopy(rows)
        board = [Player(id="gsis:allen", name="Josh Allen", position="QB")]
        result = resolve_roster_entries(rows, board)
        self.assertEqual([r["playerId"] for r in result], ["gsis:allen"] * 2)
        self.assertEqual(result[1]["teamNum"], 2)
        self.assertEqual(rows, original)


if __name__ == "__main__":
    unittest.main()
