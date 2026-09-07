import unittest
from draft_assistant.draft_paste_parser import (
    clean_line_text,
    get_snake_team,
    parse_draft_text,
)


class TestDraftPasteParser(unittest.TestCase):
    def setUp(self):
        self.players = [
            {"id": "p1", "name": "Bijan Robinson", "pos": "RB", "team": "ATL"},
            {"id": "p2", "name": "CeeDee Lamb", "pos": "WR", "team": "DAL"},
            {"id": "p3", "name": "Ja'Marr Chase", "pos": "WR", "team": "CIN"},
            {"id": "p4", "name": "Josh Allen", "pos": "QB", "team": "BUF"},
        ]

    def test_snake_team_calculation(self):
        # 12-team snake draft
        self.assertEqual(get_snake_team(1, 12), 1)
        self.assertEqual(get_snake_team(12, 12), 12)
        self.assertEqual(get_snake_team(13, 12), 12)  # Round 2 start
        self.assertEqual(get_snake_team(24, 12), 1)   # Round 2 end
        self.assertEqual(get_snake_team(25, 12), 1)   # Round 3 start

    def test_clean_line_text_formats(self):
        # ESPN
        pick, name = clean_line_text("1. (1) Team 1 - Bijan Robinson RB")
        self.assertEqual(name, "Bijan Robinson")

        # Yahoo
        pick, name = clean_line_text("1.01 CeeDee Lamb (DAL - WR)")
        self.assertEqual(name, "CeeDee Lamb")

        # Plain list
        pick, name = clean_line_text("Ja'Marr Chase")
        self.assertEqual(name, "Ja'Marr Chase")

    def test_parse_draft_text_sequential(self):
        raw_text = """
        1. (1) Bijan Robinson RB
        2. CeeDee Lamb (DAL - WR)
        Ja'Marr Chase
        """
        parsed = parse_draft_text(raw_text, self.players, num_teams=12, start_pick=1)
        self.assertEqual(len(parsed), 3)

        self.assertEqual(parsed[0]["pickNum"], 1)
        self.assertEqual(parsed[0]["teamNum"], 1)
        self.assertEqual(parsed[0]["matchedPlayerId"], "p1")
        self.assertEqual(parsed[0]["confidence"], "HIGH")

        self.assertEqual(parsed[1]["pickNum"], 2)
        self.assertEqual(parsed[1]["teamNum"], 2)
        self.assertEqual(parsed[1]["matchedPlayerId"], "p2")

        self.assertEqual(parsed[2]["pickNum"], 3)
        self.assertEqual(parsed[2]["teamNum"], 3)
        self.assertEqual(parsed[2]["matchedPlayerId"], "p3")


if __name__ == "__main__":
    unittest.main()
