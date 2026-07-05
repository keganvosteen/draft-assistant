"""Offline tests for the FFToday scraper.

FFToday is an HTML scrape (nested layout tables, a colspan title row before the
real header, and DUPLICATE column labels for Passing vs Rushing), so these
fixtures lock the parser + positional column mapping without hitting the network.
"""
import unittest

from draft_assistant.importers.fftoday import (
    _select_projection_table,
    _extract_players_from_table,
    fetch_all_fftoday,  # imported to ensure the module loads
)


def _proj_table(title, header_cells, data_rows):
    """Wrap a projection table inside an outer layout table (FFToday nests them),
    with a colspan title row before the real column header."""
    th = "".join(f"<th>{c}</th>" for c in header_cells)
    body = ""
    for row in data_rows:
        body += "<tr>" + "".join(f"<td>{c}</td>" for c in row) + "</tr>"
    return (
        "<html><body><table><tr><td>"
        "<table>"
        f"<tr><td colspan='{len(header_cells)}'>{title}</td></tr>"
        f"<tr>{th}</tr>"
        f"{body}"
        "</table>"
        "</td></tr></table></body></html>"
    )


QB_HTML = _proj_table(
    "Quarterback Projections: 2026",
    ["Chg", "Player", "Tm", "Bye", "Cmp", "Att", "Yds", "TD", "INT", "Att", "Yds", "TD", "FPts"],
    [
        ["", "Josh Allen", "BUF", "7", "326", "479", "3,787", "26", "9", "113", "567", "12", "422.1"],
        ["", "Lamar Jackson", "BAL", "7", "300", "450", "3,500", "30", "7", "140", "900", "5", "410.0"],
    ],
)

WR_HTML = _proj_table(
    "Wide Receiver Projections: 2026",
    ["Chg", "Player", "Tm", "Bye", "Rec", "Yds", "TD", "Att", "Yds", "TD", "FPts"],
    [
        ["", "Puka Nacua", "LAR", "11", "116", "1,561", "9", "10", "72", "1", "223.3"],
        ["", "Ja'Marr Chase", "CIN", "10", "120", "1,600", "12", "2", "11", "0", "250.0"],
    ],
)


def _by_name(players, name):
    return next(p for p in players if p.name == name)


class TestParser(unittest.TestCase):
    def test_finds_table_nested_with_title_row(self):
        table = _select_projection_table(QB_HTML)
        self.assertIsNotNone(table)
        # Row 0 should be the real column header (title row stripped).
        self.assertIn("Player", table[0])
        self.assertEqual(table[1][1], "Josh Allen")


class TestPositionalMapping(unittest.TestCase):
    def test_qb_disambiguates_pass_vs_rush(self):
        players = _extract_players_from_table(_select_projection_table(QB_HTML), "QB")
        p = _by_name(players, "Josh Allen")
        # The bug was pass_yd picking up rushing's "Yds" (567). It must be 3787.
        self.assertEqual(p.projections["pass_yd"], 3787.0)
        self.assertEqual(p.projections["pass_td"], 26.0)
        self.assertEqual(p.projections["pass_int"], 9.0)
        self.assertEqual(p.projections["rush_yd"], 567.0)
        self.assertEqual(p.projections["rush_td"], 12.0)

    def test_wr_receiving_block_first(self):
        players = _extract_players_from_table(_select_projection_table(WR_HTML), "WR")
        p = _by_name(players, "Puka Nacua")
        # WR lists receiving before rushing — 1561 is REC yards, not rush.
        self.assertEqual(p.projections["rec"], 116.0)
        self.assertEqual(p.projections["rec_yd"], 1561.0)
        self.assertEqual(p.projections["rec_td"], 9.0)
        self.assertEqual(p.projections["rush_yd"], 72.0)

    def test_k_and_dst_are_skipped(self):
        # FFToday K/DST are intentionally not scraped (Sleeper covers them).
        table = _select_projection_table(QB_HTML)
        self.assertEqual(_extract_players_from_table(table, "K"), [])
        self.assertEqual(_extract_players_from_table(table, "DST"), [])


if __name__ == "__main__":
    unittest.main()
