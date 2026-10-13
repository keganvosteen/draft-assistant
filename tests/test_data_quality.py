import contextlib
import io
import os
import sys
import tempfile
import unittest
from datetime import date
from unittest.mock import patch

from draft_assistant.context import current_bye_week, default_season
from draft_assistant.data_quality import evaluate_projection_quality
from draft_assistant.models import Player
from draft_assistant.storage import load_players, save_players


def _healthy_board(season=2026):
    """A board as a pull writes it: every bye stamped with its season and team."""
    counts = {"QB": 60, "RB": 130, "WR": 190, "TE": 60, "K": 30, "DST": 30}
    teams = ("KC", "DET", "BUF", "SF")
    players = []
    index = 0
    for position, count in counts.items():
        for _ in range(count):
            index += 1
            team = teams[index % len(teams)]
            projections = {"pat_made": 30} if position == "K" else {"rush_yd": 100}
            players.append(Player(
                id=str(index), name=f"P{index}", position=position, team=team,
                projections=projections, adp=float(index), bye_week=8,
                historical_stats={2025: {"rush_yd": 90}},
                metadata={"projection_source": "consensus",
                          "bye_season": season, "bye_team": team},
            ))
    return players


def _strip_bye_provenance(board):
    """What the seed board looked like before pulls stamped their byes."""
    for player in board:
        player.metadata.pop("bye_season", None)
        player.metadata.pop("bye_team", None)
    return board


STALE_BYE = "bye week the engine ignores"


class TestProjectionQuality(unittest.TestCase):
    def test_healthy_board_passes(self):
        report = evaluate_projection_quality(_healthy_board())
        self.assertTrue(report.ok, report.issues)

    def test_sleeper_only_degradation_fails(self):
        board = _healthy_board()
        for player in board:
            player.bye_week = None
            player.historical_stats = {}
            player.metadata = {}
            player.adp = None
            if player.position == "K":
                player.projections = {}
        report = evaluate_projection_quality(board)
        self.assertFalse(report.ok)
        self.assertTrue(any("bye-week" in issue for issue in report.issues))
        self.assertTrue(any("kicker" in issue for issue in report.issues))
        self.assertTrue(any("consensus" in issue for issue in report.issues))

    def test_repository_board_meets_release_gate(self):
        board = load_players("data/projections.json")
        report = evaluate_projection_quality(board)
        self.assertTrue(report.ok, report.issues)
        # The shipped board once carried 1,325 bye weeks and not one the engine
        # would use. 32 teams at 30-odd players each is well over a thousand;
        # a floor that high cannot be met by a partial stamp.
        self.assertIsNotNone(report.bye_season)
        self.assertGreaterEqual(report.with_verified_bye, 1000)
        defenses = [p for p in board if p.position == "DST"]
        self.assertEqual(
            [p.name for p in defenses if current_bye_week(p, report.bye_season) is None], [],
            "every team's defense should carry a verified bye")


