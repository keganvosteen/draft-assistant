"""Offline tests for the Yahoo importer's OAuth URL + nested-JSON parsing."""
import unittest

from draft_assistant.importers.yahoo import _parse_league, _parse_roster_players, auth_url


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


if __name__ == "__main__":
    unittest.main()


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
