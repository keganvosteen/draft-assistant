"""Tests for the preseason projection archive.

The archive exists because the board's dominant projection source cannot be
graded from its own history — Sleeper's archived endpoint returns in-season
revisions. A clean preseason number has to be written down at pull time or it is
gone, so these tests pin the two rules that keep the record honest: only
preseason snapshots are taken, and the first one of a season wins.
"""
import json
import os
import shutil
import tempfile
import unittest
from datetime import date

from draft_assistant import projection_archive as archive
from draft_assistant.models import Player


SAMPLES = {
    "joshallen|QB": [
        ("sleeper_projections", {"pass_yd": 4000.0, "pass_td": 30.0}),
        ("fftoday", {"pass_yd": 4200.0, "pass_td": 32.0}),
    ],
    "bijanrobinson|RB": [
        ("sleeper_projections", {"rush_yd": 1300.0, "rush_td": 11.0}),
    ],
}
PLAYERS = {
    "joshallen|QB": Player(id="1", name="Josh Allen", position="QB"),
    "bijanrobinson|RB": Player(id="2", name="Bijan Robinson", position="RB"),
}


class _ArchiveFixture(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self._orig = os.getcwd()
        os.chdir(self._tmp)

    def tearDown(self):
        os.chdir(self._orig)
        shutil.rmtree(self._tmp, ignore_errors=True)


class TestPreseasonWindow(_ArchiveFixture):
    def test_august_of_the_season_is_preseason(self):
        self.assertTrue(archive.is_preseason(2026, date(2026, 8, 24)))

    def test_september_onward_is_not(self):
        # Once games are played a "projection" has seen results.
        self.assertFalse(archive.is_preseason(2026, date(2026, 9, 1)))
        self.assertFalse(archive.is_preseason(2026, date(2026, 12, 20)))

    def test_a_future_season_is_always_preseason(self):
        self.assertTrue(archive.is_preseason(2027, date(2026, 12, 20)))

    def test_a_past_season_never_is(self):
        self.assertFalse(archive.is_preseason(2025, date(2026, 1, 2)))


class TestRecordSnapshot(_ArchiveFixture):
    def test_records_each_source_separately(self):
        written = archive.record_snapshot(2026, SAMPLES, PLAYERS, today=date(2026, 8, 24))
        self.assertEqual(written, ["fftoday", "sleeper_projections"])
        self.assertEqual(
            archive.archived_sources(2026),
            {"fftoday": 1, "sleeper_projections": 2},
        )

    def test_stat_lines_survive_the_round_trip(self):
        archive.record_snapshot(2026, SAMPLES, PLAYERS, today=date(2026, 8, 24))
        with open(archive.archive_path(2026), encoding="utf-8") as handle:
            data = json.load(handle)
        entry = data["sources"]["fftoday"]["players"]["joshallen|QB"]
        self.assertEqual(entry["name"], "Josh Allen")
        self.assertEqual(entry["pos"], "QB")
        self.assertEqual(entry["stats"]["pass_yd"], 4200.0)

    def test_in_season_pull_is_not_archived(self):
        self.assertEqual(
            archive.record_snapshot(2026, SAMPLES, PLAYERS, today=date(2026, 11, 3)), [])
        self.assertFalse(os.path.exists(archive.archive_path(2026)))

    def test_first_snapshot_of_a_season_wins(self):
        archive.record_snapshot(2026, SAMPLES, PLAYERS, today=date(2026, 7, 1))
        revised = {"joshallen|QB": [("fftoday", {"pass_yd": 1.0, "pass_td": 0.0})]}
        written = archive.record_snapshot(2026, revised, PLAYERS, today=date(2026, 8, 24))
        self.assertEqual(written, [])
        stats = archive.load_archive(2026)["sources"]["fftoday"]["players"]["joshallen|QB"]["stats"]
        self.assertEqual(stats["pass_yd"], 4200.0, "a later pull must not overwrite a preseason record")

    def test_a_new_source_is_added_without_touching_the_others(self):
        archive.record_snapshot(2026, SAMPLES, PLAYERS, today=date(2026, 7, 1))
        extra = {"joshallen|QB": [("espn", {"pass_yd": 4100.0})]}
        self.assertEqual(
            archive.record_snapshot(2026, extra, PLAYERS, today=date(2026, 8, 1)), ["espn"])
        self.assertEqual(sorted(archive.archived_sources(2026)),
                         ["espn", "fftoday", "sleeper_projections"])

    def test_force_overwrites_deliberately(self):
        archive.record_snapshot(2026, SAMPLES, PLAYERS, today=date(2026, 7, 1))
        revised = {"joshallen|QB": [("fftoday", {"pass_yd": 4500.0})]}
        archive.record_snapshot(2026, revised, PLAYERS, today=date(2026, 11, 1), force=True)
        stats = archive.load_archive(2026)["sources"]["fftoday"]["players"]["joshallen|QB"]["stats"]
        self.assertEqual(stats["pass_yd"], 4500.0)

    def test_empty_samples_write_nothing(self):
        self.assertEqual(archive.record_snapshot(2026, {}, {}, today=date(2026, 8, 1)), [])
        self.assertFalse(os.path.exists(archive.archive_path(2026)))


class TestGrading(_ArchiveFixture):
    def test_archived_points_are_keyed_for_the_backtest(self):
        archive.record_snapshot(2026, SAMPLES, PLAYERS, today=date(2026, 8, 24))
        pts = archive.archived_projection_points(
            2026, "fftoday", {"pass_yd": 0.04, "pass_td": 4.0})
        # 4200 * 0.04 + 32 * 4 = 168 + 128
        self.assertAlmostEqual(pts["josh allen|QB"], 296.0)

    def test_missing_season_grades_as_empty(self):
        self.assertEqual(archive.archived_projection_points(1999, "fftoday", {}), {})

    def test_corrupt_archive_degrades_to_empty(self):
        os.makedirs(os.path.dirname(archive.archive_path(2026)), exist_ok=True)
        with open(archive.archive_path(2026), "w", encoding="utf-8") as handle:
            handle.write("{not json")
        self.assertEqual(archive.load_archive(2026), {"season": 2026, "sources": {}})


if __name__ == "__main__":
    unittest.main()
