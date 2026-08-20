import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock
from urllib.error import URLError

from draft_assistant.context import (
    actual_stats_for,
    confidence_for_player,
    context_from_dict,
    context_payload,
    context_to_dict,
    is_candidate_eligible,
    load_context,
    player_context_ids,
    refresh_context,
    save_context,
    signals_for_player,
    urgency_for_player,
    weekly_availability_factor,
    weekly_projection_for,
)
from draft_assistant.models import Player, PlayerContext, PlayerSignal


NOW = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)


def _signal(kind, value, player_id="sleeper:1", source="test", week=None):
    return PlayerSignal(
        player_id=player_id, kind=kind, value=value, source=source,
        observed_at=NOW.isoformat(), effective_week=week,
        expires_at="2099-01-01T00:00:00+00:00", attribution="Test",
    )


class TestPlayerContext(unittest.TestCase):
    def setUp(self):
        self.player = Player(
            id="source:other", name="Test Player", position="WR",
            projections={"rec_yd": 180},
            metadata={"sleeper_id": "1", "gsis_id": "00-1"},
        )

    def test_provider_ids_and_stats_join_to_stable_player(self):
        context = PlayerContext(
            season=2026, selected_week=2,
            weekly_projections={"sleeper:1": {"rec_yd": 20}},
            actual_stats={"gsis:00-1": {"rec_yd": 40}},
        )
        self.assertIn("sleeper:1", player_context_ids(self.player))
        self.assertEqual(weekly_projection_for(context, self.player), {"rec_yd": 20.0})
        self.assertEqual(actual_stats_for(context, self.player), {"rec_yd": 40.0})

    def test_conservative_availability_rules(self):
        for status in ("Out", "Inactive", "IR", "PUP", "Suspended"):
            context = PlayerContext(2026, 1, signals=[_signal("injury", status, week=1)])
            self.assertEqual(weekly_availability_factor(context, self.player), 0.0, status)
        doubtful = PlayerContext(2026, 1, signals=[_signal("injury", "Doubtful", week=1)])
        questionable = PlayerContext(2026, 1, signals=[_signal("injury", "Questionable", week=1)])
        self.assertEqual(weekly_availability_factor(doubtful, self.player), 0.25)
        self.assertEqual(weekly_availability_factor(questionable, self.player), 1.0)
        self.assertEqual(confidence_for_player(questionable, self.player), 0.85)

    def test_soft_signals_only_change_urgency_and_explanation(self):
        context = PlayerContext(2026, 1, signals=[
            _signal("depth_chart", "WR1"),
            _signal("trend_add", "80"),
            _signal("trend_drop", "5"),
        ])
        self.assertEqual(weekly_availability_factor(context, self.player), 1.0)
        self.assertEqual(urgency_for_player(context, self.player), 75)
        self.assertEqual(len(signals_for_player(context, self.player, now=NOW)), 3)

    def test_expired_or_wrong_week_signals_are_ignored(self):
        expired = PlayerSignal(
            player_id="sleeper:1", kind="injury", value="Out", source="test",
            observed_at=NOW.isoformat(), effective_week=1,
            expires_at="2026-09-09T00:00:00+00:00",
        )
        context = PlayerContext(2026, 2, signals=[expired, _signal("injury", "Out", week=1)])
        self.assertEqual(signals_for_player(context, self.player, now=NOW), [])

    def test_ineligible_status_filters_only_explicit_context(self):
        self.assertTrue(is_candidate_eligible(None, self.player))
        context = PlayerContext(2026, 1, signals=[_signal("roster_status", "Practice Squad")])
        self.assertFalse(is_candidate_eligible(context, self.player))

    def test_round_trip_persistence(self):
        context = PlayerContext(
            season=2026, selected_week=4, refreshed_at=NOW.isoformat(),
            signals=[_signal("injury", "Questionable", week=4)],
            weekly_projections={"sleeper:1": {"rec_yd": 12.5}},
            source_health={"test": {"ok": True, "records": 1}},
        )
        self.assertEqual(context_to_dict(context_from_dict(context_to_dict(context))), context_to_dict(context))
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "context.json")
            save_context(context, path)
            loaded = load_context(path)
            self.assertEqual(context_to_dict(loaded), context_to_dict(context))

    def test_failed_refresh_retains_last_known_good_signals(self):
        context = PlayerContext(
            2026, 1, refreshed_at="2026-09-09T12:00:00+00:00",
            signals=[_signal("injury", "Questionable", source="sleeper_players")],
            source_health={
                "sleeper_players": {
                    "ok": True, "records": 1,
                    "refreshed_at": "2026-09-09T12:00:00+00:00",
                }
            },
        )
        patches = {
            "_refresh_sleeper_players": mock.Mock(side_effect=URLError("offline")),
            "_refresh_sleeper_trending": mock.Mock(return_value=0),
            "_refresh_sleeper_weekly": mock.Mock(return_value=0),
            "_refresh_sleeper_actuals": mock.Mock(return_value=0),
            "_refresh_nflverse_injuries": mock.Mock(return_value=0),
            "_refresh_nflverse_depth": mock.Mock(return_value=0),
            "_refresh_nflverse_stats": mock.Mock(return_value=0),
            "_refresh_nflverse_snaps": mock.Mock(return_value=0),
        }
        with mock.patch.multiple("draft_assistant.context", **patches):
            refreshed = refresh_context(context, force=True, now=NOW)
        self.assertEqual(len(refreshed.signals), 1)
        self.assertFalse(refreshed.source_health["sleeper_players"]["ok"])
        self.assertIn("offline", refreshed.source_health["sleeper_players"]["detail"])
        self.assertEqual(
            refreshed.source_health["sleeper_players"]["refreshed_at"],
            "2026-09-09T12:00:00+00:00",
        )
        self.assertEqual(
            refreshed.source_health["sleeper_players"]["attempted_at"],
            "2026-09-10T12:00:00+00:00",
        )
        payload = context_payload(refreshed, include_signals=False)
        self.assertTrue(payload["stale"])
        self.assertIn("sleeper_players", payload["failedSources"])


if __name__ == "__main__":
    unittest.main()
