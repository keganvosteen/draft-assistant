import unittest

from draft_assistant.data_quality import evaluate_projection_quality
from draft_assistant.models import Player
from draft_assistant.storage import load_players


def _healthy_board():
    counts = {"QB": 60, "RB": 130, "WR": 190, "TE": 60, "K": 30, "DST": 30}
    players = []
    index = 0
    for position, count in counts.items():
        for _ in range(count):
            index += 1
            projections = {"pat_made": 30} if position == "K" else {"rush_yd": 100}
            players.append(Player(
                id=str(index), name=f"P{index}", position=position,
                projections=projections, adp=float(index), bye_week=8,
                historical_stats={2025: {"rush_yd": 90}},
                metadata={"projection_source": "consensus"},
            ))
    return players


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
        report = evaluate_projection_quality(load_players("data/projections.json"))
        self.assertTrue(report.ok, report.issues)


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
