import unittest

from draft_assistant.models import Player
from draft_assistant.platform_sync import (
    SyncedRosterPlayer,
    SyncedRosterTeam,
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


if __name__ == "__main__":
    unittest.main()
