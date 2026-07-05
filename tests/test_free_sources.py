"""Tests for the no-dependency free data collector's field mapping and merge."""
import unittest
from unittest.mock import patch

from draft_assistant.models import LeagueConfig, Player
from draft_assistant.importers.free_sources import (
    _consensus_projection,
    _fill_missing_byes,
    _merge_many,
    _merge_player,
    _players_from_nflverse_stats,
    _players_from_sleeper_projection_rows,
)


class TestSleeperProjectionPlayers(unittest.TestCase):
    def test_age_and_experience_land_on_player_fields(self):
        rows = {"123": {"pts_ppr": 250.0, "rec": 80, "rec_yd": 1000, "adp_half_ppr": 12.0}}
        meta = {"123": {"position": "WR", "full_name": "Test Receiver",
                        "team": "KC", "age": 27, "years_exp": 5, "bye_week": 6}}
        players = _players_from_sleeper_projection_rows(rows, meta, "half-ppr")
        self.assertEqual(len(players), 1)
        p = players[0]
        self.assertEqual(p.age, 27)
        self.assertEqual(p.experience, 5)


class TestNflverseStatsPlayers(unittest.TestCase):
    def test_actuals_become_historical_stats_not_projections(self):
        rows = [{
            "player_id": "00-001", "position": "RB",
            "player_display_name": "Test Back", "recent_team": "DET",
            "rushing_yards": "1200", "rushing_tds": "10", "receptions": "40",
        }]
        meta = {"00-001": {"birth_date": "1999-05-01", "years_of_experience": "4"}}
        players = _players_from_nflverse_stats(rows, meta, 2025)
        self.assertEqual(len(players), 1)
        p = players[0]
        self.assertEqual(p.projections, {})
        self.assertIn(2025, p.historical_stats)
        self.assertEqual(p.historical_stats[2025]["rush_yd"], 1200.0)
        self.assertIsNotNone(p.age)
        self.assertEqual(p.experience, 4)


class TestFillMissingByes(unittest.TestCase):
    def test_teammates_inherit_known_bye(self):
        a = Player(id="a", name="A", position="WR", team="KC", bye_week=6)
        b = Player(id="b", name="B", position="RB", team="KC")
        c = Player(id="c", name="C", position="QB", team="DET")  # no source bye
        _fill_missing_byes([a, b, c])
        self.assertEqual(b.bye_week, 6)
        self.assertIsNone(c.bye_week)

    def test_existing_byes_not_overwritten(self):
        a = Player(id="a", name="A", position="WR", team="KC", bye_week=6)
        b = Player(id="b", name="B", position="RB", team="KC", bye_week=7)
        _fill_missing_byes([a, b])
        self.assertEqual(b.bye_week, 7)


class TestMergePlayer(unittest.TestCase):
    def test_merge_carries_age_experience_and_history(self):
        base = Player(id="a", name="Test Back", position="RB", team="DET",
                      projections={"rush_yd": 1100.0})
        incoming = Player(id="b", name="Test Back", position="RB",
                          age=26, experience=4,
                          historical_stats={2025: {"rush_yd": 1200.0}})
        _merge_player(base, incoming, "nflverse_stats_2025")
        self.assertEqual(base.age, 26)
        self.assertEqual(base.experience, 4)
        self.assertEqual(base.historical_stats[2025]["rush_yd"], 1200.0)
        # Actuals must not leak into the projection
        self.assertEqual(base.projections, {"rush_yd": 1100.0})

    def test_merge_does_not_overwrite_existing_fields(self):
        base = Player(id="a", name="Test Back", position="RB", age=25,
                      historical_stats={2025: {"rush_yd": 1000.0}})
        incoming = Player(id="b", name="Test Back", position="RB", age=30,
                          historical_stats={2025: {"rush_yd": 999.0},
                                            2024: {"rush_yd": 900.0}})
        _merge_player(base, incoming, "other")
        self.assertEqual(base.age, 25)
        self.assertEqual(base.historical_stats[2025]["rush_yd"], 1000.0)
        self.assertEqual(base.historical_stats[2024]["rush_yd"], 900.0)


