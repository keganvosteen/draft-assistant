"""Tests for the CBS Sports projections scraper.

Fixtures mirror the real page shape: a group-label row ("Passing", "Rushing"),
then a header whose cells spell the stat out in full, then rows whose player
cell carries the name twice — abbreviated for narrow screens, then in full.

No test here touches the network. A scraper's failure mode is a site redesign,
so what these pin is that a changed page is *noticed* rather than silently
producing an empty or mis-mapped board.
"""
import unittest
from unittest.mock import patch

from draft_assistant.models import Player
from draft_assistant.importers import cbs
from draft_assistant.importers.cbs import (
    fetch_all_cbs,
    parse_cbs_table,
    _player_identity,
)


QB_TABLE = [
    ["", "", "Passing", "Rushing", "Misc"],
    ["Player", "gp Games Played", "att Pass Attempts", "cmp Pass Completions",
     "yds Passing Yards", "yds/g Passing Yards Per Game", "td Touchdowns Passes",
     "int Interceptions Thrown", "rate Passer Rating", "att Rushing Attempts",
     "yds Rushing Yards", "avg Average Yards Per Rush", "td Rushing Touchdowns",
     "fl Fumbles Lost", "fpts Fantasy Points", "fppg Fantasy Points Per Game"],
    ["J. Allen QB BUF Josh Allen QB BUF", "17", "488", "334", "3717", "218.6",
     "30", "13", "100.2", "125", "611", "4.9", "11", "4", "419.1", "24.7"],
]

WR_TABLE = [
    ["", "", "Receiving", "Rushing", "Misc"],
    ["Player", "gp Games Played", "tgt Targets", "rec Receptions",
     "yds Receiving Yards", "yds/g Yards Per Game",
     "avg Average Yards Per Reception", "td Receiving Touchdowns",
     "att Rushing Attempts", "yds Rushing Yards", "avg Average Yards Per Rush",
     "td Rushing Touchdowns", "fl Fumbles Lost", "fpts Fantasy Points",
     "fppg Fantasy Points Per Game"],
    ["P. Nacua WR LAR Puka Nacua WR LAR", "17", "177", "129", "1699", "99.9",
     "13.2", "9", "15", "109", "7.3", "2", "1", "371.9", "21.9"],
]


class TestPlayerIdentity(unittest.TestCase):
    def test_full_name_is_taken_over_the_abbreviation(self):
        self.assertEqual(_player_identity("J. Allen QB BUF Josh Allen QB BUF", "QB"),
                         ("Josh Allen", "BUF"))

    def test_multi_word_surnames_survive(self):
        self.assertEqual(
            _player_identity("J. Smith-Njigba WR SEA Jaxon Smith-Njigba WR SEA", "WR"),
            ("Jaxon Smith-Njigba", "SEA"))

    def test_a_cell_that_does_not_match_is_skipped_not_guessed(self):
        self.assertIsNone(_player_identity("Totals", "QB"))
        self.assertIsNone(_player_identity("", "QB"))


class TestParseTable(unittest.TestCase):
    def test_columns_are_matched_by_description_not_offset(self):
        # Passing and rushing yards are both "yds"; only the full header text
        # tells them apart, which is why this maps by description.
        players = parse_cbs_table(QB_TABLE, "QB")
        self.assertEqual(len(players), 1)
        p = players[0]
        self.assertEqual((p.name, p.team, p.position), ("Josh Allen", "BUF", "QB"))
        self.assertEqual(p.projections["pass_yd"], 3717.0)
        self.assertEqual(p.projections["rush_yd"], 611.0)
        self.assertEqual(p.projections["pass_td"], 30.0)
        self.assertEqual(p.projections["rush_td"], 11.0)
        self.assertEqual(p.projections["pass_int"], 13.0)
        self.assertEqual(p.projections["fumbles"], 4.0)

    def test_reordered_columns_still_map_correctly(self):
        # A site reordering its columns must remap, not shift every stat by one.
        header = list(QB_TABLE[1])
        row = list(QB_TABLE[2])
        order = [0] + list(range(len(header) - 1, 0, -1))
        table = [QB_TABLE[0], [header[i] for i in order], [row[i] for i in order]]
        players = parse_cbs_table(table, "QB")
        self.assertEqual(players[0].projections["pass_yd"], 3717.0)
        self.assertEqual(players[0].projections["rush_yd"], 611.0)

    def test_receiving_line_maps_for_receivers(self):
        p = parse_cbs_table(WR_TABLE, "WR")[0]
        self.assertEqual(p.projections["rec"], 129.0)
        self.assertEqual(p.projections["rec_yd"], 1699.0)
        self.assertEqual(p.projections["rec_td"], 9.0)
        self.assertEqual(p.projections["rush_yd"], 109.0)

    def test_derived_columns_are_ignored(self):
        # Fantasy points and per-game rates are outputs, not inputs; taking them
        # would double-count against the league's own scoring.
        p = parse_cbs_table(QB_TABLE, "QB")[0]
        for stat in p.projections:
            self.assertNotIn("fpts", stat)
            self.assertNotIn("fppg", stat)

    def test_a_redesigned_page_yields_nothing_rather_than_garbage(self):
        self.assertEqual(parse_cbs_table([["Some", "Other", "Table"]], "QB"), [])
        self.assertEqual(parse_cbs_table([["Player", "who", "knows"]], "QB"), [])

    def test_zero_valued_stats_are_dropped_not_stored(self):
        row = list(QB_TABLE[2])
        row[10] = "0"  # rushing yards
        players = parse_cbs_table([QB_TABLE[0], QB_TABLE[1], row], "QB")
        self.assertNotIn("rush_yd", players[0].projections)


class TestFetchAll(unittest.TestCase):
    def test_one_position_failing_does_not_lose_the_source(self):
        def flaky(season, position):
            if position == "QB":
                raise OSError("500")
            return [Player(id=position, name=f"Test {position}", position=position,
                           projections={"rec_yd": 900.0})]

        with patch.object(cbs, "fetch_cbs", side_effect=flaky):
            players = fetch_all_cbs(2026)
        self.assertEqual(len(players), 3)  # RB/WR/TE survive a QB page failure
        self.assertEqual(sorted(p.position for p in players), ["RB", "TE", "WR"])

    def test_every_position_failing_raises_with_the_causes(self):
        with patch.object(cbs, "fetch_cbs", side_effect=OSError("down")):
            with self.assertRaises(RuntimeError) as ctx:
                fetch_all_cbs(2026)
        self.assertIn("down", str(ctx.exception))

    def test_a_silently_empty_site_raises_too(self):
        # The likeliest redesign symptom is zero rows, not an exception.
        with patch.object(cbs, "fetch_cbs", return_value=[]):
            with self.assertRaises(RuntimeError) as ctx:
                fetch_all_cbs(2026)
        self.assertIn("no rows parsed", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
