"""What NFL season and week it is, and that the whole app gives one answer.

The season used to be the calendar year and the week a count of 7-day blocks
from September 1 that returned 1 for anything before September. The regular
season runs into January -- week 17 straddles New Year and week 18 follows it
-- so on January 1 the app decided it was week 1 of a season with no games, in
the middle of fantasy championship week. Separately, the news cache was read
back with whatever season it had last been refreshed for, so a cache left over
from last autumn made `/api/players` judge this year's byes against last year,
report none, and offer a "Load bye weeks" repair that re-stamped the board from
last year's schedule.

Every date here is pinned. Nothing may depend on the day the suite runs.
"""
import json
import os
import shutil
import tempfile
import time
import unittest
from datetime import date
from unittest import mock
from unittest.mock import patch

from draft_assistant.config import save_config
from draft_assistant.context import (
    context_from_dict,
    current_bye_week,
    default_season,
    default_week,
    is_stale,
    load_context,
    save_context,
    season_kickoff,
)
from draft_assistant.importers import free_sources as fs
from draft_assistant.models import LeagueConfig, Player, PlayerContext, PlayerSignal
from draft_assistant.profiles import ProfilePaths
from draft_assistant.storage import load_players, save_players
from tests.test_cli_refresh_byes import SCHEDULE
from tests.test_web_server import _ServerFixture


def _today_is(year, month, day):
    """A stand-in for ``context.date`` whose ``today()`` never moves."""
    class Pinned(date):
        @classmethod
        def today(cls):
            return cls(year, month, day)
    return patch("draft_assistant.context.date", Pinned)


#: (date, season, week), written out from the real calendar rather than derived
#: from the function under test. Kickoffs were Thursday 2024-09-05, 2025-09-04
#: and 2026-09-10; fantasy weeks run Tuesday through Monday.
CALENDAR = {
    2024: [
        (date(2024, 3, 1), 2024, 1),    # the rollover day: draft prep begins
        (date(2024, 8, 31), 2024, 1),
        (date(2024, 9, 4), 2024, 1),    # the day before kickoff
        (date(2024, 9, 5), 2024, 1),    # kickoff
        (date(2024, 9, 9), 2024, 1),    # Monday night closes week 1
        (date(2024, 9, 10), 2024, 2),
        (date(2024, 10, 28), 2024, 8),  # a mid-season Monday night...
        (date(2024, 10, 29), 2024, 9),  # ...and the Tuesday after it
        (date(2024, 12, 29), 2024, 17),  # week 17 Sunday
        (date(2024, 12, 30), 2024, 17),
        (date(2024, 12, 31), 2024, 18),  # a Tuesday: week 18 opens on New Year's Eve
        (date(2025, 1, 1), 2024, 18),
        (date(2025, 1, 5), 2024, 18),   # week 18 Sunday
        (date(2025, 1, 7), 2024, 18),   # the regular season is over; still 18
        (date(2025, 2, 15), 2024, 18),
        (date(2025, 2, 28), 2024, 18),  # the day before the rollover
        (date(2025, 3, 1), 2025, 1),
    ],
    2025: [
        (date(2025, 8, 31), 2025, 1),
        (date(2025, 9, 3), 2025, 1),
        (date(2025, 9, 4), 2025, 1),
        (date(2025, 9, 8), 2025, 1),
        (date(2025, 9, 9), 2025, 2),
        (date(2025, 10, 20), 2025, 7),
        (date(2025, 10, 21), 2025, 8),
        (date(2025, 12, 28), 2025, 17),
        (date(2025, 12, 29), 2025, 17),
        (date(2025, 12, 30), 2025, 18),
        (date(2025, 12, 31), 2025, 18),
        (date(2026, 1, 1), 2025, 18),
        (date(2026, 1, 4), 2025, 18),
        (date(2026, 1, 6), 2025, 18),
        (date(2026, 2, 15), 2025, 18),
        (date(2026, 2, 28), 2025, 18),
        (date(2026, 3, 1), 2026, 1),
    ],
    2026: [
        (date(2026, 8, 31), 2026, 1),
        (date(2026, 9, 9), 2026, 1),
        (date(2026, 9, 10), 2026, 1),
        (date(2026, 9, 14), 2026, 1),
        (date(2026, 9, 15), 2026, 2),
        (date(2026, 10, 13), 2026, 6),
        (date(2026, 10, 19), 2026, 6),
        (date(2026, 10, 20), 2026, 7),
        (date(2026, 12, 31), 2026, 17),  # week 17 spans the New Year...
        (date(2027, 1, 1), 2026, 17),
        (date(2027, 1, 3), 2026, 17),   # ...and is played on this Sunday
        (date(2027, 1, 4), 2026, 17),
        (date(2027, 1, 5), 2026, 18),
        (date(2027, 1, 10), 2026, 18),  # week 18 Sunday
        (date(2027, 1, 12), 2026, 18),
        (date(2027, 2, 14), 2026, 18),  # Super Bowl Sunday
        (date(2027, 2, 28), 2026, 18),
        (date(2027, 3, 1), 2027, 1),
    ],
}


