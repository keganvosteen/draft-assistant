"""Partial Yahoo settings pastes: what is read from the text, and what is not."""
import unittest

from draft_assistant.importers.yahoo import parse_settings_text


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


if __name__ == "__main__":
    unittest.main()
