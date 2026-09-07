import unittest
from draft_assistant.fuzzy import score_player_query, search_players_fuzzy


class TestFuzzyQuery(unittest.TestCase):
    def setUp(self):
        self.players = [
            {"id": "bijan", "name": "Bijan Robinson", "pos": "RB", "team": "ATL", "adp": 4.5},
            {"id": "josh_allen", "name": "Josh Allen", "pos": "QB", "team": "BUF", "adp": 21.0},
            {"id": "keenan_allen", "name": "Keenan Allen", "pos": "WR", "team": "CHI", "adp": 72.0},
            {"id": "jamarr", "name": "Ja'Marr Chase", "pos": "WR", "team": "CIN", "adp": 6.0},
            {"id": "kc_dst", "name": "Kansas City Chiefs", "pos": "DST", "team": "KC", "adp": 160.0},
        ]

    def test_prefix_token_match(self):
        results = search_players_fuzzy("bij", self.players)
        self.assertTrue(len(results) > 0)
        self.assertEqual(results[0]["id"], "bijan")

    def test_position_filtered_token_match(self):
        results = search_players_fuzzy("allen qb", self.players)
        self.assertTrue(len(results) > 0)
        self.assertEqual(results[0]["id"], "josh_allen")

        wr_results = search_players_fuzzy("allen wr", self.players)
        self.assertTrue(len(wr_results) > 0)
        self.assertEqual(wr_results[0]["id"], "keenan_allen")

    def test_apostrophe_token_match(self):
        results = search_players_fuzzy("ja'm", self.players)
        self.assertTrue(len(results) > 0)
        self.assertEqual(results[0]["id"], "jamarr")

    def test_dst_team_match(self):
        results = search_players_fuzzy("kc dst", self.players)
        self.assertTrue(len(results) > 0)
        self.assertEqual(results[0]["id"], "kc_dst")


if __name__ == "__main__":
    unittest.main()