class TestSeasonAndWeek(unittest.TestCase):
    def test_week_one_opens_on_the_thursday_after_the_first_monday_of_september(self):
        for season, kickoff in ((2021, date(2021, 9, 9)), (2022, date(2022, 9, 8)),
                                (2023, date(2023, 9, 7)), (2024, date(2024, 9, 5)),
                                (2025, date(2025, 9, 4)), (2026, date(2026, 9, 10))):
            with self.subTest(season=season):
                self.assertEqual(season_kickoff(season), kickoff)
                self.assertEqual(kickoff.strftime("%A"), "Thursday")

    def test_season_and_week_on_every_boundary(self):
        for season, days in CALENDAR.items():
            for day, expected_season, expected_week in days:
                with self.subTest(season=season, day=day.isoformat()):
                    self.assertEqual(
                        (default_season(day), default_week(day)),
                        (expected_season, expected_week))

    def test_a_leap_day_still_belongs_to_the_season_that_just_ended(self):
        self.assertEqual((default_season(date(2028, 2, 29)), default_week(date(2028, 2, 29))), (2027, 18))
        self.assertEqual((default_season(date(2028, 3, 1)), default_week(date(2028, 3, 1))), (2028, 1))

    def test_the_week_only_ever_changes_on_a_tuesday(self):
        # 7-day blocks from September 1 moved the boundary to whatever weekday
        # the month happened to start on: Sundays and Mondays in 2024, Mondays
        # in 2025, and a full week early throughout 2026.
        for season in (2024, 2025, 2026):
            day = date(season, 3, 1)
            while default_season(day) == season:
                tomorrow = date.fromordinal(day.toordinal() + 1)
                if default_season(tomorrow) == season and default_week(tomorrow) != default_week(day):
                    self.assertEqual(tomorrow.strftime("%A"), "Tuesday", tomorrow)
                    self.assertEqual(default_week(tomorrow), default_week(day) + 1, tomorrow)
                day = tomorrow

    def test_no_argument_means_today(self):
        with _today_is(2027, 1, 3):
            self.assertEqual((default_season(), default_week()), (2026, 17))
        with _today_is(2027, 3, 1):
            self.assertEqual((default_season(), default_week()), (2027, 1))

    def test_a_pull_and_the_cli_agree_with_the_app_about_the_season(self):
        # `refresh-byes` on the command line defaults to the projection season
        # and POST /api/refresh-byes to the app's: one repair, one season. The
        # stats baseline is always the season before the board's.
        for days in CALENDAR.values():
            for day, season, _week in days:
                with self.subTest(day=day.isoformat()):
                    self.assertEqual(fs.default_projection_season(day), season)
                    self.assertEqual(fs.default_stats_season(day), season - 1)
        with _today_is(2027, 1, 3):
            self.assertEqual((fs.default_projection_season(), fs.default_stats_season()), (2026, 2025))


def _signal(player_id, kind, value):
    return PlayerSignal(
        player_id=player_id, kind=kind, value=value, source="sleeper_players",
        observed_at="2025-11-04T12:00:00+00:00", attribution="Sleeper")


def _cache(season, week):
    """A refreshed news cache that says the board's best player has left the league."""
    return PlayerContext(
        season, week, refreshed_at="2025-11-04T12:00:00+00:00",
        signals=[_signal("sleeper:1", "roster_status", "Inactive")],
        source_health={"sleeper_players": {
            "ok": True, "records": 1, "refreshed_at": "2025-11-04T12:00:00+00:00"}},
    )


