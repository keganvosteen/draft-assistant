"""Yahoo ownership must survive provider ordering and team-name changes."""
import unittest
from unittest.mock import patch

from draft_assistant.importers import yahoo
from draft_assistant.models import Player
from draft_assistant.platform_sync import synced_draft_to_picks, synced_rosters_to_picks
from draft_assistant.web.server import _draft_league_patch


def _team(key, name, position=None, owned=False):
    return {"team": [[
        {"team_key": key}, {"name": name}, {"draft_position": position},
        {"managers": [{"manager": {"is_current_login": "1" if owned else "0"}}]},
    ]]}


def _settings(num_teams=2):
    return {"league": [{"name": "Test league", "num_teams": num_teams},
                       {"settings": [{"draft_type": "snake"}]}]}


def _draft(*team_keys):
    return {"draft_results": [
        {"draft_result": {"pick": i, "team_key": key, "player_key": f"461.p.{i}"}}
        for i, key in enumerate(team_keys, 1)
    ]}


class TestYahooTeamIdentity(unittest.TestCase):
    def test_published_order_and_own_team_use_ids_even_with_duplicate_names(self):
        teams = {"teams": [_team("t.1", "Same name", "2", owned=True),
                           _team("t.2", "Same name", "1")]}

        league = yahoo._parse_league(_settings(), teams, "nfl.l.123")

        self.assertTrue(league["draftOrderReady"])
        self.assertEqual(league["teamIds"], ["t.2", "t.1"])
        self.assertEqual(league["teamNames"], ["Same name", "Same name"])
        self.assertEqual(league["draftPosition"], 2)
        self.assertEqual(league["myTeamId"], "t.1")
        self.assertFalse(league["teamSelectionRequired"])

    def test_unpublished_or_invalid_order_does_not_invent_draft_seats(self):
        for positions, count in [
            ((None, None), 2), ((1, None), 2), ((1, 1), 2),
            ((1, 3), 2), ((0, 2), 2), ((True, 2), 2),
            ((1.5, 2), 2), ((1, 2), 3),
        ]:
            with self.subTest(positions=positions, count=count):
                # The API's collection order deliberately disagrees with IDs.
                teams = {"num_teams": count, "teams": [
                    _team("t.2", "Second", positions[1], owned=True),
                    _team("t.1", "First", positions[0]),
                ]}
                league = yahoo._parse_league(_settings(count), teams, "nfl.l.123")
                picks = yahoo._parse_draft_picks(_draft("t.2", "t.1"), teams)

                self.assertFalse(league["draftOrderReady"])
                self.assertEqual(league["teamIds"], ["t.1", "t.2"])
                self.assertEqual(league["teamNames"], ["First", "Second"])
                self.assertEqual(league["myTeamId"], "t.2")
                self.assertEqual(league["draftPosition"], 2)
                self.assertEqual([pick.team_num for pick in picks], [0, 0])
                self.assertEqual([pick.provider_team_id for pick in picks], ["t.2", "t.1"])

    def test_missing_ownership_requires_explicit_selection_and_keeps_unnamed_team(self):
        teams = {"teams": [_team("t.2", "", 1), _team("t.1", "Alpha", 2)]}
        league = yahoo._parse_league(_settings(), teams, "nfl.l.123")

        self.assertEqual(league["teamIds"], ["t.2", "t.1"])
        self.assertEqual(league["teamNames"], ["t.2", "Alpha"])
        self.assertTrue(league["teamSelectionRequired"])
        self.assertNotIn("draftPosition", league)

    def test_settings_refresh_keeps_selected_team_after_rename_and_reorder(self):
        saved = {"teamIds": ["t.1", "t.2"], "teamNames": ["Alpha", "Bravo"],
                 "draftPosition": 1}
        teams = {"teams": [_team("t.1", "Renamed Alpha", 2),
                           _team("t.2", "Renamed Bravo", 1, owned=True)]}
        info = yahoo._parse_league(_settings(), teams, "nfl.l.123")

        update = _draft_league_patch(info, saved)

        self.assertEqual(update["teamIds"], ["t.2", "t.1"])
        self.assertEqual(update["draftPosition"], 2)
        self.assertFalse(update["teamSelectionRequired"])

    def test_draft_picks_remap_by_provider_team_id_when_order_changes(self):
        old_teams = {"teams": [_team("t.1", "Old Alpha", 1),
                               _team("t.2", "Old Bravo", 2)]}
        picks = yahoo._parse_draft_picks(_draft("t.2", "t.1"), old_teams)
        new_order = {"numTeams": 2, "draftType": "snake", "teamIds": ["t.2", "t.1"],
                     "teamNames": ["New Bravo", "New Alpha"]}

        result = synced_draft_to_picks(picks, [], new_order)

        self.assertEqual([pick["teamNum"] for pick in result["picks"]], [1, 2])
        self.assertEqual([pick["providerTeamId"] for pick in result["picks"]], ["t.2", "t.1"])
        self.assertFalse(result["hasTradedPicks"])
        self.assertEqual(result["nextPickNum"], 3)

    def test_draft_pick_without_team_id_fails_before_replacing_board(self):
        with self.assertRaisesRegex(ValueError, "without a team ID"):
            yahoo._parse_draft_picks(_draft(""), {"teams": []})
        picks = yahoo._parse_draft_picks(_draft("missing-team"), {"teams": []})
        with self.assertRaisesRegex(ValueError, "missing from the published order"):
            synced_draft_to_picks(picks, [], {"numTeams": 2, "teamIds": ["t.1", "t.2"]})

    def test_roster_refresh_maps_renamed_teams_using_imported_ids(self):
        league = yahoo._parse_league(_settings(), {"teams": [
            _team("t.1", "Alpha", 2), _team("t.2", "Bravo", 1),
        ]}, "nfl.l.123")
        responses = {
            "league/nfl.l.123/teams": {"teams": [
                _team("t.1", "Renamed Alpha"), _team("t.2", "Renamed Bravo"),
            ]},
            "team/t.1/roster": {"players": [{"player": [
                {"player_id": "1"}, {"name": {"full": "Josh Allen"}},
                {"display_position": "QB"},
            ]}]},
            "team/t.2/roster": {"players": [{"player": [
                {"player_id": "2"}, {"name": {"full": "Bijan Robinson"}},
                {"display_position": "RB"},
            ]}]},
        }
        players = [Player("yahoo:1", "Josh Allen", "QB"),
                   Player("yahoo:2", "Bijan Robinson", "RB")]
        with patch.object(yahoo, "_api_get", side_effect=lambda token, path: responses[path]):
            rosters = yahoo.fetch_league_rosters("unused-token", "nfl.l.123")

        result = synced_rosters_to_picks(rosters, players, league)

        self.assertEqual({pick["playerId"]: pick["teamNum"] for pick in result["picks"]},
                         {"yahoo:1": 2, "yahoo:2": 1})


if __name__ == "__main__":
    unittest.main()
