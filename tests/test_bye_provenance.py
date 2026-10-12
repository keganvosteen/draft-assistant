"""Current-season byes must retain schedule and team provenance through pulls."""
import unittest
from contextlib import ExitStack
from unittest.mock import patch

from draft_assistant.context import current_bye_week
from draft_assistant.importers import free_sources as fs
from draft_assistant.collectors import combined
from draft_assistant.models import LeagueConfig, Player


def player(name="Player", team="KC", bye=None, season=None, bye_team=None):
    metadata = {}
    if season is not None:
        metadata["bye_season"] = season
    if bye_team is not None:
        metadata["bye_team"] = bye_team
    return Player(id=name, name=name, position="RB", team=team,
                  bye_week=bye, metadata=metadata)


def schedule(season=2026, bye=6, home="KC", away="DET"):
    weeks = 18 if season >= 2021 else 17
    return [{"season": str(season), "game_type": "REG", "week": str(week),
             "home_team": home, "away_team": away}
            for week in range(1, weeks + 1) if week != bye]


class TestScheduleByes(unittest.TestCase):
    def test_filters_season_and_postseason(self):
        rows = schedule(2025, 7) + schedule(2026, 6)
        rows.append({"season": "2026", "game_type": "POST", "week": "6",
                     "home_team": "KC", "away_team": "DET"})
        with patch.object(fs, "_read_csv_url", return_value=rows) as read:
            self.assertEqual(fs._fetch_nflverse_byes(2026), {"KC": 6, "DET": 6})
        read.assert_called_once_with(fs.NFLVERSE_SCHEDULE_URL)

    def test_missing_and_partial_seasons_do_not_invent_a_bye(self):
        for rows in (schedule(2025), schedule(2026)[:-1], []):
            with self.subTest(rows=len(rows)), patch.object(fs, "_read_csv_url", return_value=rows):
                self.assertEqual(fs._fetch_nflverse_byes(2026), {})

    def test_pre_2021_schedule_has_seventeen_weeks(self):
        with patch.object(fs, "_read_csv_url", return_value=schedule(2020, 8)):
            self.assertEqual(fs._fetch_nflverse_byes(2020), {"KC": 8, "DET": 8})

    def test_schedule_team_aliases_match_projection_teams(self):
        with patch.object(fs, "_read_csv_url", return_value=schedule(home="LA", away="JAC")):
            self.assertEqual(fs._fetch_nflverse_byes(2026), {"LAR": 6, "JAX": 6})


class TestByeMerging(unittest.TestCase):
    def test_unverified_old_and_other_team_byes_do_not_spread(self):
        for donor in (player(bye=6), player(bye=6, season=2025),
                      player(bye=6, season=2026, bye_team="DET")):
            with self.subTest(metadata=donor.metadata):
                recipient = player("Teammate")
                fs._fill_missing_byes([donor, recipient], 2026)
                self.assertIsNone(recipient.bye_week)
                self.assertNotIn("bye_season", recipient.metadata)

    def test_current_teammate_replaces_stale_bye_and_copies_provenance(self):
        donor = player(bye=6, season=2026, bye_team="KC")
        recipient = player("Teammate", bye=7, season=2025)
        fs._fill_missing_byes([donor, recipient], 2026)
        self.assertEqual(current_bye_week(recipient, 2026), 6)
        self.assertEqual(recipient.metadata["bye_team"], "KC")

    def test_conflicting_current_byes_do_not_spread(self):
        recipient = player("Teammate")
        fs._fill_missing_byes([player(bye=6, season=2026),
                               player("Other", bye=7, season=2026), recipient], 2026)
        self.assertIsNone(recipient.bye_week)

    def test_rejected_bye_does_not_attach_unrelated_provenance(self):
        base = player(bye=6)
        incoming = player(team="DET", bye=7, season=2026, bye_team="DET")
        fs._merge_player(base, incoming, "enrichment")
        self.assertEqual(base.bye_week, 6)
        self.assertNotIn("bye_season", base.metadata)
        self.assertNotIn("bye_team", base.metadata)

    def test_newer_provenance_replaces_unverified_or_older_bye(self):
        for base in (player(bye=6), player(bye=6, season=2025)):
            incoming = player(bye=7, season=2026, bye_team="KC")
            fs._merge_player(base, incoming, "enrichment")
            self.assertEqual(current_bye_week(base, 2026), 7)

    def test_an_accepted_unverified_bye_cannot_reuse_leftover_metadata(self):
        base = player(season=2026, bye_team="KC")
        fs._merge_player(base, player(bye=7), "unverified")
        self.assertEqual(base.bye_week, 7)
        self.assertIsNone(current_bye_week(base, 2026))

    def test_ffc_bye_carries_actual_response_year(self):
        result = fs._player_from_ffc_row({"name": "Player", "position": "RB",
                                         "team": "KC", "bye": 7}, "ppr", 2025)
        self.assertEqual(result.metadata["bye_season"], 2025)
        self.assertEqual(current_bye_week(result, 2025), 7)
        self.assertIsNone(current_bye_week(result, 2026))


