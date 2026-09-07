"""Offline validity checks for optional backtest helpers."""
import os
import tempfile
import unittest
from unittest.mock import patch

try:
    import pandas as pd
    from draft_assistant import backtest
except ImportError:  # Core installs intentionally omit analytics dependencies.
    pd = None
    backtest = None


@unittest.skipIf(backtest is None, "backtest extras are not installed")
class TestBacktestValidity(unittest.TestCase):
    def test_scoring_configuration_changes_cache_identity(self):
        self.assertNotEqual(
            backtest._scoring_tag({"pass_td": 4}),
            backtest._scoring_tag({"pass_td": 6}),
        )

    def test_actual_results_do_not_select_evaluation_population(self):
        frame = pd.DataFrame({
            "pos": ["QB", "QB", "QB"],
            "actual": [999, 1, 500],
            "fftoday": [10, 30, 20],
            "prior_year": [10, 30, 20],
        }, index=["a", "b", "c"])
        sources = {"fftoday": {}, "prior_year": {}}
        with patch.dict(backtest.RELEVANT_TOP, {"QB": 2}):
            relevant = backtest._preseason_relevant(frame, sources, "QB")
        self.assertEqual(set(relevant.index), {"b", "c"})
        self.assertNotIn("a", relevant.index)  # highest actual, lowest preseason rank

    def test_scored_cache_files_do_not_collide(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(backtest, "CACHE_DIR", tmp), patch.object(
                backtest, "_fetch_nflverse_stats_rows", return_value=[]
            ):
                backtest.actuals(2024, {"pass_td": 4})
                backtest.actuals(2024, {"pass_td": 6})
            self.assertEqual(len(os.listdir(tmp)), 2)


if __name__ == "__main__":
    unittest.main()
