"""Offline tests for the Yahoo importer's OAuth URL + nested-JSON parsing."""
import unittest

from draft_assistant.importers.yahoo import (
    _parse_draft_picks,
    _parse_league,
    _parse_roster_players,
    auth_url,
    extract_code,
)
from draft_assistant.platform_sync import SyncedRosterPlayer, SyncedRosterTeam


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

    def test_roster_players_flatten_nested_yahoo_shape(self):
        roster = {"fantasy_content": {"team": [
            {"team_key": "461.l.123.t.1"},
            {"roster": {"0": {"players": {
                "0": {"player": [
                    {"player_key": "461.p.7200"},
                    {"player_id": "7200"},
                    {"name": {"full": "Josh Allen"}},
                    {"display_position": "QB"},
                    {"editorial_team_abbr": "BUF"},
                ]},
                "count": 1,
            }}}},
        ]}}

        players = _parse_roster_players(roster, "461.l.123")

        self.assertEqual(len(players), 1)
        self.assertEqual(players[0].name, "Josh Allen")
        self.assertEqual(players[0].position, "QB")
        self.assertEqual(players[0].team, "BUF")
        self.assertEqual(players[0].provider_id, "yahoo:7200")

    def test_extract_code_from_raw_and_url(self):
        self.assertEqual(extract_code("my_secret_code_123"), "my_secret_code_123")
        self.assertEqual(
            extract_code("https://localhost/?code=xyz789&state=oauth"),
            "xyz789",
        )
        self.assertEqual(
            extract_code("http://localhost:8080/callback?code=abc456"),
            "abc456",
        )
        self.assertEqual(extract_code("code=direct_code_321"), "direct_code_321")

    def test_extended_scoring_and_kick_averaging(self):
        settings = {"settings": [{
            "stat_modifiers": {"stats": [
                {"stat": {"stat_id": 7, "value": "2"}},     # pass_2pt
                {"stat": {"stat_id": 14, "value": "2"}},    # rush_2pt
                {"stat": {"stat_id": 15, "value": "2"}},    # rec_2pt
                {"stat": {"stat_id": 16, "value": "-2"}},   # fumbles
                {"stat": {"stat_id": 17, "value": "-1"}},   # fumbles_total
                {"stat": {"stat_id": 19, "value": "3"}},    # fg_0_19
                {"stat": {"stat_id": 20, "value": "3"}},    # fg_20_29
                {"stat": {"stat_id": 21, "value": "3"}},    # fg_30_39
                {"stat": {"stat_id": 22, "value": "4"}},    # fg_40_49
                {"stat": {"stat_id": 23, "value": "5"}},    # fg_50_plus
                {"stat": {"stat_id": 25, "value": "1"}},    # pat_made
                {"stat": {"stat_id": 26, "value": "-1"}},   # fg_miss
                {"stat": {"stat_id": 27, "value": "1"}},    # sack
                {"stat": {"stat_id": 28, "value": "2"}},    # def_int
                {"stat": {"stat_id": 29, "value": "2"}},    # fumble_recovery
                {"stat": {"stat_id": 30, "value": "6"}},    # int_ret_td & fum_ret_td
                {"stat": {"stat_id": 31, "value": "2"}},    # safety
                {"stat": {"stat_id": 32, "value": "2"}},    # blk_kick
                {"stat": {"stat_id": 33, "value": "6"}},    # krt_td & prt_td
            ]}
        }]}
        teams = {"teams": []}
        info = _parse_league(settings, teams, "nfl.l.123")
        scoring = info["scoring"]
        self.assertEqual(scoring["pass_2pt"], 2.0)
        self.assertEqual(scoring["rush_2pt"], 2.0)
        self.assertEqual(scoring["rec_2pt"], 2.0)
        self.assertEqual(scoring["fumbles"], -2.0)
        self.assertEqual(scoring["fumbles_total"], -1.0)
        self.assertEqual(scoring["fg_0_39"], 3.0)
        self.assertEqual(scoring["fg_40_49"], 4.0)
        self.assertEqual(scoring["fg_50_59"], 5.0)
        self.assertEqual(scoring["fg_60_plus"], 5.0)
        self.assertEqual(scoring["pat_made"], 1.0)
        self.assertEqual(scoring["fg_miss"], -1.0)
        self.assertEqual(scoring["sack"], 1.0)
        self.assertEqual(scoring["def_int"], 2.0)
        self.assertEqual(scoring["fumble_recovery"], 2.0)
        self.assertEqual(scoring["int_ret_td"], 6.0)
        self.assertEqual(scoring["fum_ret_td"], 6.0)
        self.assertEqual(scoring["safety"], 2.0)
        self.assertEqual(scoring["blk_kick"], 2.0)
        self.assertEqual(scoring["krt_td"], 6.0)
        self.assertEqual(scoring["prt_td"], 6.0)

    def test_draft_order_sorting_and_user_seat_detection(self):
        settings = {"settings": [{
            "draft_type": "snake",
            "draft_status": "predraft",
            "season": "2026",
            "stat_modifiers": {"stats": []},
        }]}
        teams = {"teams": {
            "0": {"team": [[
                {"team_key": "t.1"},
                {"name": "Team One"},
                {"draft_position": 2},
                {"managers": [{"manager": {"nickname": "Alice"}}]},
            ]]},
            "1": {"team": [[
                {"team_key": "t.2"},
                {"name": "Team Two"},
                {"draft_position": 1},
                {"is_owned_by_current_login": 1},
                {"managers": [{"manager": {"nickname": "Me", "is_current_login": "1"}}]},
            ]]},
        }}
        info = _parse_league(settings, teams, "nfl.l.123")
        # Team Two has draft_position 1, so it should be first in teamNames
        self.assertEqual(info["teamNames"], ["Team Two", "Team One"])
        # And user seat should be slot 1
        self.assertEqual(info["draftPosition"], 1)
        self.assertEqual(info["myTeamName"], "Team Two")
        self.assertEqual(info["draftType"], "snake")
        self.assertEqual(info["draftStatus"], "predraft")
        self.assertEqual(info["season"], "2026")

    def test_parse_draft_picks(self):
        draft_results = {"draft_results": [
            {"draft_result": {"pick": 1, "round": 1, "team_key": "t.1", "player_key": "461.p.7200"}},
            {"draft_result": {"pick": 2, "round": 1, "team_key": "t.2", "player_key": "461.p.8200"}},
        ]}
        teams_data = {"teams": [
            {"team": [[{"team_key": "t.1"}, {"name": "Team One"}, {"draft_position": 1}]]},
            {"team": [[{"team_key": "t.2"}, {"name": "Team Two"}, {"draft_position": 2}]]},
        ]}
        rosters = [
            SyncedRosterTeam(
                name="Team One",
                provider_id="t.1",
                players=[SyncedRosterPlayer(name="Josh Allen", position="QB", team="BUF", provider_id="yahoo:7200")],
            ),
            SyncedRosterTeam(
                name="Team Two",
                provider_id="t.2",
                players=[SyncedRosterPlayer(name="CeeDee Lamb", position="WR", team="DAL", provider_id="yahoo:8200")],
            ),
        ]
        picks = _parse_draft_picks(draft_results, teams_data, rosters)
        self.assertEqual(len(picks), 2)
        self.assertEqual(picks[0].pick_no, 1)
        self.assertEqual(picks[0].team_num, 1)
        self.assertEqual(picks[0].player.name, "Josh Allen")
        self.assertEqual(picks[0].player.position, "QB")
        self.assertEqual(picks[0].player.provider_id, "yahoo:7200")

        self.assertEqual(picks[1].pick_no, 2)
        self.assertEqual(picks[1].team_num, 2)
        self.assertEqual(picks[1].player.name, "CeeDee Lamb")
        self.assertEqual(picks[1].player.position, "WR")


if __name__ == "__main__":
    unittest.main()
