"""`refresh-byes` repairs bye provenance on a saved board and nothing else.

`current_bye_week` trusts a bye only when its season and team are stamped beside
it. The tracked seed board predated that stamp, so the engine used none of its
1,325 byes: no draft bye penalty, no bye in `/api/players`, no zeroing of a
waiver target on his week off. A full re-pull would have stamped them -- and, in
October, replaced the preseason projections and ADP the draft board is built
on. Only the provenance was missing, so this command may only touch bye fields.
"""
import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

from draft_assistant.context import current_bye_week
from draft_assistant.importers import free_sources as fs
from draft_assistant.models import Player
from draft_assistant.profiles import ProfilePaths
from draft_assistant.storage import load_players, save_players


BOARD = "data/projections.json"
#: One bye per team, as a published schedule gives.
SCHEDULE = {team: 5 + index % 10 for index, team in enumerate(sorted(fs.NFL_TEAM_NAMES))}


def _board():
    return [
        # Right week, but saved before pulls stamped provenance -- the seed
        # board's exact condition. Carries one of everything a save can hold.
        Player(id="sleeper:1", name="Star RB", position="RB", team="KC",
               bye_week=SCHEDULE["KC"], adp=5.0, projections={"rush_yd": 1000.0},
               age=25, experience=3,
               historical_stats={s: {"rush_yd": 900.0 + s} for s in (2023, 2024, 2025)},
               previous_team="DET", draft_capital="1st-round",
               injury_history=["2024 ankle"],
               metadata={"sleeper_id": "1", "projection_source": "consensus",
                         "sources": ["sleeper_projections", "espn"]}),
        Player(id="sleeper:2", name="Wrong Week WR", position="WR", team="DET",
               bye_week=SCHEDULE["DET"] + 1, metadata={"sources": ["sleeper_players"]}),
        # nflverse spells the Rams "LA"; the schedule lists them as "LAR".
        Player(id="gsis:3", name="Rams Kicker", position="K", team="LA",
               metadata={"gsis_id": "3"}),
        Player(id="sleeper:DET", name="Detroit Lions", position="DST", team="DET",
               bye_week=SCHEDULE["DET"], metadata={"sleeper_id": "DET"}),
        Player(id="sleeper:4", name="Free Agent", position="QB", adp=400.0,
               projections={"pass_yd": 10.0}, metadata={"status": "Active"}),
        Player(id="sleeper:5", name="Last Year TE", position="TE", team="BUF",
               bye_week=SCHEDULE["BUF"], metadata={"bye_season": 2025, "bye_team": "BUF"}),
        Player(id="hand:1", name="Hand Authored", position="RB", team="SF"),
    ]


def _without_byes(path):
    """The saved board as raw JSON with every bye field removed."""
    with open(path, encoding="utf-8") as handle:
        players = json.load(handle)["players"]
    for player in players:
        player.pop("bye_week")
        metadata = player.get("metadata", {})
        metadata.pop("bye_season", None)
        metadata.pop("bye_team", None)
        if not metadata:
            # A player saved with no metadata gains a block holding only the stamp.
            player.pop("metadata", None)
    return players


def _bytes(path):
    with open(path, "rb") as handle:
        return handle.read()