class TestConsensusProjection(unittest.TestCase):
    def test_per_stat_median_across_sources(self):
        out = _consensus_projection([
            {"rush_yd": 1000.0, "rush_td": 8.0},
            {"rush_yd": 1200.0, "rush_td": 10.0},
            {"rush_yd": 1400.0, "rush_td": 9.0},
        ])
        self.assertEqual(out["rush_yd"], 1200.0)  # median of 1000/1200/1400
        self.assertEqual(out["rush_td"], 9.0)

    def test_two_sources_average(self):
        # median of two values is their mean — a fair Sleeper+FFToday blend.
        self.assertEqual(_consensus_projection([{"rec": 80.0}, {"rec": 90.0}])["rec"], 85.0)

    def test_stat_only_one_source_has_stands(self):
        out = _consensus_projection([{"rush_yd": 1000.0, "fumbles": -2.0}, {"rush_yd": 1100.0}])
        self.assertEqual(out["rush_yd"], 1050.0)
        self.assertEqual(out["fumbles"], -2.0)


class TestMergeCollectsProjectionSamples(unittest.TestCase):
    def test_merge_many_accumulates_then_consensus(self):
        merged, samples = {}, {}
        a = Player(id="a", name="Star RB", position="RB", projections={"rush_yd": 1000.0})
        b = Player(id="b", name="Star RB", position="RB", projections={"rush_yd": 1400.0})
        _merge_many(merged, [a], "sleeper", samples)
        _merge_many(merged, [b], "fftoday", samples)
        key = next(iter(samples))
        self.assertEqual(len(samples[key]), 2)
        self.assertEqual(_consensus_projection(samples[key])["rush_yd"], 1200.0)

    def test_no_samples_dict_means_no_collection(self):
        merged = {}
        _merge_many(merged, [Player(id="a", name="X", position="WR", projections={"rec": 50.0})], "sleeper")
        self.assertEqual(len(merged), 1)  # still merges fine without sample tracking


class TestEspnProjectionStats(unittest.TestCase):
    def test_maps_numeric_stat_ids_for_target_season_only(self):
        from draft_assistant.importers.free_sources import _espn_projection_stats
        player = {"stats": [
            {"statSourceId": 0, "statSplitTypeId": 0, "seasonId": 2026, "stats": {"3": 9999}},  # actual
            {"statSourceId": 1, "statSplitTypeId": 2, "seasonId": 2026, "stats": {"3": 1}},      # per-game split
            {"statSourceId": 1, "statSplitTypeId": 0, "seasonId": 2025, "stats": {"3": 1}},      # wrong season
            {"statSourceId": 1, "statSplitTypeId": 0, "seasonId": 2026,
             "stats": {"3": 4200, "4": 30, "24": 500, "25": 6, "42": 900, "53": 80, "999": 7}},
        ]}
        out = _espn_projection_stats(player, 2026)
        self.assertEqual(out["pass_yd"], 4200.0)
        self.assertEqual(out["pass_td"], 30.0)
        self.assertEqual(out["rush_yd"], 500.0)
        self.assertEqual(out["rec_yd"], 900.0)
        self.assertEqual(out["rec"], 80.0)
        self.assertNotIn("999", out)            # unknown stat id dropped

    def test_parses_espn_rosters(self):
        from draft_assistant.importers.free_sources import _parse_espn_rosters
        data = {"teams": [{
            "id": 1,
            "name": "Team Alpha",
            "roster": {"entries": [{
                "playerPoolEntry": {"player": {
                    "id": 3918298,
                    "fullName": "Josh Allen",
                    "defaultPositionId": 1,
                    "proTeamId": 2,
                }}
            }]}
        }]}

        teams = _parse_espn_rosters(data)

        self.assertEqual(len(teams), 1)
        self.assertEqual(teams[0].name, "Team Alpha")
        self.assertEqual(teams[0].players[0].name, "Josh Allen")
        self.assertEqual(teams[0].players[0].position, "QB")
        self.assertEqual(teams[0].players[0].team, "BUF")
        self.assertEqual(teams[0].players[0].provider_id, "espn:3918298")

    def test_parses_espn_rosters(self):
        from draft_assistant.importers.free_sources import _parse_espn_rosters
        data = {"teams": [{
            "id": 1,
            "name": "Team Alpha",
            "roster": {"entries": [{
                "playerPoolEntry": {"player": {
                    "id": 3918298,
                    "fullName": "Josh Allen",
                    "defaultPositionId": 1,
                    "proTeamId": 2,
                }}
            }]}
        }]}

        teams = _parse_espn_rosters(data)

        self.assertEqual(len(teams), 1)
        self.assertEqual(teams[0].name, "Team Alpha")
        self.assertEqual(teams[0].players[0].name, "Josh Allen")
        self.assertEqual(teams[0].players[0].position, "QB")
        self.assertEqual(teams[0].players[0].team, "BUF")
        self.assertEqual(teams[0].players[0].provider_id, "espn:3918298")