class TestTheCacheFollowsTheSeason(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self._tmp, ignore_errors=True)
        self.path = os.path.join(self._tmp, "player_context.json")

    def test_last_seasons_cache_reads_as_no_news_for_this_season(self):
        save_context(_cache(2025, 9), self.path)
        with _today_is(2027, 1, 3):
            context = load_context(self.path)
        self.assertEqual((context.season, context.selected_week), (2026, 17))
        self.assertEqual(context.signals, [])
        self.assertEqual(context.source_health, {})
        self.assertIsNone(context.refreshed_at)
        self.assertTrue(is_stale(context), "an unrefreshed context has to say so")

    def test_this_seasons_cache_survives_the_new_year(self):
        # Saved in December, read in January: the same season. On the calendar
        # year this cache stopped matching at midnight on December 31.
        save_context(_cache(2026, 16), self.path)
        for today in ((2026, 12, 31), (2027, 1, 1), (2027, 1, 10), (2027, 2, 28)):
            with self.subTest(today=today), _today_is(*today):
                context = load_context(self.path)
                self.assertEqual(context.season, 2026)
                self.assertEqual(len(context.signals), 1)
                # An unnamed week keeps the one the cache was fetched for.
                self.assertEqual(context.selected_week, 16)
        with _today_is(2027, 3, 1):
            self.assertEqual(load_context(self.path).signals, [], "and stops on the rollover")

    def test_a_cache_from_a_later_season_is_not_this_seasons_either(self):
        save_context(_cache(2027, 1), self.path)
        with _today_is(2026, 10, 13):
            context = load_context(self.path)
        self.assertEqual((context.season, context.selected_week, context.signals), (2026, 6, []))

    def test_a_named_season_still_reads_its_own_cache(self):
        save_context(_cache(2025, 9), self.path)
        with _today_is(2027, 1, 3):
            context = load_context(self.path, season=2025)
        self.assertEqual((context.season, context.selected_week), (2025, 9))
        self.assertEqual(len(context.signals), 1)

    def test_a_missing_or_unreadable_cache_is_this_season_with_no_news(self):
        with _today_is(2027, 1, 3):
            self.assertEqual(load_context(self.path).season, 2026)
            with open(self.path, "w", encoding="utf-8") as handle:
                handle.write("{not json")
            context = load_context(self.path)
        self.assertEqual((context.season, context.selected_week, context.signals), (2026, 17, []))


#: Week 17 Sunday of the 2026 season, on the far side of the New Year: fantasy
#: championship week, and the day the calendar-year season was most wrong.
TODAY = (2027, 1, 3)
SEASON, WEEK = 2026, 17
LEAGUE = {"id": "manual", "name": "Manual league", "numTeams": 2, "draftPosition": 1,
          "sims": 2, "rosterSlots": {"QB": 1, "RB": 1, "WR": 1, "TE": 0, "FLEX": 0, "BN": 1}}


def _stamped_board(season):
    players = [
        Player("sleeper:1", "Chiefs Back", "RB", team="KC", adp=1.0,
               projections={"rush_yd": 1400.0}, metadata={"sleeper_id": "1"}),
        Player("sleeper:2", "Lions Receiver", "WR", team="DET", adp=2.0, projections={"rec_yd": 1300.0}),
        Player("sleeper:3", "Bills Passer", "QB", team="BUF", adp=3.0, projections={"pass_yd": 4500.0}),
        Player("sleeper:4", "Niners Back", "RB", team="SF", adp=4.0, projections={"rush_yd": 900.0}),
        Player("sleeper:5", "Rams Receiver", "WR", team="LAR", adp=5.0, projections={"rec_yd": 800.0}),
        Player("sleeper:6", "Eagles Passer", "QB", team="PHI", adp=6.0, projections={"pass_yd": 3500.0}),
    ]
    # The stamp a pull writes, through the function a pull writes it with.
    fs.apply_schedule_byes(players, SCHEDULE, season)
    return players


BYES = {player.name: SCHEDULE[player.team] for player in _stamped_board(SEASON)}


