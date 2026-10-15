import unittest

from draft_assistant.draft import DraftTracker
from draft_assistant.identity import player_indexes
from draft_assistant.importers.free_sources import _merge_many, merge_historical_into
from draft_assistant.models import DraftState, LeagueConfig, Player
from draft_assistant.platform_sync import (
    SyncedDraftPick, SyncedRosterPlayer, SyncedRosterTeam, resolve_roster_entries,
    synced_draft_to_picks, synced_rosters_to_picks,
)
from draft_assistant.web.server import _player_to_js


class TestProviderIdentity(unittest.TestCase):
    def setUp(self):
        self.config = LeagueConfig(2, {"WR": 1}, {"rec_yd": .1}, {})

    def player(self, provider):
        return Player(f"{provider}:77" if provider == "ffc" else "sleeper:11",
                      "Example Receiver", "WR", projections={"rec_yd": 100},
                      metadata={"ffc_player_id": 77} if provider == "ffc" else {"sleeper_id": "11"})

    def test_refresh_failure_and_recovery_preserve_pick_and_provider_aliases(self):
        for old_source, new_source in (("ffc", "sleeper"), ("sleeper", "ffc")):
            with self.subTest(old_source=old_source):
                old = self.player(old_source)
                new = self.player(new_source)
                players = merge_historical_into([new], [old])
                self.assertEqual(new.key(), old.key())
                tracker = DraftTracker(self.config, DraftState("Me", [], [old.key()], [old.key()]), players)
                self.assertEqual(tracker.available_players(), [])
                self.assertEqual(tracker.drafted_players(), [new])
                rows = resolve_roster_entries([{"playerId": self.player(new_source).key(), "teamNum": 2}], players)
                self.assertEqual(rows[0]["playerId"], old.key())
                self.assertEqual(rows[0]["teamNum"], 2)
                self.assertIn(self.player(new_source).key(), _player_to_js(new, self.config)["aliases"])

    def test_prior_provider_alias_resolves_even_without_saved_board(self):
        pool = {}
        _merge_many(pool, [self.player("sleeper")], "sleeper")
        _merge_many(pool, [self.player("ffc")], "ffc")
        players = list(pool.values())
        self.assertEqual(player_indexes(players)[1]["ffc:77"], "sleeper:11")
        tracker = DraftTracker(self.config, DraftState("Me", [], ["ffc:77"], ["ffc:77"]), players)
        self.assertEqual(tracker.available_players(), [])

    def test_ambiguous_alias_does_not_guess_or_override_canonical_identity(self):
        a = Player("a", "Same Name", "WR", metadata={"identity_aliases": ["old", "b"]})
        b = Player("b", "Same Name", "WR", metadata={"identity_aliases": ["old"]})
        canonical, aliases = player_indexes([a, b])
        self.assertNotIn("old", aliases)
        self.assertNotIn("Same Name|WR", aliases)
        self.assertNotIn("b", aliases)
        self.assertIs(canonical["b"], b)

    def test_refresh_keeps_new_stats_without_copying_old_context(self):
        old = self.player("ffc")
        old.metadata["status"] = "Retired"
        old.historical_stats = {2025: {"rec_yd": 800}}
        new = self.player("sleeper")
        merge_historical_into([new], [old])
        self.assertNotIn("status", new.metadata)
        self.assertEqual(new.projections, {"rec_yd": 100})
        self.assertEqual(new.historical_stats[2025]["rec_yd"], 800)

    def test_ambiguous_provider_alias_does_not_fall_back_to_provider_or_name(self):
        first = Player("a", "First Player", "WR", metadata={"espn_id": 42})
        second = Player("b", "Second Player", "WR", metadata={"espn_id": 42})
        for board in ([first, second], [second, first]):
            for name, position in (("", ""), ("First Player", "WR")):
                with self.subTest(order=board[0].id, name=name):
                    source = SyncedRosterPlayer(name, position, provider_id="espn:42")
                    result = synced_rosters_to_picks([SyncedRosterTeam("Team", [source])], board, {})
                    self.assertEqual(result["matched"], 0)
                    self.assertEqual(result["picks"][0]["playerId"], "espn:42")
                    self.assertTrue(result["picks"][0]["unmatched"])
                    resolved = resolve_roster_entries(result["picks"], board)
                    self.assertEqual(resolved[0]["playerId"], "espn:42")
                    self.assertTrue(resolved[0]["unmatched"])

    def test_ambiguous_display_alias_cannot_be_restored_by_legacy_fallback(self):
        board = [Player("a", "Same Name", "WR"), Player("b", "Same Name", "WR")]
        for players in (board, list(reversed(board))):
            result = resolve_roster_entries([{"playerId": "Same Name|WR", "unmatched": True}], players)
            self.assertEqual(result[0]["playerId"], "Same Name|WR")
            self.assertTrue(result[0]["unmatched"])
            synced = synced_rosters_to_picks([SyncedRosterTeam("Team", [
                SyncedRosterPlayer("Same Name", "WR", provider_id="yahoo:unknown"),
            ])], players, {})
            self.assertEqual(synced["matched"], 0)

    def test_canonical_identity_still_wins_over_a_conflicting_alias(self):
        actual = Player("espn:42", "Correct Player", "WR")
        conflicting = Player("other", "Other Player", "WR", metadata={"espn_id": 42})
        result = resolve_roster_entries([{"playerId": "espn:42"}], [actual, conflicting])
        self.assertEqual(result[0]["playerId"], actual.key())

    def test_unmatched_draft_pick_keeps_identity_for_later_projection_refresh(self):
        source = SyncedRosterPlayer("Old Spelling", "WR", "KC", "espn:42")
        result = synced_draft_to_picks([SyncedDraftPick(1, 2, source, "owner")], [], {"numTeams": 2})
        row = result["picks"][0]
        self.assertEqual(row["playerId"], "espn:42")
        self.assertEqual(row["sourcePosition"], "WR")
        self.assertEqual(row["sourceTeam"], "KC")
        self.assertEqual(row["providerPlayerId"], "espn:42")
        board = [Player("sleeper:11", "New Spelling", "WR", metadata={"espn_id": 42})]
        resolved = resolve_roster_entries([row], board)[0]
        self.assertEqual(resolved["playerId"], "sleeper:11")
        self.assertEqual(resolved["teamNum"], 2)
        self.assertEqual(resolved["providerTeamId"], "owner")
        self.assertNotIn("unmatched", resolved)
