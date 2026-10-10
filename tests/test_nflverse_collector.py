"""Tests for the nflverse data collector."""
import unittest
from unittest import mock

from draft_assistant.collectors.nflverse import (
    _extract_stats,
    _draft_capital_label,
    _safe_int,
    _safe_float,
    _compute_bye_weeks,
    _aggregate_injuries,
    collect_players,
)

try:
    import pandas  # noqa: F401
    HAS_PANDAS = True
except ImportError:
    HAS_PANDAS = False


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


@unittest.skipUnless(HAS_PANDAS, "pandas not installed (optional collector dependency)")
class TestByeWeeks(unittest.TestCase):
    @staticmethod
    def schedule(season, bye):
        import pandas as pd
        return pd.DataFrame([
            {"season": season, "game_type": "REG", "week": week,
             "home_team": "TST" if week % 2 else "OPP",
             "away_team": "OPP" if week % 2 else "TST"}
            for week in range(1, 19) if week != bye
        ])

    def test_computes_bye(self):
        byes = _compute_bye_weeks(self.schedule(2026, 14), 2026)
        self.assertEqual(byes["TST"], 14)
        self.assertEqual(byes["OPP"], 14)

    def test_uses_requested_season_only(self):
        import pandas as pd
        schedules = pd.concat([self.schedule(2025, 6), self.schedule(2026, 14)])
        self.assertEqual(_compute_bye_weeks(schedules, 2026)["TST"], 14)

    def test_partial_wrong_season_or_missing_schedule_leaves_bye_unknown(self):
        import pandas as pd
        self.assertEqual(_compute_bye_weeks(self.schedule(2025, 6), 2026), {})
        self.assertEqual(_compute_bye_weeks(self.schedule(2026, 14).iloc[:5], 2026), {})
        self.assertEqual(_compute_bye_weeks(pd.DataFrame(), 2026), {})

    def test_collector_requests_current_schedule_with_provenance(self):
        import pandas as pd
        nfl = mock.Mock()
        nfl.import_seasonal_rosters.return_value = pd.DataFrame([{
            "player_id": "p1", "position": "WR", "player_name": "Test", "team": "TST",
        }])
        nfl.import_seasonal_data.return_value = pd.DataFrame()
        nfl.import_injuries.return_value = pd.DataFrame(columns=[
            "report_primary_injury", "report_status",
        ])
        nfl.import_schedules.return_value = pd.concat([
            self.schedule(2025, 6), self.schedule(2026, 14),
        ])
        with mock.patch.dict("sys.modules", {"nfl_data_py": nfl}):
            players = collect_players(current_season=2026)
        nfl.import_schedules.assert_called_once_with([2026])
        nfl.import_weekly_data.assert_not_called()
        self.assertEqual(players[0].bye_week, 14)
        self.assertEqual(players[0].metadata["bye_season"], 2026)
        self.assertEqual(players[0].metadata["bye_team"], "TST")

    def test_unavailable_schedule_does_not_substitute_historical_bye(self):
        import pandas as pd
        nfl = mock.Mock()
        nfl.import_seasonal_rosters.return_value = pd.DataFrame()
        nfl.import_seasonal_data.return_value = pd.DataFrame([{
            "player_id": "p1", "season": 2025, "receiving_yards": 100,
        }])
        nfl.import_injuries.return_value = pd.DataFrame(columns=[
            "report_primary_injury", "report_status",
        ])
        nfl.import_schedules.side_effect = OSError("schedule unavailable")
        nfl.import_weekly_data.return_value = pd.DataFrame([
            {"recent_team": "TST", "week": week, "season_type": "REG",
             "player_id": "p1", "player_name": "Test", "position": "WR"}
            for week in range(1, 19) if week != 6
        ])
        with mock.patch.dict("sys.modules", {"nfl_data_py": nfl}):
            players = collect_players(current_season=2026)
        nfl.import_weekly_data.assert_called_once_with([2025])
        self.assertIsNone(players[0].bye_week)
        self.assertNotIn("bye_season", players[0].metadata)


@unittest.skipUnless(HAS_PANDAS, "pandas not installed (optional collector dependency)")
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
