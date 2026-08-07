"""Tests for atomic JSON persistence."""
import os
import tempfile
import threading
import unittest

from draft_assistant.models import DraftState, Player
from draft_assistant.storage import (
    atomic_write_json,
    load_players,
    load_state,
    save_players,
    save_state,
    update_state,
)


class TestAtomicWrite(unittest.TestCase):
    def test_write_and_no_leftover_temp_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "out.json")
            atomic_write_json(path, {"ok": True})
            self.assertTrue(os.path.exists(path))
            leftovers = [f for f in os.listdir(tmp) if f.endswith(".tmp")]
            self.assertEqual(leftovers, [])

    def test_failed_write_leaves_original_intact(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "out.json")
            atomic_write_json(path, {"version": 1})
            # A payload json.dump can't serialize must not clobber the file.
            with self.assertRaises(TypeError):
                atomic_write_json(path, {"bad": object()})
            with open(path, encoding="utf-8") as f:
                self.assertIn('"version": 1', f.read())
            leftovers = [f for f in os.listdir(tmp) if f.endswith(".tmp")]
            self.assertEqual(leftovers, [])


class TestStateRoundTrip(unittest.TestCase):
    def test_corrupt_state_is_preserved_and_recovers_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "draft_state.json")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("{not valid json")
            with self.assertWarns(RuntimeWarning):
                state = load_state(path)
            self.assertEqual(state.my_team_name, "My Team")
            self.assertFalse(os.path.exists(path))
            self.assertTrue(os.path.exists(path + ".corrupt"))

    def test_partial_updates_do_not_overwrite_each_other(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "draft_state.json")
            save_state(DraftState("Me", ["Me", "Them"]), path)
            barrier = threading.Barrier(2)

            def set_picks():
                barrier.wait()
                update_state(path, lambda state: setattr(state, "picks", ["a"]))

            def set_my_picks():
                barrier.wait()
                update_state(path, lambda state: setattr(state, "my_picks", ["a"]))

            threads = [threading.Thread(target=set_picks), threading.Thread(target=set_my_picks)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=5)
            state = load_state(path)
            self.assertEqual(state.picks, ["a"])
            self.assertEqual(state.my_picks, ["a"])

    def test_state_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "draft_state.json")
            state = DraftState(
                my_team_name="Me",
                league_teams=["Me", "Them"],
                picks=["A|RB", "B|WR"],
                my_picks=["A|RB"],
            )
            save_state(state, path)
            loaded = load_state(path)
            self.assertEqual(loaded.picks, ["A|RB", "B|WR"])
            self.assertEqual(loaded.my_picks, ["A|RB"])

    def test_players_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "projections.json")
            players = [Player(
                id="x", name="Test Back", position="RB", team="DET",
                age=26, experience=4,
                projections={"rush_yd": 1200.0},
                historical_stats={2025: {"rush_yd": 1100.0}},
            )]
            save_players(players, path)
            loaded = load_players(path)
            self.assertEqual(len(loaded), 1)
            self.assertEqual(loaded[0].age, 26)
            self.assertEqual(loaded[0].historical_stats[2025]["rush_yd"], 1100.0)


if __name__ == "__main__":
    unittest.main()
