"""What a Yahoo settings paste has to contain before it becomes a league.

The paste is the route left to a user whose app Yahoo has not approved for API
access, and every value the parser reads has a default behind it. That makes
the *result* useless as evidence that anything was read — "lorem ipsum" used to
import as a 10-team league with the stock roster and scoring — so these tests
pin what must have been found in the text itself, and that a partial paste is
still enough.
"""
import unittest

import tests.test_yahoo as pinned
from draft_assistant.importers.yahoo import parse_settings_text


DEFAULT_ROSTER = {"QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 1, "K": 1, "DST": 1, "BN": 6}

# The roster table on its own, in the line-per-position layout the settings
# page uses (tests/test_yahoo.py pins the same rows inside a full paste).
ROSTER_LINES = "\n".join([
    "Quarterback        1",
    "Running Back       2",
    "Wide Receiver      2",
    "Tight End          1",
    "W/R/T              1",
    "Kicker             1",
    "Defense/Special Teams 1",
    "Bench              6",
])


class TestRosterRowIsNotATeamCount(unittest.TestCase):
    def test_defense_special_teams_slot_does_not_set_the_league_size(self):
        # "Defense/Special Teams 1" ends in "Teams 1". With no team-count row
        # ahead of it, that made a one-team league out of a roster table.
        info = parse_settings_text(ROSTER_LINES)
        self.assertEqual(info["numTeams"], 10)
        self.assertEqual(info["rosterSlots"]["DST"], 1)

    def test_team_count_labels_still_read(self):
        for row in ("Max Teams: 12", "Teams: 12", "Number of Teams 12", "Max Teams\n12"):
            with self.subTest(row=row):
                self.assertEqual(parse_settings_text(row + "\n" + ROSTER_LINES)["numTeams"], 12)

    def test_real_team_count_after_the_roster_table_still_wins(self):
        self.assertEqual(parse_settings_text(ROSTER_LINES + "\nMax Teams 14")["numTeams"], 14)


class TestUnrecognizableTextIsRejected(unittest.TestCase):
    def assert_rejected(self, text):
        with self.assertRaisesRegex(ValueError, "does not look like a Yahoo league settings page"):
            parse_settings_text(text)

    def test_prose_is_not_a_league(self):
        for text in (
            "lorem ipsum dolor sit amet",
            "This is not a league settings page",
            "Hey, can you set the league up for me?\nThanks!\n\nSent from my phone",
            "https://football.fantasysports.yahoo.com/f1/828682/settings",
            "12345",
        ):
            with self.subTest(text=text):
                self.assert_rejected(text)

    def test_punctuation_is_not_a_league(self):
        for text in ("!!! ... ---", "?", "-----\n=====\n-----", "• • •", "( ) [ ] : :"):
            with self.subTest(text=text):
                self.assert_rejected(text)

    def test_blank_text_keeps_its_own_message(self):
        for text in ("", "   \n\t  "):
            with self.subTest(text=text):
                with self.assertRaisesRegex(ValueError, "Please paste"):
                    parse_settings_text(text)

    def test_the_error_says_what_to_paste(self):
        with self.assertRaises(ValueError) as caught:
            parse_settings_text("lorem ipsum dolor sit amet")
        message = str(caught.exception)
        self.assertIn("League > Settings", message)
        self.assertIn("select the whole page", message)

    def test_page_chrome_without_the_settings_table_is_rejected(self):
        # The wrong Yahoo page: every navigation link the full-page paste
        # carries, and none of the rows it is pasted for.
        self.assert_rejected("\n".join([
            "Yahoo Fantasy", "Sports", "Fantasy", "Mail", "Sign In",
            "Home", "My Team", "League", "Players", "Scores", "Draft",
            "Terms of Service", "Privacy Policy", "Help",
        ]))

    def test_a_numbered_list_is_not_settings(self):
        # Numbered lines are collected as team names when a league is being
        # read, but any list has them — they are not what makes text a league.
        self.assert_rejected("1. Buy milk\n2. Call the vet\n3. Renew passport")


class TestStrayKeywordIsNotAField(unittest.TestCase):
    """A settings row opens with its label and carries a value the parser can
    read. A sentence that merely mentions "teams" has neither, and must not be
    enough to import a league of defaults."""

    def test_keywords_inside_sentences_are_rejected(self):
        for text in (
            "All teams must set their lineups before Sunday",      # no count at all
            "I think teams 3 and 4 are stacked this year",          # a count, mid-sentence
            "what should my league name be this year",
            "which draft type do you like, snake or auction",
            "Draft type is something I never understood",           # leads, names no format
            "Our roster positions are still undecided",
        ):
            with self.subTest(text=text):
                with self.assertRaisesRegex(ValueError, "does not look like"):
                    parse_settings_text(text)

    def test_the_same_labels_as_rows_are_read(self):
        self.assertEqual(parse_settings_text("Teams: 12")["numTeams"], 12)
        self.assertEqual(parse_settings_text("Max Teams\n12")["numTeams"], 12)
        self.assertEqual(parse_settings_text("League Name: Sunday Football")["name"], "Sunday Football")
        self.assertEqual(parse_settings_text("League: Sunday Football")["name"], "Sunday Football")
        self.assertEqual(parse_settings_text("Draft Type: Live Salary Cap Draft")["draftType"], "auction")
        self.assertEqual(parse_settings_text("Draft Type\nLive Standard Draft")["draftType"], "snake")

    def test_bullets_and_indentation_do_not_hide_a_row(self):
        for text in ("- Max Teams: 12", "• Max Teams: 12", "* Max Teams 12", "note:\n    Max Teams: 12"):
            with self.subTest(text=text):
                self.assertEqual(parse_settings_text(text)["numTeams"], 12)

    def test_a_sentence_ahead_of_a_real_row_does_not_hide_it(self):
        info = parse_settings_text("All teams must set their lineups before Sunday\nMax Teams: 12")
        self.assertEqual(info["numTeams"], 12)

    def test_a_row_starts_after_any_line_break_the_parser_splits_on(self):
        # The roster and scoring sections read str.splitlines() lines, which
        # also end at a bare "\r", a soft return or U+2028. A settings row
        # after one of those was read and then refused as unrecognized,
        # because "^" only knows "\n".
        for name, line_break in (("CR", "\r"), ("CRLF", "\r\n"), ("soft return", "\x0b"),
                                 ("form feed", "\x0c"), ("NEL", "\x85"), ("U+2028", " ")):
            with self.subTest(line_break=name):
                def paste(row):
                    return parse_settings_text("Lega di Paca" + line_break + row)
                self.assertEqual(paste("Max Teams: 12")["numTeams"], 12)
                self.assertEqual(paste("Draft Type: Live Salary Cap Draft")["draftType"], "auction")
                self.assertEqual(paste("League Name: Sunday Football")["name"], "Sunday Football")
                # ...and a sentence on that line is still only a sentence.
                with self.assertRaisesRegex(ValueError, "does not look like"):
                    paste("I think teams 3 and 4 are stacked this year")


class TestPartialPastesStillImport(unittest.TestCase):
    """Whatever the text does not say keeps its default. Only text that says
    nothing is refused."""

    def assert_defaults_except(self, info, *changed):
        expected = {"numTeams": 10, "draftType": "snake", "rosterSlots": DEFAULT_ROSTER,
                    "scoringType": "half-ppr"}
        for key, value in expected.items():
            if key not in changed:
                self.assertEqual(info[key], value, key)

    def test_scoring_table_alone(self):
        layouts = {
            "inline": "Passing Yards: 20 yards per point\nPassing Touchdowns: 6\nReceptions: 1",
            "yahoo table": "Passing Yards\nYahoo Default\n\t20 yards per point \t25 yards per point\n"
                           "Passing Touchdowns \t6 \t\nReceptions \t1 \t",
            # A browser table copy puts the label and its value on separate lines.
            "one cell per line": "Passing Yards\n20 yards per point\nPassing Touchdowns\n6\nReceptions\n1",
        }
        for layout, text in layouts.items():
            with self.subTest(layout=layout):
                info = parse_settings_text(text)
                self.assertEqual(info["scoring"]["pass_yd"], 0.05)
                self.assertEqual(info["scoring"]["pass_td"], 6.0)
                self.assertEqual(info["scoringType"], "ppr")
                self.assert_defaults_except(info, "scoringType")

    def test_a_single_scoring_row_is_enough(self):
        info = parse_settings_text("Receptions\n0")
        self.assertEqual(info["scoringType"], "standard")
        self.assert_defaults_except(info, "scoringType")

    def test_roster_positions_alone(self):
        expected = {"QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 1, "K": 1, "DST": 1, "BN": 6}
        layouts = {
            "list": "Roster Positions: QB, WR, WR, RB, RB, TE, W/R/T, K, DEF, BN, BN, BN, BN, BN, BN",
            "list, one cell per line": "Roster Positions\nQB, WR, WR, RB, RB, TE, W/R/T, K, DEF, BN, BN, BN, BN, BN, BN",
            "line per position": ROSTER_LINES,
            "one slot per line": "QB\nRB\nRB\nWR\nWR\nTE\nW/R/T\nK\nDEF\nBN\nBN\nBN\nBN\nBN\nBN",
        }
        for layout, text in layouts.items():
            with self.subTest(layout=layout):
                info = parse_settings_text(text)
                self.assertEqual({k: v for k, v in info["rosterSlots"].items() if v}, expected)
                self.assertEqual(info["scoring"]["rec"], 0.5)
                self.assert_defaults_except(info, "rosterSlots")

    def test_a_single_settings_field_is_enough(self):
        self.assert_defaults_except(parse_settings_text("Max Teams: 12"), "numTeams")
        self.assert_defaults_except(parse_settings_text("Draft Type: Live Salary Cap Draft"), "draftType")
        self.assert_defaults_except(parse_settings_text("League Name: Sunday Football"))

    def test_full_pages_still_import(self):
        real = parse_settings_text(pinned.TestOverriddenScoringRows.REAL)
        self.assertEqual((real["name"], real["numTeams"], real["scoringType"]), ("Lega di Paca", 16, "custom"))
        lines = parse_settings_text(pinned.TestSettingsTextRosterParsing.LINE_LAYOUT)
        self.assertEqual((lines["name"], lines["numTeams"]), ("Anonymous", 12))
        self.assertEqual(lines["rosterSlots"]["BN"], 6)

    def test_incomplete_pastes_are_not_rejected(self):
        """The unmerged Yahoo verification branch refuses a paste that lacks a
        league name, a roster or any scoring. This parser fills those from
        defaults on purpose — only *nothing at all* is an error here."""
        no_name = parse_settings_text("League ID: 123\nMax Teams: 10\nRoster Positions: QB\nReceptions: 1")
        self.assertEqual(no_name["name"], "Yahoo League")
        self.assertEqual(no_name["rosterSlots"]["QB"], 1)

        no_roster = parse_settings_text("League Name: Example\nMax Teams: 10\nPassing Touchdowns: 6")
        self.assertEqual(no_roster["rosterSlots"], DEFAULT_ROSTER)
        self.assertEqual(no_roster["scoring"]["pass_td"], 6.0)

        no_scoring = parse_settings_text("League Name: Example\nMax Teams: 10\nRoster Positions: QB, RB, WR")
        self.assertEqual(no_scoring["scoringType"], "half-ppr")
        self.assertEqual((no_scoring["rosterSlots"]["QB"], no_scoring["rosterSlots"]["BN"]), (1, 0))


if __name__ == "__main__":
    unittest.main()
