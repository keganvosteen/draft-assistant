"""Offline tests for the Yahoo importer's OAuth URL + nested-JSON parsing."""
import unittest

from draft_assistant.importers.yahoo import _parse_league, auth_url


SETTINGS = {"fantasy_content": {"league": [
    {"league_key": "nfl.l.123", "name": "My Yahoo League", "num_teams": 12, "season": "2025"},
    {"settings": [{
        "roster_positions": [
            {"roster_position": {"position": "QB", "count": 1}},
            {"roster_position": {"position": "RB", "count": 2}},
            {"roster_position": {"position": "WR", "count": 2}},
            {"roster_position": {"position": "TE", "count": 1}},
            {"roster_position": {"position": "W/R/T", "count": 1}},
            {"roster_position": {"position": "W/T", "count": 1}},
            {"roster_position": {"position": "K", "count": 1}},
            {"roster_position": {"position": "DEF", "count": 1}},
            {"roster_position": {"position": "BN", "count": 6}},
        ],
        # stat_categories carry definitions WITHOUT a value — must be ignored.
        "stat_categories": {"stats": [{"stat": {"stat_id": 11, "name": "Receptions"}}]},
        "stat_modifiers": {"stats": [
            {"stat": {"stat_id": 4, "value": "0.04"}},
            {"stat": {"stat_id": 5, "value": "4"}},
            {"stat": {"stat_id": 11, "value": "0.5"}},
            {"stat": {"stat_id": 12, "value": "0.1"}},
            {"stat": {"stat_id": 13, "value": "6"}},
        ]},
    }]},
]}}

TEAMS = {"fantasy_content": {"league": [
    {"league_key": "nfl.l.123"},
    {"teams": {"count": 2,
        "0": {"team": [[{"team_key": "t.1"}, {"name": "Team Alpha"},
                        {"managers": [{"manager": {"nickname": "Alice"}}]}]]},
        "1": {"team": [[{"team_key": "t.2"}, {"name": "Team Bravo"},
                        {"managers": [{"manager": {"nickname": "Bob"}}]}]]}}},
]}}


class TestYahooParse(unittest.TestCase):
    def test_roster_maps_typed_flex(self):
        info = _parse_league(SETTINGS, TEAMS, "nfl.l.123")
        self.assertEqual(info["name"], "My Yahoo League")
        self.assertEqual(info["numTeams"], 12)
        self.assertEqual(info["rosterSlots"]["FLEX"], 1)   # W/R/T
        self.assertEqual(info["rosterSlots"]["WRTE"], 1)   # W/T -> typed flex
        self.assertEqual(info["rosterSlots"]["DST"], 1)    # DEF -> DST

    def test_scoring_uses_modifiers_not_categories(self):
        info = _parse_league(SETTINGS, TEAMS, "nfl.l.123")
        self.assertEqual(info["scoring"]["pass_yd"], 0.04)
        self.assertEqual(info["scoring"]["pass_td"], 4.0)
        self.assertEqual(info["scoring"]["rec"], 0.5)       # value present
        # stat_categories' value-less stat must not appear as 0/None.
        self.assertTrue(all(v is not None for v in info["scoring"].values()))

    def test_team_names(self):
        info = _parse_league(SETTINGS, TEAMS, "nfl.l.123")
        self.assertEqual(info["teamNames"], ["Team Alpha", "Team Bravo"])

    def test_auth_url_has_params(self):
        url = auth_url("ABC", "https://localhost/")
        self.assertIn("client_id=ABC", url)
        self.assertIn("response_type=code", url)


if __name__ == "__main__":
    unittest.main()