class TestRefreshByes(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self._orig = os.getcwd()
        os.chdir(self._tmp)

    def tearDown(self):
        os.chdir(self._orig)
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _run(self, byes=SCHEDULE, error=None, argv=("--season", "2026")):
        from draft_assistant import cli

        out = io.StringIO()
        with patch.object(cli, "_fetch_nflverse_byes", return_value=dict(byes),
                          side_effect=error) as fetch, \
             patch.object(fs, "urlopen", side_effect=AssertionError("unexpected network")), \
             patch.object(sys, "argv", ["draft-assistant", "refresh-byes", *argv]), \
             contextlib.redirect_stdout(out):
            try:
                cli.main()
                code = 0
            except SystemExit as exc:
                code = exc.code
        return code, out.getvalue(), fetch

    def test_every_rostered_player_ends_up_with_a_bye_the_engine_trusts(self):
        save_players(_board(), BOARD)
        self.assertEqual(
            [p.name for p in load_players(BOARD) if current_bye_week(p, 2026)], [],
            "the fixture should start with no usable bye")
        code, out, _fetch = self._run()
        self.assertEqual(code, 0, out)
        saved = {p.name: p for p in load_players(BOARD)}
        for name, team in (("Star RB", "KC"), ("Wrong Week WR", "DET"), ("Rams Kicker", "LAR"),
                           ("Detroit Lions", "DET"), ("Last Year TE", "BUF"),
                           ("Hand Authored", "SF")):
            with self.subTest(player=name):
                player = saved[name]
                self.assertEqual(current_bye_week(player, 2026), SCHEDULE[team])
                self.assertEqual(player.metadata["bye_season"], 2026)
                # Stored the way the board spells the team ("LA", not "LAR"),
                # or current_bye_week's team comparison rejects the stamp.
                self.assertEqual(player.metadata["bye_team"], player.team)
        free_agent = saved["Free Agent"]
        self.assertIsNone(free_agent.bye_week)
        self.assertEqual(free_agent.metadata, {"status": "Active"})
        self.assertIn("6 of 7 players now carry a verified 2026 bye", out)
        self.assertIn("1 stored bye week(s) changed", out)

    def test_nothing_but_the_bye_fields_changes(self):
        save_players(_board(), BOARD)
        before = _without_byes(BOARD)
        self._run()
        self.assertEqual(_without_byes(BOARD), before)
        star = load_players(BOARD)[0]
        self.assertEqual(star.name, "Star RB")
        self.assertEqual(sorted(star.historical_stats), [2023, 2024, 2025],
                         "a bye refresh must not cost the board its banked seasons")
        self.assertEqual(star.projections, {"rush_yd": 1000.0})
        self.assertEqual(star.adp, 5.0)

    def test_a_second_refresh_rewrites_the_same_file(self):
        save_players(_board(), BOARD)
        self._run()
        once = _bytes(BOARD)
        code, _out, _fetch = self._run()
        self.assertEqual(code, 0)
        self.assertEqual(_bytes(BOARD), once)

    def test_an_unavailable_schedule_changes_nothing_and_exits_nonzero(self):
        save_players(_board(), BOARD)
        before = _bytes(BOARD)
        code, out, _fetch = self._run(error=OSError("offline"))
        self.assertEqual(code, 1)
        self.assertEqual(_bytes(BOARD), before)
        self.assertIn("Could not load the 2026 schedule (offline)", out)
        self.assertIn("the board was not changed", out)

    def test_an_incomplete_schedule_changes_nothing_and_exits_nonzero(self):
        # Before the schedule is published the fetch returns no team at all;
        # a partial one would verify some teams and leave the rest looking like
        # players who simply have no bye. Either way: stamp nobody.
        partial = {team: week for team, week in SCHEDULE.items() if team not in ("KC", "SF")}
        for byes, named in (({}, "any team"), (partial, "KC, SF")):
            with self.subTest(teams=len(byes)):
                save_players(_board(), BOARD)
                before = _bytes(BOARD)
                code, out, _fetch = self._run(byes=byes)
                self.assertEqual(code, 1)
                self.assertEqual(_bytes(BOARD), before)
                self.assertIn(f"no bye week yet for {named}", out)
                self.assertIn("the board was not changed", out)

    def test_season_flag_picks_the_schedule_and_the_stamp(self):
        save_players(_board(), BOARD)
        _code, _out, fetch = self._run(argv=("--season", "2025"))
        fetch.assert_called_once_with(2025)
        star = load_players(BOARD)[0]
        self.assertEqual(current_bye_week(star, 2025), SCHEDULE["KC"])
        self.assertIsNone(current_bye_week(star, 2026))

    def test_season_defaults_to_the_projection_season(self):
        from draft_assistant import cli

        save_players(_board(), BOARD)
        with patch.object(cli, "default_projection_season", return_value=2031):
            _code, _out, fetch = self._run(argv=())
        fetch.assert_called_once_with(2031)
        self.assertEqual(load_players(BOARD)[0].metadata["bye_season"], 2031)

    def test_the_board_is_found_through_the_profile_paths(self):
        # An installed build keeps its board in the per-user data directory
        # (paths.resolve). A hardcoded "data/projections.json" would refresh a
        # file beside the executable that nothing reads.
        from draft_assistant import cli

        elsewhere = os.path.join(self._tmp, "user-data", "data", "projections.json")
        save_players(_board(), elsewhere)
        paths = ProfilePaths("default", ".", "league.config.json", "draft_state.json", elsewhere)
        with patch.object(cli, "ensure_profile", return_value=paths):
            code, out, _fetch = self._run()
        self.assertEqual(code, 0, out)
        self.assertFalse(os.path.exists(BOARD))
        self.assertEqual(current_bye_week(load_players(elsewhere)[0], 2026), SCHEDULE["KC"])

    def test_an_empty_board_is_reported_rather_than_called_refreshed(self):
        code, out, _fetch = self._run()
        self.assertEqual(code, 1)
        self.assertIn("run pull-free-data first", out)
        self.assertEqual(load_players(BOARD), [])


if __name__ == "__main__":
    unittest.main()