class TestFftodayRetryAndFailure(unittest.TestCase):
    def test_fetch_retries_transient_failures(self):
        from draft_assistant.importers import fftoday
        calls = {"n": 0}

        def flaky(url):
            calls["n"] += 1
            if calls["n"] < 3:
                raise OSError("connection dropped")
            return "<html></html>"

        with patch.object(fftoday, "_fetch_once", side_effect=flaky), \
             patch.object(fftoday.time, "sleep"):
            self.assertEqual(fftoday._fetch("http://example"), "<html></html>")
        self.assertEqual(calls["n"], 3)

    def test_fetch_raises_after_exhausting_attempts(self):
        from draft_assistant.importers import fftoday
        with patch.object(fftoday, "_fetch_once", side_effect=OSError("down")), \
             patch.object(fftoday.time, "sleep"):
            with self.assertRaises(OSError):
                fftoday._fetch("http://example")

    def test_all_positions_failing_raises(self):
        from draft_assistant.importers import fftoday
        with patch.object(fftoday, "fetch_fftoday", side_effect=OSError("down")):
            with self.assertRaises(RuntimeError):
                fftoday.fetch_all_fftoday(2026)

    def test_partial_failure_still_returns_players(self):
        from draft_assistant.importers import fftoday

        def some(season, pos):
            if pos == "QB":
                raise OSError("down")
            return [Player(id=pos, name=f"Test {pos}", position=pos)]

        with patch.object(fftoday, "fetch_fftoday", side_effect=some):
            players = fftoday.fetch_all_fftoday(2026)
        self.assertEqual(len(players), 3)  # RB/WR/TE survive a QB-page failure


class TestSingleSourceWarning(unittest.TestCase):
    """A pull that ends up Sleeper-only must say so, not just report success."""

    def _pull(self, fftoday_result, include_fftoday=True):
        from draft_assistant.importers import free_sources as fs
        config = LeagueConfig(teams=12, roster={}, scoring={"rec": 1.0}, provider={})
        sleeper_meta = {"1": {"position": "RB", "full_name": "Star RB", "team": "DET"}}
        sleeper_rows = {"1": {"rush_yd": 1000.0, "adp_ppr": 5.0}}

        def fftoday(season):
            if isinstance(fftoday_result, Exception):
                raise fftoday_result
            return fftoday_result

        with patch.object(fs, "_fetch_sleeper_players", return_value=sleeper_meta), \
             patch.object(fs, "_fetch_sleeper_projection_rows", return_value=sleeper_rows), \
             patch.object(fs, "_fetch_ffc_adp_players", side_effect=RuntimeError("offline")), \
             patch.object(fs, "_fetch_nflverse_players", side_effect=RuntimeError("offline")), \
             patch.object(fs, "_fetch_nflverse_stats_rows", side_effect=RuntimeError("offline")), \
             patch.object(fs, "fetch_all_fftoday", side_effect=fftoday):
            return fs.pull_free_data(config, season=2026, include_fftoday=include_fftoday)

    def test_fftoday_failure_yields_warning_with_cause(self):
        result = self._pull(RuntimeError("QB: connection dropped"))
        self.assertEqual(result.consensus_players, 0)
        self.assertEqual(len(result.warnings), 1)
        self.assertIn("single-source", result.warnings[0])
        self.assertIn("FFToday failed: QB: connection dropped", result.warnings[0])
        self.assertIn("no ESPN league linked", result.warnings[0])

    def test_fftoday_skipped_yields_warning(self):
        result = self._pull([], include_fftoday=False)
        self.assertEqual(result.consensus_players, 0)
        self.assertEqual(len(result.warnings), 1)
        self.assertIn("FFToday was skipped", result.warnings[0])

    def test_consensus_present_means_no_warning(self):
        ff = [Player(id="ff", name="Star RB", position="RB",
                     projections={"rush_yd": 1200.0})]
        result = self._pull(ff)
        self.assertEqual(result.consensus_players, 1)
        self.assertEqual(result.warnings, [])


if __name__ == "__main__":
    unittest.main()