class TestGateSeesVerifiedByes(unittest.TestCase):
    """The gate counts the byes the engine will use, not the ones on disk.

    `current_bye_week` trusts a bye only when its `bye_season`/`bye_team` stamp
    matches. The gate used to count `bye_week is not None`, so the seed board
    passed with 1,325 "byes" while the draft penalty and the waiver wire saw
    none of them.
    """

    def test_a_pre_provenance_board_fails(self):
        board = _strip_bye_provenance(_healthy_board())
        report = evaluate_projection_quality(board)
        self.assertFalse(report.ok)
        self.assertTrue(any(STALE_BYE in issue for issue in report.issues), report.issues)
        self.assertEqual(report.with_bye, len(board))
        self.assertEqual(report.with_verified_bye, 0)
        self.assertEqual(report.stale_byes, len(board))
        self.assertIsNone(report.bye_season)

    def test_a_stamped_board_passes(self):
        board = _healthy_board()
        report = evaluate_projection_quality(board)
        self.assertTrue(report.ok, report.issues)
        self.assertEqual(report.with_verified_bye, len(board))
        self.assertEqual(report.stale_byes, 0)
        self.assertEqual(report.bye_season, 2026)

    def test_a_board_with_no_byes_is_reported_but_not_called_stale(self):
        # Missing byes and unusable byes are different failures with different
        # fixes; only the second is repaired by refresh-byes.
        board = _strip_bye_provenance(_healthy_board())
        for player in board:
            player.bye_week = None
        report = evaluate_projection_quality(board)
        self.assertEqual((report.with_bye, report.with_verified_bye, report.stale_byes), (0, 0, 0))
        self.assertFalse(any(STALE_BYE in issue for issue in report.issues), report.issues)
        self.assertTrue(any("bye-week coverage" in issue for issue in report.issues), report.issues)

    def test_the_calendar_rolling_over_does_not_fail_a_stamped_board(self):
        # The gate runs offline on every pull request. Judged against today's
        # year, a board stamped for last season would go red on January 1st and
        # stay red until the next schedule is published in May.
        class NextFebruary(date):
            @classmethod
            def today(cls):
                return cls(2027, 2, 1)

        with patch("draft_assistant.context.date", NextFebruary):
            self.assertEqual(default_season(), 2027, "the engine's own default has moved on")
            report = evaluate_projection_quality(_healthy_board(2026))
        self.assertTrue(report.ok, report.issues)
        self.assertEqual(report.bye_season, 2026)
        self.assertEqual(report.stale_byes, 0)

    def test_a_board_is_judged_against_whatever_season_it_is_stamped_for(self):
        this_year = date.today().year
        for season in (this_year - 1, this_year, this_year + 1):
            with self.subTest(season=season):
                report = evaluate_projection_quality(_healthy_board(season))
                self.assertTrue(report.ok, report.issues)
                self.assertEqual(report.bye_season, season)

    def test_a_few_stale_byes_are_tolerated_but_not_many(self):
        # 500 byes at a 2% allowance is ten: a traded player or an unlisted
        # team code must not block a release, a wholesale loss must.
        for stale, ok in ((10, True), (11, False)):
            with self.subTest(stale=stale):
                board = _healthy_board()
                # Deep in the pool, so head coverage is not what decides this.
                _strip_bye_provenance(board[-stale:])
                report = evaluate_projection_quality(board)
                self.assertEqual(report.stale_byes, stale)
                self.assertEqual(report.ok, ok, report.issues)
                self.assertEqual(any(STALE_BYE in issue for issue in report.issues), not ok)

    def test_older_stamps_are_stale_once_any_player_names_a_newer_season(self):
        board = _healthy_board(2025)
        for player in board[:250]:
            player.metadata["bye_season"] = 2026
        report = evaluate_projection_quality(board)
        self.assertEqual(report.bye_season, 2026)
        self.assertEqual(report.stale_byes, len(board) - 250)
        self.assertTrue(any(STALE_BYE in issue for issue in report.issues), report.issues)

    def test_a_bye_stamped_for_another_team_is_stale(self):
        board = _healthy_board()
        for player in board:
            player.metadata["bye_team"] = "OLD"
        report = evaluate_projection_quality(board)
        self.assertEqual(report.with_verified_bye, 0)
        self.assertTrue(any(STALE_BYE in issue for issue in report.issues), report.issues)

    def test_teamless_players_are_not_counted_as_stale(self):
        # A player with no NFL team has no bye to verify, and refresh-byes could
        # not stamp one, so a leftover value on a free agent is not this failure.
        board = _healthy_board()
        for i in range(100):
            board.append(Player(id=f"fa{i}", name=f"Free Agent {i}", position="WR",
                                adp=float(5000 + i), bye_week=5,
                                metadata={"projection_source": "Sleeper"}))
        report = evaluate_projection_quality(board)
        self.assertTrue(report.ok, report.issues)
        self.assertEqual(report.stale_byes, 0)
        self.assertEqual(report.with_bye - report.with_verified_bye, 100)

    def test_head_coverage_counts_byes_the_engine_uses_not_stored_ones(self):
        # A released player keeps his bye_week but has no team to verify it
        # against. That is not a stale bye -- refresh-byes has nothing to stamp
        # -- but it is not coverage either: counted raw, a draftable head with
        # no usable bye in it reads as 100% covered.
        board = _healthy_board()
        for player in sorted(board, key=lambda p: p.adp)[:300]:
            player.team = None
        report = evaluate_projection_quality(board)
        self.assertEqual(report.with_bye, len(board))
        self.assertEqual(report.stale_byes, 0)
        self.assertFalse(any(STALE_BYE in issue for issue in report.issues), report.issues)
        self.assertTrue(
            any("verified bye-week coverage is 0.0% (0/300)" in issue for issue in report.issues),
            report.issues)

    def test_a_player_saved_with_null_metadata_is_unverified_not_a_crash(self):
        # A hand-edited board can carry "metadata": null. current_bye_week reads
        # metadata unguarded, and the gate must report on such a board rather
        # than die on it.
        board = _healthy_board()
        for player in board[-5:]:
            player.metadata = None
        report = evaluate_projection_quality(board)
        self.assertTrue(report.ok, report.issues)
        self.assertEqual(report.stale_byes, 5)
        self.assertEqual(report.with_verified_bye, len(board) - 5)


