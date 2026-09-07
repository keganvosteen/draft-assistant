"""The CLI pull must accumulate history the same way the web endpoints do.

A pull only fetches the stats seasons it was asked for. `cmd_pull_free_data`
used to hand its result straight to `save_players`, so a default CLI pull
replaced a board carrying 2023/2024/2025 with one carrying only 2025 — silently
discarding two seasons the historical blend depends on. The web endpoints have
always routed through `update_players` + `merge_historical_into`; this pins the
CLI to the same contract.
"""
import os
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

from draft_assistant.models import Player
from draft_assistant.storage import load_players, save_players


def _board(seasons, name="Star RB"):
    return [Player(
        id="sleeper:1", name=name, position="RB",
        projections={"rush_yd": 1000.0}, adp=5.0,
        historical_stats={s: {"rush_yd": 900.0 + s} for s in seasons},
    )]


class TestCliPullKeepsHistory(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self._orig = os.getcwd()
        os.chdir(self._tmp)
        os.makedirs("data", exist_ok=True)

    def tearDown(self):
        os.chdir(self._orig)
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _run(self, extra_argv=()):
        from draft_assistant import cli
        from draft_assistant.importers import free_sources as fs

        # The pull itself returns only the newest season, as a real one would
        # when asked for a single stats season.
        result = fs.FreeDataResult(players=_board([2025]), reports=[])
        argv = ["draft-assistant", "pull-free-data", *extra_argv]
        with patch.object(cli, "pull_free_data", return_value=result), \
             patch.object(sys, "argv", argv):
            cli.main()

    def test_earlier_seasons_survive_a_later_pull(self):
        save_players(_board([2023, 2024, 2025]), "data/projections.json")
        self._run()
        saved = load_players("data/projections.json")
        self.assertEqual(len(saved), 1)
        self.assertEqual(
            sorted(saved[0].historical_stats), [2023, 2024, 2025],
            "a CLI pull must not discard seasons an earlier pull banked",
        )

    def test_pull_onto_an_empty_board_still_works(self):
        self._run()
        saved = load_players("data/projections.json")
        self.assertEqual(sorted(saved[0].historical_stats), [2025])

    def test_explicit_out_is_an_export_and_is_written_verbatim(self):
        save_players(_board([2023, 2024, 2025]), "data/projections.json")
        self._run(["--out", "export.json"])
        exported = load_players("export.json")
        self.assertEqual(sorted(exported[0].historical_stats), [2025])
        # ...and the live board is left alone.
        board = load_players("data/projections.json")
        self.assertEqual(sorted(board[0].historical_stats), [2023, 2024, 2025])


if __name__ == "__main__":
    unittest.main()
