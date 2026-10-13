"""`POST /api/refresh-byes` is the packaged app's way to repair bye provenance.

An install never replaces the board a user already has, so one saved before
pulls stamped `bye_season`/`bye_team` reports no bye for anyone: `/api/players`
returns `byeWeek: null` across the board, and the bye penalty, the bye flags
and the waiver wire's week-off handling are all silently off. The CLI has
`refresh-byes`; the installed build has no terminal, so the same repair has to
be reachable over HTTP -- and, like the command, may only touch bye fields.
"""
import json
import os
import shutil
import tempfile
from unittest.mock import patch

from draft_assistant.context import current_bye_week
from draft_assistant.importers import free_sources as fs
from draft_assistant.models import PlayerContext
from draft_assistant.profiles import ProfilePaths
from draft_assistant.storage import load_players, save_players
from tests.test_cli_refresh_byes import SCHEDULE, _board, _bytes, _without_byes
from tests.test_web_server import _ServerFixture


#: Deliberately not the calendar year. The default season has to be the one the
#: news context carries -- the season `/api/players` judges byes against -- so a
#: default read from `date.today()` stamps a season these tests never see.
SEASON = 2031


class TestRefreshByesEndpoint(_ServerFixture):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self._tmp, ignore_errors=True)
        self.board = os.path.join(self._tmp, "data", "projections.json")
        paths = ProfilePaths(
            "default", self._tmp, os.path.join(self._tmp, "league.config.json"),
            os.path.join(self._tmp, "draft_state.json"), self.board)
        self.ensure = self._patch("draft_assistant.web.server.ensure_profile", return_value=paths)
        self._patch("draft_assistant.web.server.load_context",
                    side_effect=lambda *a, **k: PlayerContext(SEASON, 1))
        self.fetch = self._patch("draft_assistant.importers.free_sources._fetch_nflverse_byes",
                                 return_value=dict(SCHEDULE))
        self._patch("draft_assistant.importers.free_sources.urlopen",
                    side_effect=AssertionError("unexpected network"))
        save_players(_board(), self.board)

    def _patch(self, target, **kwargs):
        patcher = patch(target, **kwargs)
        self.addCleanup(patcher.stop)
        return patcher.start()

    def refresh(self, body=None, **kwargs):
        status, raw = self.request("POST", "/api/refresh-byes", {} if body is None else body, **kwargs)
        return status, json.loads(raw)

    def byes(self):
        status, raw = self.request("GET", "/api/players")
        self.assertEqual(status, 200, raw)
        return {player["name"]: player["byeWeek"] for player in json.loads(raw)}

    def test_refresh_stamps_the_board_and_players_then_report_byes(self):
        self.assertEqual(set(self.byes().values()), {None},
                         "the fixture should start with no bye the engine trusts")
        status, body = self.refresh()
        self.assertEqual(status, 200, body)
        self.assertEqual(body, {"ok": True, "season": SEASON, "players": 7,
                                "verified": 6, "changed": 1, "unlistedTeams": []})
        # The season nobody passed is the context's, not the calendar's.
        self.fetch.assert_called_once_with(SEASON)
        # The same board every other handler reads for this profile.
        self.ensure.assert_called_with("default")
        saved = {player.name: player for player in load_players(self.board)}
        self.assertEqual(current_bye_week(saved["Star RB"], SEASON), SCHEDULE["KC"])
        self.assertEqual(self.byes(), {
            "Star RB": SCHEDULE["KC"], "Wrong Week WR": SCHEDULE["DET"],
            "Rams Kicker": SCHEDULE["LAR"], "Detroit Lions": SCHEDULE["DET"],
            "Last Year TE": SCHEDULE["BUF"], "Hand Authored": SCHEDULE["SF"],
            "Free Agent": None,
        })

    def test_nothing_but_the_bye_fields_changes(self):
        # The whole reason this is not "just pull again": in-season a pull
        # swaps the preseason projections and ADP for current ones.
        before = _without_byes(self.board)
        status, body = self.refresh()
        self.assertEqual(status, 200, body)
        self.assertEqual(_without_byes(self.board), before)
        star = load_players(self.board)[0]
        self.assertEqual((star.adp, star.projections, sorted(star.historical_stats)),
                         (5.0, {"rush_yd": 1000.0}, [2023, 2024, 2025]))

    def test_an_explicit_season_picks_the_schedule_and_the_stamp(self):
        status, body = self.refresh({"season": 2025})
        self.assertEqual(status, 200, body)
        self.assertEqual(body["season"], 2025)
        self.fetch.assert_called_once_with(2025)
        self.assertEqual(load_players(self.board)[0].metadata["bye_season"], 2025)

    def test_an_unavailable_schedule_is_an_error_and_the_board_is_untouched(self):
        # Offline, not published yet, or half published: stamp nobody. A
        # partial schedule would verify some teams and leave the rest looking
        # like players who simply have no bye.
        partial = {team: week for team, week in SCHEDULE.items() if team not in ("KC", "SF")}
        before = _bytes(self.board)
        for fetched, expected in (
            (OSError("offline"), f"Could not load the {SEASON} NFL schedule"),
            ({}, f"The {SEASON} NFL schedule is not published yet, so bye weeks cannot be loaded."),
            (partial, "missing KC, SF"),
        ):
            with self.subTest(fetched=type(fetched).__name__, teams=len(fetched) if isinstance(fetched, dict) else None):
                failed = isinstance(fetched, Exception)
                self.fetch.side_effect = fetched if failed else None
                self.fetch.return_value = None if failed else dict(fetched)
                status, body = self.refresh()
                self.assertEqual(status, 502, body)
                self.assertIn(expected, body["error"])
                self.assertEqual(body["code"], "schedule_unavailable")
                self.assertNotIn("ok", body)
                self.assertEqual(_bytes(self.board), before)
        self.assertEqual(set(self.byes().values()), {None})

    def test_an_invalid_season_is_a_400_before_anything_is_fetched(self):
        before = _bytes(self.board)
        for season in ("next year", None, True, [], {}, 1999, 2101):
            with self.subTest(season=season):
                status, body = self.refresh({"season": season})
                self.assertEqual(status, 400, body)
                self.assertIn("season", body["error"])
        self.fetch.assert_not_called()
        self.assertEqual(_bytes(self.board), before)

    def test_a_board_with_no_players_is_an_error_and_is_not_rewritten(self):
        # Written by hand, compactly, so a save would be visible in the bytes:
        # "refreshed 0 players" is not a success, and a failed refresh must not
        # touch the file.
        with open(self.board, "w", encoding="utf-8") as handle:
            handle.write('{"players": []}')
        before = _bytes(self.board)
        status, body = self.refresh()
        self.assertEqual(status, 409, body)
        self.assertEqual(body["code"], "board_empty")
        self.assertIn("Pull player data first", body["error"])
        self.assertEqual(_bytes(self.board), before)

    def test_another_site_cannot_trigger_a_refresh(self):
        before = _bytes(self.board)
        for headers, host in (({"Sec-Fetch-Site": "cross-site"}, None),
                              ({"Sec-Fetch-Site": "same-origin"}, "evil.example.com")):
            with self.subTest(headers=headers, host=host):
                status, body = self.refresh(headers=headers, host=host)
                self.assertEqual(status, 403, body)
        self.fetch.assert_not_called()
        self.assertEqual(_bytes(self.board), before)
        # Those refusals are the guard's doing, not a route that was never
        # there: the 403 comes before dispatch, so on its own it would pass
        # with the endpoint deleted. The app's own page gets through.
        status, body = self.refresh(headers={"Sec-Fetch-Site": "same-origin"})
        self.assertEqual(status, 200, body)
        self.fetch.assert_called_once_with(SEASON)


if __name__ == "__main__":
    import unittest

    unittest.main()
