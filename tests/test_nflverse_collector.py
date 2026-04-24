"""Tests for the nflverse data collector."""
import unittest

from draft_assistant.collectors.nflverse import (
    _extract_stats,
    _draft_capital_label,
    _safe_int,
    _safe_float,
    _compute_bye_weeks,
    _aggregate_injuries,
)


class TestExtractStats(unittest.TestCase):
    def test_basic_passing(self):
        row = {"passing_yards": 4000.0, "passing_tds": 30.0, "interceptions": 10.0}
        stats = _extract_stats(row)
        self.assertEqual(stats["pass_yd"], 4000.0)
        self.assertEqual(stats["pass_td"], 30.0)
        self.assertEqual(stats["pass_int"], 10.0)

    def test_rushing_receiving(self):
        row = {"rushing_yards": 1200.0, "rushing_tds": 10.0,
               "receptions": 50.0, "receiving_yards": 400.0, "receiving_tds": 3.0}
        stats = _extract_stats(row)
        self.assertEqual(stats["rush_yd"], 1200.0)
        self.assertEqual(stats["rec"], 50.0)
        self.assertEqual(stats["rec_yd"], 400.0)

    def test_fumbles_summed(self):
        row = {"sack_fumbles_lost": 1.0, "rushing_fumbles_lost": 2.0,
               "receiving_fumbles_lost": 1.0}
        stats = _extract_stats(row)
        self.assertEqual(stats["fumbles"], 4.0)

    def test_none_values_skipped(self):
        row = {"passing_yards": None, "rushing_yards": 500.0}
        stats = _extract_stats(row)
        self.assertNotIn("pass_yd", stats)
        self.assertEqual(stats["rush_yd"], 500.0)

    def test_empty_row(self):
        self.assertEqual(_extract_stats({}), {})


class TestDraftCapital(unittest.TestCase):
    def test_first_round(self):
        self.assertEqual(_draft_capital_label(1), "1st-round")
        self.assertEqual(_draft_capital_label(32), "1st-round")

    def test_later_rounds(self):
        self.assertEqual(_draft_capital_label(33), "2nd-round")
        self.assertEqual(_draft_capital_label(100), "3rd-round")
        self.assertEqual(_draft_capital_label(250), "7th-round")

    def test_none(self):
        self.assertIsNone(_draft_capital_label(None))


class TestSafeConversions(unittest.TestCase):
    def test_safe_int_normal(self):
        self.assertEqual(_safe_int(25), 25)
        self.assertEqual(_safe_int(25.0), 25)
        self.assertEqual(_safe_int("25"), 25)

    def test_safe_int_none_and_nan(self):
        self.assertIsNone(_safe_int(None))
        self.assertIsNone(_safe_int(float("nan")))

    def test_safe_float_normal(self):
        self.assertAlmostEqual(_safe_float(3.5), 3.5)

    def test_safe_float_none(self):
        self.assertIsNone(_safe_float(None))


class TestByeWeeks(unittest.TestCase):
    def test_computes_bye(self):
        import pandas as pd
        # Simulate: team A plays weeks 1-13,15-18 → bye=14
        rows = []
        for week in list(range(1, 14)) + list(range(15, 19)):
            rows.append({"recent_team": "TST", "week": week, "season_type": "REG",
                         "player_id": "p1", "player_name": "Test"})
        df = pd.DataFrame(rows)
        byes = _compute_bye_weeks(df)
        self.assertEqual(byes["TST"], 14)


class TestAggregateInjuries(unittest.TestCase):
    def test_collects_unique_injuries(self):
        import pandas as pd
        rows = [
            {"gsis_id": "p1", "report_primary_injury": "Ankle",
             "report_status": "Out", "season": 2024},
            {"gsis_id": "p1", "report_primary_injury": "Ankle",
             "report_status": "Out", "season": 2024},
            {"gsis_id": "p1", "report_primary_injury": "Knee",
             "report_status": "Questionable", "season": 2024},
        ]
        df = pd.DataFrame(rows)
        result = _aggregate_injuries(df, [2024])
        self.assertEqual(result["p1"], ["Ankle", "Knee"])

    def test_skips_none_injuries(self):
        import pandas as pd
        rows = [
            {"gsis_id": "p1", "report_primary_injury": None,
             "report_status": "Out", "season": 2024},
        ]
        df = pd.DataFrame(rows)
        result = _aggregate_injuries(df, [2024])
        self.assertNotIn("p1", result)


if __name__ == "__main__":
    unittest.main()
