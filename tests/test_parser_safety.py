"""Input bounds and offline regressions for the six slow-parser alert families."""
import json
import subprocess
import sys
import textwrap
import unittest
from pathlib import Path
from unittest import mock

from draft_assistant.draft_paste_parser import (
    _remove_parenthetical_annotations,
    _trim_name_delimiters,
    clean_line_text,
    parse_draft_text,
)
from draft_assistant.fuzzy import normalize_player_name
from draft_assistant.importers.yahoo import _numbered_team_name, parse_settings_text
from draft_assistant.input_limits import (
    MAX_PASTED_LINE_CHARS,
    MAX_PASTED_LINES,
    MAX_PASTED_TEXT_CHARS,
    validate_pasted_text,
)


class TestParserBoundaries(unittest.TestCase):
    def test_both_parsers_reject_documents_outside_each_limit(self):
        invalid = (
            ("x" * (MAX_PASTED_TEXT_CHARS + 1), "characters"),
            ("x" * (MAX_PASTED_LINE_CHARS + 1), "lines must"),
            ("x\n" * (MAX_PASTED_LINES + 1), "lines"),
            (None, "must be text"),
        )
        for parser in (parse_settings_text, lambda text: parse_draft_text(text, [])):
            for text, message in invalid:
                with self.subTest(parser=parser, message=message):
                    with self.assertRaisesRegex(ValueError, message):
                        parser(text)

    def test_rejects_draft_input_before_scanning_players(self):
        with mock.patch("draft_assistant.draft_paste_parser.match_player_against_candidates") as match:
            with self.assertRaises(ValueError):
                parse_draft_text("x\n" * (MAX_PASTED_LINES + 1), [{"name": "Test"}])
        match.assert_not_called()

    def test_direct_line_parser_enforces_line_limit(self):
        with self.assertRaisesRegex(ValueError, "lines must"):
            clean_line_text("(" * (MAX_PASTED_LINE_CHARS + 1))

    def test_limits_include_blank_lines_and_accept_boundaries(self):
        self.assertEqual(validate_pasted_text("x\n" * MAX_PASTED_LINES), ["x"] * MAX_PASTED_LINES)
        self.assertEqual(validate_pasted_text(" " * MAX_PASTED_LINE_CHARS), [" " * MAX_PASTED_LINE_CHARS])
        # Exactly the document bound, with legal individual lines/count.
        legal = (("x" * 199 + "\n") * (MAX_PASTED_TEXT_CHARS // 200))
        self.assertEqual(len(legal), MAX_PASTED_TEXT_CHARS)
        self.assertTrue(validate_pasted_text(legal))


class TestParserCompatibility(unittest.TestCase):
    def test_suffix_normalization_only_removes_one_final_suffix_token(self):
        for name, expected in (
            ("Marvin Harrison JR.", "marvin harrison"),
            ("Odell\tBeckham\u2003Jr", "odell beckham"),
            ("Will Fuller V", "will fuller"),
            ("John Jr. III", "john jr."),
            ("Jr.", "jr."),
            ("John II Smith", "john ii smith"),
        ):
            with self.subTest(name=name):
                self.assertEqual(normalize_player_name(name), expected)
        self.assertEqual(normalize_player_name("Odell Beckham Jr.", compact=True), "odellbeckham")

    def test_annotations_preserve_unclosed_text_and_previous_nested_behavior(self):
        for text, expected in (
            ("Player (ATL - WR) (Round 1)", "Player  "),
            ("Player (((unclosed", "Player (((unclosed"),
            ("Player (nested (note))", "Player )"),
            ("Player (a) (unclosed", "Player  (unclosed"),
        ):
            with self.subTest(text=text):
                self.assertEqual(_remove_parenthetical_annotations(text), expected)

    def test_unicode_whitespace_and_delimiter_trimming(self):
        self.assertEqual(_trim_name_delimiters("\u2003--:.Amon-Ra St. Brown...\t"), "Amon-Ra St. Brown")
        self.assertEqual(_trim_name_delimiters("--\u2003:.."), "")
        self.assertEqual(clean_line_text("Pick 5: CeeDee Lamb (DAL - WR)"), (5, "CeeDee Lamb"))

    def test_yahoo_team_names_with_optional_managers_and_malformed_rows(self):
        info = parse_settings_text("\n".join([
            "League Name: Parser League", "Max Teams: 12",
            "1. Team Alpha (Manager One)", "2) O'Brien's Team (Manager (co-owner))",
            "3. Team Bravo", "4. Bad Name!", "5. Unclosed (Manager",
            "6. Team (Manager) extra", "7. Team(Manager)",
        ]))
        self.assertEqual(info["teamNames"], ["Team Alpha", "O'Brien's Team", "Team Bravo"])

    def test_team_index_requires_digits_punctuation_and_whitespace(self):
        for line in ("1 Team", "1.Team", ". Team", "12345", "12345!", "1."):
            with self.subTest(line=line):
                self.assertIsNone(_numbered_team_name(line))
        self.assertEqual(_numbered_team_name("12.\tTeam Alpha"), "Team Alpha")
        self.assertEqual(_numbered_team_name("\u0661) Team Bravo"), "Team Bravo")

    def test_yahoo_roster_labels_reject_partial_labels_and_unclosed_annotations(self):
        info = parse_settings_text("\n".join([
            "League Name: Parser League", "Wide Receiver (WR): 3", "W/R/T\t1",
            "Quarterback (QB) 1", "Bench\t5", "Kicker-extra 8", "RB (unclosed",
        ]))
        roster = info["rosterSlots"]
        self.assertEqual((roster["WR"], roster["QB"], roster["BN"], roster["FLEX"]), (3, 1, 5, 1))
        self.assertEqual((roster["RB"], roster["K"]), (0, 0))


class TestMalformedInputScaling(unittest.TestCase):
    def test_all_alert_families_scale_without_quadratic_backtracking(self):
        # A child process ensures a future regression cannot hang the test run.
        # Exercise the algorithms beyond the line bound as well, so the input
        # guard cannot mask a reintroduced backtracking pattern.
        code = textwrap.dedent("""
            import json
            import timeit
            from unittest import mock
            from draft_assistant.fuzzy import normalize_player_name
            from draft_assistant.draft_paste_parser import (
                _remove_parenthetical_annotations, _trim_name_delimiters,
            )
            from draft_assistant.importers.yahoo import (
                _roster_position_row, _numbered_team_name, parse_settings_text,
            )
            def rejected(text):
                # Deciding that a paste holds no settings at all means every
                # label search has run over the whole of it and missed.
                try:
                    parse_settings_text(text)
                except ValueError:
                    return
                raise AssertionError('unrecognizable settings text was accepted')

            cases = {
                'suffix': (normalize_player_name, lambda n: 'Player' + ' ' * n + '!'),
                'parentheses': (_remove_parenthetical_annotations, lambda n: '(' * n + '!'),
                'delimiters': (_trim_name_delimiters, lambda n: 'Player' + '-' * n + '!'),
                'roster': (_roster_position_row, lambda n: 'WR' + ' ' * n + '!'),
                # The team count keeps this a recognizable paste, so the scoring
                # scan is timed through to a result rather than to a rejection.
                'scoring': (parse_settings_text,
                            lambda n: 'Max Teams: 12\\nPassing Yards' + ' ' * n + '!'),
                'team_name': (_numbered_team_name, lambda n: '1. Team' + ' ' * n + '!'),
                'team_index': (_numbered_team_name, lambda n: '9' * n + '!'),
                'stray_label': (rejected, lambda n: 'Teams' + ' ' * n + '!'),
                'row_start': (rejected, lambda n: '-' * n + 'Teams!'),
            }
            timings = {}
            with mock.patch('draft_assistant.importers.yahoo.validate_pasted_text'):
                for name, (function, make_input) in cases.items():
                    durations = []
                    for size in (2048, 8192):
                        value = make_input(size)
                        durations.append(min(timeit.repeat(
                            lambda: function(value), number=3, repeat=3,
                        )) / 3)
                    timings[name] = durations
            print(json.dumps(timings))
        """)
        result = subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True,
            cwd=Path(__file__).resolve().parents[1], timeout=20, check=True,
        )
        timings = json.loads(result.stdout)
        self.assertEqual(len(timings), 9)
        for family, (small, large) in timings.items():
            with self.subTest(family=family):
                # Four times the input may take a little more than four times
                # the work; allow scheduling noise without accepting 16x growth.
                self.assertLess(large, small * 10 + 0.015, (family, small, large))


if __name__ == "__main__":
    unittest.main()
