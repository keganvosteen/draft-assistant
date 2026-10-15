"""Every "current season" default follows the NFL season, not the calendar.

context.default_season() names a season for the year it kicked off, so January
and February still belong to last year's season and March 1 rolls over. The
history weighting and the CLI collectors kept their own defaults: the calendar
year, or a hard-coded 2026 that would have pulled last season's board next
year. Each test pins two dates in different seasons, so a default that ignores
the season cannot pass both whatever today's date is.
"""
import os
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

from draft_assistant.historical import HISTORY_STALENESS_DECAY, history_recency_factor
from tests.test_season_calendar import _today_is

# 2027-01-03 is week 17 of the 2026 season; 2027-07-15 is the 2027 preseason.
IN_SEASON_2026 = (2027, 1, 3)
PRESEASON_2027 = (2027, 7, 15)


class TestHistoryRecencyDefault(unittest.TestCase):
    def test_default_season_is_the_nfl_season(self):
        history = {2025: {"rush_yd": 900.0}}
        with _today_is(*IN_SEASON_2026):
            # 2025 is the last completed season while 2026 is being played.
            self.assertEqual(history_recency_factor(history), 1.0)
        with _today_is(*PRESEASON_2027):
            # Once 2027 is the season, a history that stops at 2025 is stale.
            self.assertEqual(history_recency_factor(history), HISTORY_STALENESS_DECAY)


class TestCliSeasonDefaults(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self._orig = os.getcwd()
        os.chdir(self._tmp)
        os.makedirs("data", exist_ok=True)

    def tearDown(self):
        os.chdir(self._orig)
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _season_used(self, command, target, keyword, today):
        from draft_assistant import cli

        with _today_is(*today), patch(target, return_value=[]) as fetch, \
                patch.object(sys, "argv", ["draft-assistant", command]), \
                patch("builtins.print"):
            cli.main()
        call = fetch.call_args
        return call.kwargs[keyword] if keyword else call.args[0]

    def _assert_follows_season(self, command, target, keyword=None):
        for today, season in ((IN_SEASON_2026, 2026), (PRESEASON_2027, 2027)):
            with self.subTest(command=command, today=today):
                self.assertEqual(self._season_used(command, target, keyword, today), season)

    def test_collect_all(self):
        self._assert_follows_season(
            "collect-all", "draft_assistant.collectors.combined.collect_all", "current_season")

    def test_collect(self):
        self._assert_follows_season(
            "collect", "draft_assistant.collectors.sleeper_historical.collect_players", "current_season")

    def test_pull_fftoday(self):
        self._assert_follows_season("pull-fftoday", "draft_assistant.cli.fetch_all_fftoday")


if __name__ == "__main__":
    unittest.main()
