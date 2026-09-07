"""Tests for DraftTracker including fuzzy matching and multi-step undo."""
import unittest

from draft_assistant.models import DraftState, LeagueConfig, Player
from draft_assistant.draft import DraftTracker


def _make_player(name, pos, adp=None):
    return Player(id=f"{name}|{pos}", name=name, position=pos, projections={}, adp=adp)


ROSTER = {"QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 1, "K": 0, "DST": 0, "BN": 5}
SCORING = {}


def _config():
    return LeagueConfig(teams=10, roster=ROSTER, scoring=SCORING, provider={})


def _state():
    return DraftState(my_team_name="Me", league_teams=["Me", "Them"])


class TestRecordPick(unittest.TestCase):
    def test_blank_pick_leaves_the_draft_unchanged(self):
        state = _state()
        tracker = DraftTracker(_config(), state, [_make_player("Josh Allen", "QB")])
        for query in ("", "   "):
            self.assertIsNone(tracker.record_pick(query, my_pick=True))
        self.assertEqual(state.picks, [])
        self.assertEqual(state.my_picks, [])

    def test_repeated_exact_pick_does_not_select_a_similar_name(self):
        players = [_make_player("John Smith", "WR"), _make_player("Josh Smith", "WR")]
        state = _state()
        tracker = DraftTracker(_config(), state, players)
        self.assertIs(tracker.record_pick("John Smith"), players[0])
        self.assertIsNone(tracker.record_pick("John Smith", my_pick=True))
        self.assertEqual(state.picks, [players[0].key()])
        self.assertEqual(state.my_picks, [])
        self.assertEqual(tracker.available_players(), [players[1]])

    def test_fuzzy_distance_takes_priority_over_adp(self):
        players = [_make_player("John Smith", "WR", adp=150),
                   _make_player("Josh Smith", "WR", adp=10)]
        tracker = DraftTracker(_config(), _state(), players)
        self.assertIs(tracker.record_pick("Jon Smith"), players[0])

    def test_position_filter_applies_before_fuzzy_matching(self):
        players = [_make_player("John Smith", "QB"), _make_player("Josh Smith", "WR")]
        tracker = DraftTracker(_config(), _state(), players)
        self.assertIs(tracker.record_pick("Jon Smith", position=" wr "), players[1])

    def test_stable_provider_id_is_persisted(self):
        player = Player(id="sleeper:123", name="Renamed Player", position="WR")
        state = _state()
        tracker = DraftTracker(_config(), state, [player])
        tracker.record_pick("Renamed Player", my_pick=True)
        self.assertEqual(state.picks, ["sleeper:123"])

    def test_legacy_saved_key_still_resolves(self):
        player = Player(id="sleeper:123", name="Renamed Player", position="WR")
        state = DraftState("Me", ["Me"], picks=["Renamed Player|WR"],
                           my_picks=["Renamed Player|WR"])
        tracker = DraftTracker(_config(), state, [player])
        self.assertEqual(tracker.available_players(), [])
        self.assertEqual(tracker.my_roster()["WR"], [player])

    def test_exact_match(self):
        players = [_make_player("Josh Allen", "QB"), _make_player("CeeDee Lamb", "WR")]
        tracker = DraftTracker(_config(), _state(), players)
        result = tracker.record_pick("Josh Allen")
        self.assertIsNotNone(result)
        self.assertEqual(result.name, "Josh Allen")

    def test_substring_match(self):
        players = [_make_player("Christian McCaffrey", "RB")]
        tracker = DraftTracker(_config(), _state(), players)
        result = tracker.record_pick("McCaffrey")
        self.assertIsNotNone(result)

    def test_fuzzy_match(self):
        players = [_make_player("Christian McCaffrey", "RB"), _make_player("Josh Allen", "QB")]
        tracker = DraftTracker(_config(), _state(), players)
        result = tracker.record_pick("Cristian Mcafrey")  # misspelled
        self.assertIsNotNone(result)
        self.assertEqual(result.name, "Christian McCaffrey")

    def test_my_pick_tracked(self):
        players = [_make_player("Josh Allen", "QB")]
        state = _state()
        tracker = DraftTracker(_config(), state, players)
        tracker.record_pick("Josh Allen", my_pick=True)
        self.assertEqual(len(state.my_picks), 1)

    def test_no_match(self):
        players = [_make_player("Josh Allen", "QB")]
        tracker = DraftTracker(_config(), _state(), players)
        result = tracker.record_pick("ZZZZZZZZZZZZZZZ")
        self.assertIsNone(result)

    def test_ambiguous_match_prefers_lower_adp(self):
        # Two "Lamb" substring matches: the one with the better ADP is the
        # player far more likely to be the one actually drafted.
        players = [
            _make_player("Backup Lamb", "WR", adp=180.0),
            _make_player("CeeDee Lamb", "WR", adp=8.0),
        ]
        tracker = DraftTracker(_config(), _state(), players)
        result = tracker.record_pick("Lamb")
        self.assertEqual(result.name, "CeeDee Lamb")

    def test_short_query_requires_close_match(self):
        # Short queries only get 1 edit of slack: "Ba Nx" (2 edits from
        # "Bo Nix") must not match, while a 1-edit typo still does.
        players = [_make_player("Bo Nix", "QB")]
        tracker = DraftTracker(_config(), _state(), players)
        self.assertIsNone(tracker.record_pick("Ba Nx"))
        result = tracker.record_pick("Bo Nyx")
        self.assertIsNotNone(result)
        self.assertEqual(result.name, "Bo Nix")


class TestUndo(unittest.TestCase):
    def test_undo_resolves_legacy_and_stable_keys_for_personal_roster(self):
        player = Player(id="sleeper:123", name="Renamed Player", position="WR")
        state = DraftState("Me", ["Me"], picks=[player.key()],
                           my_picks=[player.legacy_key()])
        tracker = DraftTracker(_config(), state, [player])
        self.assertEqual(tracker.undo(), [player.key()])
        self.assertEqual(state.my_picks, [])
        self.assertEqual(tracker.my_roster(), {})

    def test_single_undo(self):
        players = [_make_player("Josh Allen", "QB"), _make_player("CeeDee Lamb", "WR")]
        state = _state()
        tracker = DraftTracker(_config(), state, players)
        tracker.record_pick("Josh Allen")
        tracker.record_pick("CeeDee Lamb")
        undone = tracker.undo(1)
        self.assertEqual(len(undone), 1)
        self.assertEqual(len(state.picks), 1)

    def test_multi_step_undo(self):
        players = [_make_player("Josh Allen", "QB"), _make_player("CeeDee Lamb", "WR")]
        state = _state()
        tracker = DraftTracker(_config(), state, players)
        tracker.record_pick("Josh Allen")
        tracker.record_pick("CeeDee Lamb")
        undone = tracker.undo(2)
        self.assertEqual(len(undone), 2)
        self.assertEqual(len(state.picks), 0)

    def test_undo_more_than_available(self):
        players = [_make_player("Josh Allen", "QB")]
        state = _state()
        tracker = DraftTracker(_config(), state, players)
        tracker.record_pick("Josh Allen")
        undone = tracker.undo(5)
        self.assertEqual(len(undone), 1)


class TestDraftLog(unittest.TestCase):
    def test_log_records_picks(self):
        players = [_make_player("Josh Allen", "QB"), _make_player("CeeDee Lamb", "WR")]
        state = _state()
        tracker = DraftTracker(_config(), state, players)
        tracker.record_pick("Josh Allen", my_pick=True)
        tracker.record_pick("CeeDee Lamb", my_pick=False)
        log = tracker.draft_log()
        self.assertEqual(len(log), 2)
        self.assertTrue(log[0][2])   # first pick is mine
        self.assertFalse(log[1][2])  # second is not


if __name__ == "__main__":
    unittest.main()
