"""Offline tests for the Yahoo importer's OAuth URL + nested-JSON parsing."""
import unittest

from draft_assistant.importers.yahoo import (
    _parse_draft_picks,
    _parse_league,
    _parse_roster_players,
    auth_url,
    extract_code,
    parse_settings_text,
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


class TestYahooParseSettingsText(unittest.TestCase):
    def test_parse_settings_empty_raises(self):
        with self.assertRaises(ValueError):
            parse_settings_text("")
        with self.assertRaises(ValueError):
            parse_settings_text("   \n\t  ")

    def test_parse_settings_comma_positions_and_scoring(self):
        sample = """
League Name: The Champions League
Max Teams: 12
Draft Type: Live Standard Draft
Roster Positions: QB, WR, WR, RB, RB, TE, W/R/T, K, DEF, BN, BN, BN, BN, BN, BN, IR

Passing Yards: 25 yards per point
Passing Touchdowns: 4
Interceptions: -2
Rushing Yards: 10 yards per point
Rushing Touchdowns: 6
Receptions: 0.5
Receiving Yards: 10 yards per point
Receiving Touchdowns: 6
2-Point Conversions: 2
Fumbles Lost: -2
Sacks: 1
Interceptions: 2
Fumble Recoveries: 2
Touchdown (DEF): 6
Safeties: 2
Blocked Kicks: 2
Field Goals 0-19 Yards: 3
Field Goals 20-29 Yards: 3
Field Goals 30-39 Yards: 3
Field Goals 40-49 Yards: 4
Field Goals 50+ Yards: 5
Point After Attempt Made: 1

1. Josh's Team
2. Sarah's Squad
3. Team Dynasty
        """
        info = parse_settings_text(sample)
        self.assertEqual(info["name"], "The Champions League")
        self.assertEqual(info["numTeams"], 12)
        self.assertEqual(info["draftType"], "snake")
        self.assertEqual(info["platform"], "Yahoo")
        self.assertEqual(info["scoringType"], "half-ppr")

        # Roster
        roster = info["rosterSlots"]
        self.assertEqual(roster["QB"], 1)
        self.assertEqual(roster["WR"], 2)
        self.assertEqual(roster["RB"], 2)
        self.assertEqual(roster["TE"], 1)
        self.assertEqual(roster["FLEX"], 1)
        self.assertEqual(roster["K"], 1)
        self.assertEqual(roster["DST"], 1)
        self.assertEqual(roster["BN"], 6)

        # Scoring
        sc = info["scoring"]
        self.assertEqual(sc["pass_yd"], 0.04)
        self.assertEqual(sc["pass_td"], 4.0)
        self.assertEqual(sc["pass_int"], -2.0)
        self.assertEqual(sc["rush_yd"], 0.1)
        self.assertEqual(sc["rush_td"], 6.0)
        self.assertEqual(sc["rec"], 0.5)
        self.assertEqual(sc["rec_yd"], 0.1)
        self.assertEqual(sc["rec_td"], 6.0)
        self.assertEqual(sc["pass_2pt"], 2.0)
        self.assertEqual(sc["fumbles"], -2.0)
        self.assertEqual(sc["fg_0_39"], 3.0)
        self.assertEqual(sc["fg_40_49"], 4.0)
        self.assertEqual(sc["fg_50_59"], 5.0)
        self.assertEqual(sc["pat_made"], 1.0)
        self.assertEqual(sc["sack"], 1.0)
        self.assertEqual(sc["def_int"], 2.0)
        self.assertEqual(sc["fumble_recovery"], 2.0)
        self.assertEqual(sc["int_ret_td"], 6.0)
        self.assertEqual(sc["safety"], 2.0)

        # Teams
        self.assertEqual(info["teamNames"][:3], ["Josh's Team", "Sarah's Squad", "Team Dynasty"])

    def test_parse_settings_line_by_line_and_superflex(self):
        sample = """
League: Superflex Showdown
Teams: 10
Draft Type: Live Salary Cap Draft
Quarterback (QB): 1
Running Back (RB): 2
Wide Receiver (WR): 3
Tight End (TE): 1
Superflex (Q/W/R/T): 1
Defense (DEF): 1
Bench (BN): 5
Injured Reserve (IR): 2

Passing Yards: 20 yards per point
Passing Touchdowns: 6
Receptions: 1.0
        """
        info = parse_settings_text(sample)
        self.assertEqual(info["name"], "Superflex Showdown")
        self.assertEqual(info["numTeams"], 10)
        self.assertEqual(info["draftType"], "auction")
        self.assertEqual(info["scoringType"], "ppr")

        roster = info["rosterSlots"]
        self.assertEqual(roster["QB"], 1)
        self.assertEqual(roster["RB"], 2)
        self.assertEqual(roster["WR"], 3)
        self.assertEqual(roster["TE"], 1)
        self.assertEqual(roster["SUPERFLEX"], 1)
        self.assertEqual(roster["DST"], 1)
        self.assertEqual(roster["BN"], 5)
        self.assertEqual(roster["IR"], 2)

        sc = info["scoring"]
        self.assertEqual(sc["pass_yd"], 0.05)
        self.assertEqual(sc["pass_td"], 6.0)
        self.assertEqual(sc["rec"], 1.0)


class TestDraftAnalysis(unittest.TestCase):
    """fetch_draft_analysis pages Yahoo's player collection and keeps only
    drafted players (average_pick "-" means nobody drafts them)."""

    @staticmethod
    def _page(players):
        return {"fantasy_content": {"league": [
            {"league_key": "nfl.l.123"},
            {"players": {str(i): {"player": [[
                {"player_key": f"461.p.{i}"},
                {"name": {"full": p["name"]}},
                {"display_position": p["pos"]},
                {"editorial_team_abbr": p.get("team", "Det")},
                {"draft_analysis": [
                    {"average_pick": p.get("avg_pick", "-")},
                    {"average_round": p.get("avg_round", "-")},
                    {"average_cost": p.get("avg_cost", "-")},
                    {"percent_drafted": p.get("pct", "-")},
                ]},
            ]]} for i, p in enumerate(players)}},
        ]}}

    def test_pages_and_skips_undrafted(self):
        from unittest.mock import patch
        from draft_assistant.importers import yahoo

        # Page 1: 25 drafted; page 2: 2 drafted then an undrafted tail-only
        # page which must stop the paging.
        page1 = self._page([{"name": f"Player {i}", "pos": "RB",
                             "avg_pick": str(i + 1.5), "pct": "0.99"} for i in range(25)])
        page2 = self._page([
            {"name": "Late Guy", "pos": "WR", "avg_pick": "180.2"},
            {"name": "Undrafted Guy", "pos": "WR"},           # avg_pick "-"
            {"name": "Multi Pos", "pos": "WR,TE", "avg_pick": "190.0"},
        ])
        page3 = self._page([{"name": f"Deep {i}", "pos": "TE"} for i in range(25)])
        pages = [page1, page2, page3]
        calls = []

        def fake_get(token, path):
            calls.append(path)
            return pages[len(calls) - 1]

        with patch.object(yahoo, "_api_get", side_effect=fake_get):
            rows = yahoo.fetch_draft_analysis("tok", "nfl.l.123")

        self.assertEqual(len(rows), 27)                     # 25 + 2 drafted
        self.assertEqual(rows[0]["average_pick"], 1.5)
        self.assertEqual(rows[0]["team"], "DET")            # abbr upper-cased
        self.assertEqual(rows[26]["position"], "WR")        # "WR,TE" -> WR
        self.assertNotIn("Undrafted Guy", [r["name"] for r in rows])
        # Paging: page 2 was short of its count, so page 3 is never requested.
        self.assertEqual(len(calls), 2)
        self.assertIn("sort=OR/draft_analysis", calls[0])
        self.assertIn("league/nfl.l.123/players;start=0;count=25", calls[0])

    def test_stops_when_full_page_has_no_drafted_players(self):
        from unittest.mock import patch
        from draft_assistant.importers import yahoo

        drafted = self._page([{"name": f"P{i}", "pos": "RB", "avg_pick": str(i + 1)}
                              for i in range(25)])
        undrafted = self._page([{"name": f"U{i}", "pos": "TE"} for i in range(25)])

        pages = [drafted, undrafted, undrafted]
        calls = []

        def fake_get(token, path):
            calls.append(path)
            return pages[len(calls) - 1]

        with patch.object(yahoo, "_api_get", side_effect=fake_get):
            rows = yahoo.fetch_draft_analysis("tok", "nfl.l.123")

        self.assertEqual(len(rows), 25)
        self.assertEqual(len(calls), 2)   # stops after the all-undrafted page


class TestApplyYahooAdp(unittest.TestCase):
    def _board(self):
        from draft_assistant.models import Player
        return [
            Player(id="1", name="D'Andre Swift", position="RB", team="CHI",
                   adp=45.0, projections={"rush_yd": 1000}),
            Player(id="2", name="Justin Jefferson", position="WR", team="MIN",
                   adp=4.0, projections={"rec_yd": 1400}),
            Player(id="3", name="Dallas Cowboys", position="DST", team="DAL",
                   adp=None, projections={"sack": 40}),
        ]

    def test_overlays_and_preserves_public_adp(self):
        from draft_assistant.importers.free_sources import apply_yahoo_adp

        board = self._board()
        rows = [
            # Name spelling differs -> normalized merge key must still match.
            {"name": "DAndre Swift", "position": "RB", "team": "CHI",
             "average_pick": 38.4, "average_cost": 12.0, "percent_drafted": 0.98},
            # DEF position + team abbr -> DST merge key.
            {"name": "Dallas", "position": "DEF", "team": "DAL",
             "average_pick": 140.0, "average_cost": None, "percent_drafted": 0.5},
            {"name": "Nobody Real", "position": "WR", "team": "ATL",
             "average_pick": 60.0},
        ]
        matched = apply_yahoo_adp(board, rows)

        self.assertEqual(matched, 2)
        swift = board[0]
        self.assertEqual(swift.adp, 38.4)
        self.assertEqual(swift.metadata["yahoo_adp"], 38.4)
        self.assertEqual(swift.metadata["public_adp"], 45.0)  # original kept
        self.assertEqual(swift.metadata["yahoo_avg_cost"], 12.0)
        dst = board[2]
        self.assertEqual(dst.adp, 140.0)
        self.assertNotIn("public_adp", dst.metadata)          # had no ADP before
        jj = board[1]
        self.assertEqual(jj.adp, 4.0)                         # untouched

    def test_reapplying_does_not_clobber_public_adp(self):
        from draft_assistant.importers.free_sources import apply_yahoo_adp

        board = self._board()
        rows = [{"name": "D'Andre Swift", "position": "RB", "team": "CHI",
                 "average_pick": 38.4}]
        apply_yahoo_adp(board, rows)
        rows[0]["average_pick"] = 40.0
        apply_yahoo_adp(board, rows)
        self.assertEqual(board[0].adp, 40.0)
        self.assertEqual(board[0].metadata["public_adp"], 45.0)  # still original


class TestSettingsTextRosterParsing(unittest.TestCase):
    """The paste fallback is what a user falls back on when Yahoo has not
    approved their app for API access, so its roster must be exact — a wrong
    slot count changes the draft's round count and every replacement level."""

    LINE_LAYOUT = "\n".join([
        "League Settings",
        "League Name        Anonymous",
        "Max Teams          12",
        # Both of these used to donate their number to a position: "Date" ends
        # in "te" (TE) and "Week" ends in "k" (K).
        "Trade End Date     Week 11",
        "Playoffs Start     Week 15",
        "Quarterback        1",
        "Running Back       2",
        "Wide Receiver      2",
        "Tight End          1",
        "W/R/T              1",
        "Kicker             1",
        "Defense/Special Teams 1",
        "Bench              6",
    ])

    def test_unrelated_lines_do_not_donate_counts(self):
        from draft_assistant.importers.yahoo import parse_settings_text
        roster = parse_settings_text(self.LINE_LAYOUT)["rosterSlots"]
        self.assertEqual(roster["TE"], 1)   # not 11, from "Trade End Date"
        self.assertEqual(roster["K"], 1)    # not 15, from "Playoffs ... Week"
        self.assertEqual(roster["BN"], 6)

    def test_typed_flex_is_claimed_once(self):
        from draft_assistant.importers.yahoo import parse_settings_text
        roster = parse_settings_text(self.LINE_LAYOUT)["rosterSlots"]
        self.assertEqual(roster["FLEX"], 1)
        # "W/R/T" also contains "W/R"; it must not add a phantom RBWR slot.
        self.assertEqual(roster.get("RBWR", 0), 0)

    def test_league_name_survives_the_settings_heading(self):
        from draft_assistant.importers.yahoo import parse_settings_text
        # "League Settings" precedes the real row and used to win, leaving the
        # placeholder name behind.
        self.assertEqual(parse_settings_text(self.LINE_LAYOUT)["name"], "Anonymous")

    def test_first_line_names_the_league_when_no_label_row(self):
        from draft_assistant.importers.yahoo import parse_settings_text
        info = parse_settings_text(
            "Anonymous\nMax Teams 12\nRoster Positions QB, RB, RB, WR, WR, TE, W/T, K, DEF, BN, BN\n")
        self.assertEqual(info["name"], "Anonymous")
        self.assertEqual(info["rosterSlots"]["WRTE"], 1)   # typed flex preserved
        self.assertEqual(info["rosterSlots"]["BN"], 2)

    def test_one_slot_per_line_layout_counts_each_line(self):
        from draft_assistant.importers.yahoo import parse_settings_text
        roster = parse_settings_text(
            "My Dynasty League\nMax Teams 12\nQB\nRB\nRB\nWR\nWR\nTE\nW/R/T\nK\nDEF\n")["rosterSlots"]
        self.assertEqual(roster["RB"], 2)
        self.assertEqual(roster["WR"], 2)
        self.assertEqual(roster["FLEX"], 1)
        self.assertEqual(roster["DST"], 1)

    def test_table_copy_puts_each_cell_on_its_own_line(self):
        """Copying Yahoo's settings table out of a browser yields the label and
        its value on separate lines. That must parse identically to the inline
        layout — it is the shape most users actually paste."""
        from draft_assistant.importers.yahoo import parse_settings_text
        info = parse_settings_text("\n".join([
            "Lega di Paca",
            "League Settings",
            "League Name",
            "Lega di Paca",
            "Max Teams",
            "12",
            "Roster Positions",
            "QB, WR, WR, RB, RB, TE, W/R/T, K, DEF, BN, BN, BN, BN, BN, BN",
            "Receptions",
            "0.5",
        ]))
        self.assertEqual(info["name"], "Lega di Paca")
        self.assertEqual(info["numTeams"], 12)
        self.assertEqual(info["scoringType"], "half-ppr")
        roster = info["rosterSlots"]
        self.assertEqual((roster["QB"], roster["RB"], roster["WR"]), (1, 2, 2))
        self.assertEqual(roster["FLEX"], 1)
        self.assertEqual(roster["BN"], 6)


if __name__ == "__main__":
    unittest.main()