class TestPullByeProvenance(unittest.TestCase):
    def pull(self, byes=None, schedule_error=None):
        config = LeagueConfig(teams=12, roster={}, scoring={"rec": 1}, provider={})
        old_ffc = fs._player_from_ffc_row({"name": "Player", "position": "RB",
                                          "team": "KC", "bye": 7}, "ppr", 2025)
        results = {"_fetch_sleeper_players": {"1": {"full_name": "Player", "position": "RB",
                                                      "team": "KC", "bye_week": 8}},
                   "_fetch_sleeper_projection_rows": {"1": {"rush_yd": 1000}},
                   "_fetch_ffc_adp_players": ([old_ffc], 2025),
                   "_fetch_nflverse_players": {}, "_fetch_nflverse_stats_rows": [],
                   "_fetch_espn_players": [], "record_snapshot": []}
        with ExitStack() as stack:
            stack.enter_context(patch.object(fs, "urlopen", side_effect=AssertionError("unexpected network")))
            for method, value in results.items():
                stack.enter_context(patch.object(fs, method, return_value=value))
            fetch = stack.enter_context(patch.object(fs, "_fetch_nflverse_byes",
                                                      return_value=byes or {}, side_effect=schedule_error))
            result = fs.pull_free_data(config, season=2026, stats_season=2025,
                                       include_fftoday=False, include_cbs=False)
            fetch.assert_called_once_with(2026)
            return result

    def test_requested_schedule_overrides_undated_sleeper_and_old_ffc(self):
        result = self.pull({"KC": 6})
        self.assertEqual(current_bye_week(result.players[0], 2026), 6)
        self.assertEqual(result.players[0].metadata["bye_team"], "KC")

    def test_failed_schedule_does_not_promote_ffc_fallback_year(self):
        result = self.pull(schedule_error=OSError("offline"))
        self.assertIsNone(current_bye_week(result.players[0], 2026))
        self.assertEqual(result.players[0].metadata["bye_season"], 2025)
        self.assertTrue(any(r.source == "nflverse schedule" and not r.ok for r in result.reports))
        self.assertTrue(any("2026 schedule" in warning for warning in result.warnings))

    def test_empty_schedule_is_reported_unavailable(self):
        result = self.pull()
        self.assertIsNone(current_bye_week(result.players[0], 2026))
        self.assertTrue(any(r.source == "nflverse schedule" and not r.ok for r in result.reports))

    def test_combined_collection_copies_current_schedule_to_enrichment_teammates(self):
        current = player(bye=6, season=2026, bye_team="KC")
        enrichment = player("Teammate", bye=7, season=2025)
        with patch.object(combined, "pull_free_data", return_value=fs.FreeDataResult([current], [])), \
             patch.object(combined, "_collect_nflverse", return_value=[enrichment]):
            result = combined.collect_all_result(current_season=2026, skip_sleeper=True, skip_adp=True)
        teammate = next(p for p in result.players if p.name == "Teammate")
        self.assertEqual(current_bye_week(teammate, 2026), 6)
        self.assertEqual(teammate.metadata["bye_team"], "KC")


if __name__ == "__main__":
    unittest.main()
