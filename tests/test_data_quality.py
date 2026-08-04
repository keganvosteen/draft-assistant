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


if __name__ == "__main__":
    unittest.main()