class TestQualityScriptPrintsVerifiedByes(unittest.TestCase):
    """`scripts/check_projection_quality.py` is what CI and both builds run."""

    def _run(self, board):
        from scripts.check_projection_quality import main

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "board.json")
            save_players(board, path)
            out = io.StringIO()
            with patch.object(sys, "argv", ["check_projection_quality.py", path]), \
                 contextlib.redirect_stdout(out):
                code = main()
        return code, out.getvalue()

    def test_a_stamped_board_passes_and_prints_both_counts(self):
        code, out = self._run(_healthy_board())
        self.assertEqual(code, 0, out)
        self.assertIn("500 with byes (500 verified for 2026)", out)

    def test_a_pre_provenance_board_exits_nonzero_and_says_why(self):
        code, out = self._run(_strip_bye_provenance(_healthy_board()))
        self.assertEqual(code, 1, out)
        self.assertIn("500 with byes (0 verified, none stamped)", out)
        self.assertIn(STALE_BYE, out)


class TestCoverageIsMeasuredOverDraftablePlayers(unittest.TestCase):
    """Coverage is scored over the draftable head, not the provider's universe.

    Sleeper lists ~2,000 players with an ADP and nobody projects the tail of
    that list, because nobody drafts it. Measuring against the whole pool made a
    pull that *added* a source and lifted top-200 consensus from 76% to 88% fail
    the gate for also carrying a thousand undraftable names.
    """

    def _with_undraftable_tail(self, count):
        board = _healthy_board()
        start = len(board)
        for i in range(count):
            board.append(Player(
                id=f"deep{i}", name=f"Deep {i}", position="WR",
                adp=float(start + i + 1000),  # ranked far below every real pick
                metadata={"projection_source": "Sleeper"},
            ))
        return board

    def test_a_large_unprojected_tail_does_not_fail_the_board(self):
        report = evaluate_projection_quality(self._with_undraftable_tail(1200))
        self.assertTrue(report.ok, report.issues)

    def test_but_losing_the_draftable_head_still_fails(self):
        board = self._with_undraftable_tail(1200)
        ranked = sorted(board, key=lambda p: (p.adp is None, p.adp))
        for player in ranked[:300]:
            player.projections = {}
        report = evaluate_projection_quality(board)
        self.assertFalse(report.ok)
        self.assertTrue(any("projection coverage" in issue for issue in report.issues))

    def test_a_board_with_no_adp_is_judged_whole(self):
        # No ADP means no identifiable draftable head, so the slice must not
        # silently become "whatever the pull emitted first" -- that order can
        # exclude an entire position and skip its check.
        board = self._with_undraftable_tail(1200)
        for player in board:
            player.adp = None
            if player.position == "K":
                player.projections = {}
        report = evaluate_projection_quality(board)
        self.assertFalse(report.ok)
        self.assertTrue(any("kicker" in issue for issue in report.issues), report.issues)

    def test_board_wide_signals_are_still_judged_board_wide(self):
        # ADP and provenance describe the whole pull; losing them wholesale is a
        # broken pull no matter how healthy the top 300 looks.
        board = self._with_undraftable_tail(1200)
        for player in board:
            player.metadata = {}
        report = evaluate_projection_quality(board)
        self.assertFalse(report.ok)
        self.assertTrue(any("provenance" in issue for issue in report.issues))


if __name__ == "__main__":
    unittest.main()