class TestEndpointsAgreeOnTheSeason(_ServerFixture):
    """A board stamped for this season, beside a news cache left from the last.

    Reproduced on a live server before the fix: `/api/players` reported
    `byeWeek: null` for all 1,256 stamped players, the bye-weeks notice
    appeared, and one click on it moved every stamp from 2026 to 2025.
    """

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self._tmp, ignore_errors=True)
        self.board = os.path.join(self._tmp, "data", "projections.json")
        self.cache = os.path.join(self._tmp, "data", "player_context.json")
        config_path = os.path.join(self._tmp, "league.config.json")
        paths = ProfilePaths(
            "default", self._tmp, config_path,
            os.path.join(self._tmp, "draft_state.json"), self.board)
        self._patch("draft_assistant.web.server.ensure_profile", return_value=paths)
        self._patch("draft_assistant.context.context_path", return_value=self.cache)
        today = _today_is(*TODAY)
        today.start()
        self.addCleanup(today.stop)
        self.schedule = self._patch(
            "draft_assistant.importers.free_sources._fetch_nflverse_byes",
            return_value=dict(SCHEDULE))
        for module in ("draft_assistant.importers.free_sources", "draft_assistant.context"):
            self._patch(f"{module}.urlopen", side_effect=AssertionError("unexpected network"))
        save_config(LeagueConfig(
            teams=2, roster=dict(LEAGUE["rosterSlots"]),
            scoring={"pass_yd": 0.04, "rush_yd": 0.1, "rec_yd": 0.1},
            provider={}, draft={"slot": 1, "rollout_sims": 2}), config_path)
        save_players(_stamped_board(SEASON), self.board)
        save_context(_cache(SEASON - 1, 9), self.cache)

    def _patch(self, target, **kwargs):
        patcher = patch(target, **kwargs)
        self.addCleanup(patcher.stop)
        return patcher.start()

    def json(self, method, path, body=None):
        status, raw = self.request(method, path, body)
        self.assertEqual(status, 200, raw)
        return json.loads(raw)

    def players(self):
        return {player["name"]: player for player in self.json("GET", "/api/players")}

    def stamps(self):
        return {player.metadata.get("bye_season") for player in load_players(self.board)}

    def cached(self):
        with open(self.cache, encoding="utf-8") as handle:
            return context_from_dict(json.load(handle))

    def refresh(self, body):
        """POST /api/context/refresh with every feed stubbed, and wait for it."""
        feeds = {name: mock.Mock(return_value=0) for name in (
            "_refresh_sleeper_players", "_refresh_sleeper_trending", "_refresh_sleeper_weekly",
            "_refresh_sleeper_actuals", "_refresh_nflverse_injuries", "_refresh_nflverse_depth",
            "_refresh_nflverse_stats", "_refresh_nflverse_snaps",
        )}
        with patch.multiple("draft_assistant.context", **feeds):
            started = self.json("POST", "/api/context/refresh", body)
            for _ in range(200):
                task = self.json("GET", f"/api/task/{started['taskId']}")
                if task["status"] != "running":
                    break
                time.sleep(0.02)
        self.assertEqual(task["status"], "done", task)
        return task["result"]

    def test_a_stale_cache_does_not_hide_a_correctly_stamped_boards_byes(self):
        players = self.players()
        self.assertEqual({name: row["byeWeek"] for name, row in players.items()}, BYES)
        # Last season's news is not this season's: the player it called
        # inactive is judged on no news at all, which the gate reads as eligible.
        self.assertIsNone(players["Chiefs Back"]["availability"])
        self.assertTrue(players["Chiefs Back"]["eligible"])
        self.assertEqual(players["Chiefs Back"]["signals"], [])

    def test_load_bye_weeks_stamps_the_season_players_are_judged_against(self):
        body = self.json("POST", "/api/refresh-byes", {})
        self.assertEqual(body["season"], SEASON)
        self.assertEqual((body["verified"], body["changed"]), (len(BYES), 0))
        self.schedule.assert_called_once_with(SEASON)
        self.assertEqual(self.stamps(), {SEASON}, "the stamps must stay on the current season")
        self.assertEqual({name: row["byeWeek"] for name, row in self.players().items()}, BYES)

    def test_a_board_stamped_for_last_season_is_repaired_onto_this_one(self):
        # The other direction: whatever season the default stamps, the very
        # next /api/players has to show it -- by construction, not by luck.
        save_players(_stamped_board(SEASON - 1), self.board)
        self.assertEqual(set(row["byeWeek"] for row in self.players().values()), {None})
        self.assertEqual(self.json("POST", "/api/refresh-byes", {})["season"], SEASON)
        self.assertEqual(self.stamps(), {SEASON})
        self.assertEqual({name: row["byeWeek"] for name, row in self.players().items()}, BYES)

    def test_the_news_endpoint_reports_this_season_and_that_it_has_no_news(self):
        context = self.json("GET", "/api/context")
        self.assertEqual((context["season"], context["week"]), (SEASON, WEEK))
        self.assertTrue(context["stale"])
        self.assertEqual((context["signalCount"], context["signals"]), (0, []))
        self.assertIsNone(context["refreshedAt"])

    def test_the_draft_room_ranks_against_this_seasons_byes(self):
        result = self.json("POST", "/api/suggest", {"top": 6, "league": LEAGUE})
        rows = {row["name"]: row["byeWeek"] for row in result["suggestions"]}
        self.assertEqual(rows, BYES)
        self.assertTrue(result["contextStale"])
        self.assertIsNone(result["contextAsOf"])

    def test_the_waiver_wire_knows_it_is_championship_week(self):
        # No week in the body: the scan asks the server what week it is. On the
        # calendar year this was week 1 of 2027, with every bye ignored and 18
        # weeks of rest-of-season value still to play for.
        result = self.json("POST", "/api/free-agents", {
            "leagues": [LEAGUE], "top": 30,
            "picks": {LEAGUE["id"]: [{"playerId": "sleeper:4", "teamNum": 1}]},
        })
        self.assertEqual(result["week"], WEEK)
        self.assertTrue(result["contextStale"])
        rows = result["leagues"][0]["rosRecommendations"] + result["leagues"][0]["weeklyRecommendations"]
        self.assertTrue(rows, "the fixture should rank at least one pickup")
        for row in rows:
            self.assertEqual(row["byeWeek"], BYES[row["name"]], row["name"])

    def test_the_startup_refresh_moves_a_stale_cache_onto_this_season_and_week(self):
        # What the app sends on launch: no season, no week.
        result = self.refresh({})
        self.assertEqual((result["season"], result["week"]), (SEASON, WEEK))
        saved = self.cached()
        self.assertEqual((saved.season, saved.selected_week), (SEASON, WEEK))
        self.assertEqual(saved.signals, [], "last season's news is not carried into this one")
        context = self.json("GET", "/api/context")
        self.assertEqual((context["season"], context["week"]), (SEASON, WEEK))

    def test_the_startup_refresh_advances_the_week_within_a_season(self):
        save_context(_cache(SEASON, 9), self.cache)
        self.assertEqual(self.json("GET", "/api/context")["week"], 9)
        result = self.refresh({})
        self.assertEqual((result["season"], result["week"]), (SEASON, WEEK))
        saved = self.cached()
        self.assertEqual(saved.selected_week, WEEK)
        self.assertEqual(len(saved.signals), 1, "this season's news is kept")

    def test_an_explicit_season_and_week_are_still_honoured(self):
        # Tools refresh an older season on purpose, and the waiver wire names
        # the week it is looking at.
        result = self.refresh({"season": SEASON - 1, "week": 9})
        self.assertEqual((result["season"], result["week"], result["signalCount"]), (SEASON - 1, 9, 1))
        self.assertEqual(self.cached().season, SEASON - 1)
        # ...and that cache still is not news about this season.
        self.assertEqual(self.json("GET", "/api/context")["season"], SEASON)
        self.assertEqual(self.json("POST", "/api/refresh-byes", {"season": SEASON - 1})["season"], SEASON - 1)
        self.assertEqual(self.stamps(), {SEASON - 1})


class TestCurrentByeWeekAcrossTheNewYear(unittest.TestCase):
    def test_a_bye_stamped_in_the_autumn_is_still_this_seasons_in_january(self):
        player = _stamped_board(2026)[0]
        for day in (date(2026, 12, 31), date(2027, 1, 1), date(2027, 1, 10)):
            with self.subTest(day=day.isoformat()):
                self.assertEqual(current_bye_week(player, default_season(day)), SCHEDULE["KC"])
        self.assertIsNone(current_bye_week(player, default_season(date(2027, 3, 1))))


if __name__ == "__main__":
    unittest.main()
