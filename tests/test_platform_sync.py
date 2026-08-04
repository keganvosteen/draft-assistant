import unittest

from draft_assistant.models import Player
from draft_assistant.platform_sync import (
    SyncedDraftPick,
    SyncedRosterPlayer,
    SyncedRosterTeam,
    synced_draft_to_picks,
    synced_rosters_to_picks,
)


def _p(name, pos, team=None, metadata=None):
    return Player(
        id=f"{name}|{pos}",
        name=name,
        position=pos,
        team=team,
        projections={},
        metadata=metadata or {},
    )


class TestSyncedRostersToPicks(unittest.TestCase):
    def test_maps_team_names_to_saved_draft_order(self):
        players = [_p("Josh Allen", "QB"), _p("Bijan Robinson", "RB")]
        rosters = [
            SyncedRosterTeam("Team Bravo", [SyncedRosterPlayer("Bijan Robinson", "RB")]),
            SyncedRosterTeam("Team Alpha", [SyncedRosterPlayer("Josh Allen", "QB")]),
        ]
        league = {"teamNames": ["Team Alpha", "Team Bravo"]}

        result = synced_rosters_to_picks(rosters, players, league)

        by_player = {pick["playerId"]: pick for pick in result["picks"]}
        self.assertEqual(by_player["Josh Allen|QB"]["teamNum"], 1)
        self.assertEqual(by_player["Bijan Robinson|RB"]["teamNum"], 2)

    def test_matches_espn_id_before_name(self):
        wrong_name = _p("John Smith", "WR", metadata={"espn_id": 7})
        local = _p("Different Imported Name", "WR", metadata={"espn_id": 42})
        rosters = [
            SyncedRosterTeam("T1", [
                SyncedRosterPlayer("Name Changed", "WR", provider_id="espn:42")
            ])
        ]

        result = synced_rosters_to_picks(rosters, [wrong_name, local], {})

        self.assertEqual(result["picks"][0]["playerId"], "Different Imported Name|WR")

    def test_dst_matches_by_team_code(self):
        players = [_p("Buffalo Bills", "DST", team="BUF")]
        rosters = [SyncedRosterTeam("T1", [SyncedRosterPlayer("Bills D/ST", "DEF", team="BUF")])]

        result = synced_rosters_to_picks(rosters, players, {})

        self.assertEqual(result["matched"], 1)
        self.assertEqual(result["picks"][0]["playerId"], "Buffalo Bills|DST")

    def test_unmatched_are_reported(self):
        rosters = [SyncedRosterTeam("T1", [SyncedRosterPlayer("Unknown Player", "RB")])]

        result = synced_rosters_to_picks(rosters, [], {})

        self.assertEqual(result["matched"], 0)
        self.assertEqual(result["unmatched"][0]["name"], "Unknown Player")


class TestSyncedDraftToPicks(unittest.TestCase):
    """The live Sleeper feed: pick COUNT drives whose turn it is, so no pick may
    ever be dropped — the UI reads the next pick as ``picks.length + 1``."""

    def _picks(self, *names_positions):
        return [
            SyncedDraftPick(i, i, SyncedRosterPlayer(name, pos))
            for i, (name, pos) in enumerate(names_positions, 1)
        ]

    def test_every_pick_is_returned(self):
        players = [_p("Josh Allen", "QB"), _p("Bijan Robinson", "RB")]
        picks = self._picks(("Josh Allen", "QB"), ("Bijan Robinson", "RB"))

        result = synced_draft_to_picks(picks, players, {"numTeams": 12})

        self.assertEqual(len(result["picks"]), 2)
        self.assertEqual(result["nextPickNum"], 3)

    def test_unmatched_pick_keeps_its_slot(self):
        players = [_p("Josh Allen", "QB")]
        picks = self._picks(("Josh Allen", "QB"), ("Deep Rookie", "WR"))

        result = synced_draft_to_picks(picks, players, {"numTeams": 12})

        self.assertEqual(len(result["picks"]), 2)
        self.assertTrue(result["picks"][1]["unmatched"])
        self.assertEqual(result["picks"][1]["playerId"], "Deep Rookie|WR")

    def test_duplicate_match_keeps_its_slot(self):
        # Two provider players can resolve to one board player (suffix variants
        # normalize together). Dropping the second used to shift every later
        # pick down one and put the whole draft on the wrong clock.
        players = [_p("Marvin Harrison", "WR")]
        picks = self._picks(("Marvin Harrison", "WR"), ("Marvin Harrison Jr.", "WR"))

        result = synced_draft_to_picks(picks, players, {"numTeams": 12})

        self.assertEqual(len(result["picks"]), 2, "a duplicate match must not drop a pick")
        self.assertEqual(result["totalPicks"], 2)
        self.assertEqual(result["nextPickNum"], 3)
        self.assertEqual(result["picks"][0]["playerId"], "Marvin Harrison|WR")
        self.assertTrue(result["picks"][1]["unmatched"])
        self.assertEqual(result["matched"], 1)

    def test_pick_numbers_are_preserved_in_order(self):
        players = [_p(f"P{i}", "RB") for i in range(1, 4)]
        picks = self._picks(("P3", "RB"), ("P1", "RB"), ("P2", "RB"))
        # Feed them out of order; the result must be sorted by pick number.
        result = synced_draft_to_picks(list(reversed(picks)), players, {"numTeams": 12})

        self.assertEqual([p["pickNum"] for p in result["picks"]], [1, 2, 3])


class TestPlayerMatcher(unittest.TestCase):
    def test_stable_provider_id_matches_without_metadata_or_name(self):
        player = Player(id="sleeper:123", name="Current Name", position="WR")
        roster = [SyncedRosterTeam("T1", [
            SyncedRosterPlayer("Old Name", "WR", provider_id="sleeper:123")
        ])]
        result = synced_rosters_to_picks(roster, [player], {})
        self.assertEqual(result["picks"][0]["playerId"], "sleeper:123")

    def test_suffix_variant_matches_base_name(self):
        players = [_p("Marvin Harrison Jr.", "WR")]
        rosters = [SyncedRosterTeam("T1", [SyncedRosterPlayer("Marvin Harrison", "WR")])]

        result = synced_rosters_to_picks(rosters, players, {})

        self.assertEqual(result["picks"][0]["playerId"], "Marvin Harrison Jr.|WR")

    def test_containment_prefers_closest_length_not_file_order(self):
        # Both board names contain the query. The closer one must win no matter
        # which order the player file happens to list them in.
        close = _p("Mike Evans", "WR")
        far = _p("Mike Evanston Williamson", "WR")
        rosters = [SyncedRosterTeam("T1", [SyncedRosterPlayer("Mike Evans", "WR")])]

        for board in ([far, close], [close, far]):
            result = synced_rosters_to_picks(rosters, board, {})
            self.assertEqual(result["picks"][0]["playerId"], "Mike Evans|WR")


if __name__ == "__main__":
    unittest.main()
