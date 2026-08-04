"""Tests for the Sleeper league import, roster sync, and live draft sync.

Everything here runs against fixture payloads shaped like Sleeper's public API,
so no network is touched.
"""
import unittest

from draft_assistant.importers.sleeper import (
    _parse_draft_picks,
    _parse_league,
    _parse_rosters,
    _parse_scoring,
)
from draft_assistant.models import Player
from draft_assistant.platform_sync import (
    SyncedRosterPlayer,
    SyncedRosterTeam,
    synced_draft_to_picks,
    synced_rosters_to_picks,
)


def _p(name, pos, team=None, metadata=None):
    return Player(id=f"{name}|{pos}", name=name, position=pos, team=team,
                  projections={}, metadata=metadata or {})


LEAGUE = {
    "league_id": "112233",
    "name": "Dynasty Warriors",
    "season": "2026",
    "status": "in_season",
    "total_rosters": 4,
    "draft_id": "998877",
    "roster_positions": ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "REC_FLEX",
                         "K", "DEF", "BN", "BN", "IR", "TAXI"],
    "scoring_settings": {"rec": 1.0, "pass_td": 4.0, "rush_yd": 0.1, "fum_lost": -2.0,
                          "int": 2.0, "fgm_0_19": 3.0, "fgm_20_29": 3.0, "fgm_30_39": 3.0,
                          "fgm_50p": 5.0},
    "settings": {"num_teams": 4},
}
USERS = [
    {"user_id": "u1", "display_name": "kegan", "metadata": {"team_name": "Gridiron Gang"}},
    {"user_id": "u2", "display_name": "riley", "metadata": {}},
    {"user_id": "u3", "display_name": "sam", "metadata": {"team_name": "Sam Slam"}},
    {"user_id": "u4", "display_name": "alex", "metadata": {}},
]
ROSTERS = [
    {"roster_id": 1, "owner_id": "u1", "players": ["4034", "SF"]},
    {"roster_id": 2, "owner_id": "u2", "players": ["6794"]},
    {"roster_id": 3, "owner_id": "u3", "players": []},
    {"roster_id": 4, "owner_id": "u4", "players": []},
]
DRAFT = {
    "draft_id": "998877",
    "type": "snake",
    "status": "drafting",
    "draft_order": {"u1": 3, "u2": 1, "u3": 4, "u4": 2},
    "slot_to_roster_id": {"1": 2, "2": 4, "3": 1, "4": 3},
}


class TestParseLeague(unittest.TestCase):
    def test_roster_positions_become_typed_slots(self):
        info = _parse_league(LEAGUE, USERS, ROSTERS, DRAFT)
        slots = info["rosterSlots"]
        self.assertEqual(slots["RB"], 2)
        self.assertEqual(slots["FLEX"], 1)
        self.assertEqual(slots["WRTE"], 1)  # REC_FLEX keeps its eligibility
        self.assertEqual(slots["DST"], 1)
        self.assertEqual(slots["BN"], 2)
        # IR / taxi are not draftable capacity and must not inflate the bench.
        self.assertNotIn("IR", slots)
        self.assertNotIn("TAXI", slots)

    def test_absent_standard_slots_are_explicit_zeros(self):
        league = {**LEAGUE, "roster_positions": ["QB", "RB", "WR", "BN"]}
        slots = _parse_league(league, USERS, ROSTERS, DRAFT)["rosterSlots"]
        self.assertEqual(slots["TE"], 0)
        self.assertEqual(slots["K"], 0)

    def test_team_names_come_back_in_draft_slot_order(self):
        info = _parse_league(LEAGUE, USERS, ROSTERS, DRAFT)
        # slot_to_roster_id: 1->roster 2 (riley), 2->roster 4 (alex),
        # 3->roster 1 (Gridiron Gang), 4->roster 3 (Sam Slam)
        self.assertEqual(info["teamNames"], ["riley", "alex", "Gridiron Gang", "Sam Slam"])

    def test_draft_position_resolved_for_known_user(self):
        info = _parse_league(LEAGUE, USERS, ROSTERS, DRAFT, user_id="u1")
        self.assertEqual(info["draftPosition"], 3)
        self.assertEqual(info["sleeperDraftId"], "998877")

    def test_no_draft_position_without_a_user(self):
        self.assertNotIn("draftPosition", _parse_league(LEAGUE, USERS, ROSTERS, DRAFT))

    def test_falls_back_to_roster_order_before_the_draft_exists(self):
        info = _parse_league(LEAGUE, USERS, ROSTERS, None)
        self.assertEqual(info["teamNames"][0], "Gridiron Gang")
        self.assertNotIn("draftPosition", info)


class TestParseScoring(unittest.TestCase):
    def test_renames_and_bucket_merges(self):
        scoring = _parse_scoring(LEAGUE["scoring_settings"])
        self.assertEqual(scoring["rec"], 1.0)
        self.assertEqual(scoring["fumbles"], -2.0)     # fum_lost
        self.assertEqual(scoring["def_int"], 2.0)      # "int" is the defense's
        self.assertEqual(scoring["fg_0_39"], 3.0)      # three buckets merged
        self.assertEqual(scoring["fg_50_59"], 5.0)     # fgm_50p spread over
        self.assertEqual(scoring["fg_60_plus"], 5.0)   # both long buckets

    def test_qb_interception_stays_separate_from_defensive_one(self):
        scoring = _parse_scoring({"pass_int": -2.0, "int": 2.0})
        self.assertEqual(scoring["pass_int"], -2.0)
        self.assertEqual(scoring["def_int"], 2.0)


class TestRosterSync(unittest.TestCase):
    def test_rosters_match_by_sleeper_id_without_names(self):
        players = [
            _p("Justin Jefferson", "WR", metadata={"sleeper_id": "4034"}),
            _p("San Francisco 49ers", "DST", team="SF", metadata={"sleeper_id": "SF"}),
            _p("Puka Nacua", "WR", metadata={"sleeper_id": "6794"}),
        ]
        teams = _parse_rosters(USERS, ROSTERS, DRAFT)
        result = synced_rosters_to_picks(teams, players, {})

        self.assertEqual(result["matched"], 3)
        self.assertEqual(result["unmatched"], [])
        drafted = {pick["playerId"] for pick in result["picks"]}
        self.assertEqual(drafted, {"Justin Jefferson|WR", "San Francisco 49ers|DST",
                                    "Puka Nacua|WR"})

    def test_rosters_match_by_name_when_the_board_has_no_sleeper_ids(self):
        # Boards built by collect-all carry nflverse ids and no sleeper_id, so
        # roster ids get resolved through Sleeper's player dictionary instead.
        players = [
            _p("Justin Jefferson", "WR"),
            _p("San Francisco 49ers", "DST", team="SF"),
            _p("Puka Nacua", "WR"),
        ]
        index = {
            "4034": {"full_name": "Justin Jefferson", "position": "WR", "team": "MIN"},
            "6794": {"first_name": "Puka", "last_name": "Nacua",
                     "fantasy_positions": ["WR"], "team": "LAR"},
            "SF": {"first_name": "San Francisco", "last_name": "49ers",
                   "position": "DEF", "team": "SF"},
        }
        teams = _parse_rosters(USERS, ROSTERS, DRAFT, index)
        result = synced_rosters_to_picks(teams, players, {})

        self.assertEqual(result["matched"], 3)
        self.assertEqual(result["unmatched"], [])

    def test_teams_are_ordered_by_draft_seat(self):
        teams = _parse_rosters(USERS, ROSTERS, DRAFT)
        self.assertEqual([t.name for t in teams],
                         ["riley", "alex", "Gridiron Gang", "Sam Slam"])

    def test_unknown_sleeper_ids_are_reported_not_matched(self):
        teams = _parse_rosters(USERS, ROSTERS, DRAFT)
        result = synced_rosters_to_picks(teams, [], {})
        self.assertEqual(result["matched"], 0)
        self.assertEqual({u["id"] for u in result["unmatched"]},
                         {"sleeper:4034", "sleeper:SF", "sleeper:6794"})


PICK_ROWS = [
    {"pick_no": 1, "round": 1, "draft_slot": 1, "roster_id": 2, "player_id": "4034",
     "metadata": {"first_name": "Justin", "last_name": "Jefferson", "position": "WR", "team": "MIN"}},
    {"pick_no": 2, "round": 1, "draft_slot": 2, "roster_id": 4, "player_id": "9999",
     "metadata": {"first_name": "Unknown", "last_name": "Rookie", "position": "RB", "team": "DAL"}},
    {"pick_no": 3, "round": 1, "draft_slot": 3, "roster_id": 1, "player_id": "SF",
     "metadata": {"first_name": "San Francisco", "last_name": "49ers", "position": "DEF", "team": "SF"}},
]


class TestDraftPickSync(unittest.TestCase):
    def setUp(self):
        self.players = [
            _p("Justin Jefferson", "WR", metadata={"sleeper_id": "4034"}),
            _p("San Francisco 49ers", "DST", team="SF", metadata={"sleeper_id": "SF"}),
        ]

    def test_picks_keep_real_numbers_and_seats(self):
        picks = _parse_draft_picks(PICK_ROWS, DRAFT)
        result = synced_draft_to_picks(picks, self.players, {"numTeams": 4})

        self.assertEqual([p["pickNum"] for p in result["picks"]], [1, 2, 3])
        self.assertEqual([p["teamNum"] for p in result["picks"]], [1, 2, 3])
        self.assertEqual(result["picks"][0]["playerId"], "Justin Jefferson|WR")
        self.assertEqual(result["picks"][2]["playerId"], "San Francisco 49ers|DST")
        self.assertEqual(result["nextPickNum"], 4)

    def test_unknown_player_is_kept_as_placeholder_so_the_clock_stays_right(self):
        picks = _parse_draft_picks(PICK_ROWS, DRAFT)
        result = synced_draft_to_picks(picks, self.players, {"numTeams": 4})

        # Three picks were made, so three picks come back — otherwise the app
        # would think it was an earlier pick than it is.
        self.assertEqual(len(result["picks"]), 3)
        self.assertEqual(result["matched"], 2)
        placeholder = result["picks"][1]
        self.assertTrue(placeholder["unmatched"])
        self.assertEqual(placeholder["playerId"], "Unknown Rookie|RB")
        self.assertEqual(result["unmatched"][0]["id"], "sleeper:9999")

    def test_out_of_order_rows_are_sorted_by_pick_number(self):
        picks = _parse_draft_picks(list(reversed(PICK_ROWS)), DRAFT)
        self.assertEqual([p.pick_no for p in picks], [1, 2, 3])

    def test_auction_picks_fall_back_to_roster_seat(self):
        rows = [{"pick_no": 1, "draft_slot": 0, "roster_id": 3, "player_id": "4034",
                 "metadata": {"first_name": "Justin", "last_name": "Jefferson",
                              "position": "WR", "team": "MIN"}}]
        picks = _parse_draft_picks(rows, DRAFT)
        # slot_to_roster_id maps roster 3 to seat 4.
        self.assertEqual(picks[0].team_num, 4)

    def test_seatless_pick_falls_back_to_snake_order(self):
        rows = [{"pick_no": 5, "player_id": "4034",
                 "metadata": {"first_name": "Justin", "last_name": "Jefferson",
                              "position": "WR", "team": "MIN"}}]
        picks = _parse_draft_picks(rows, {})
        result = synced_draft_to_picks(picks, self.players, {"numTeams": 4})
        # Pick 5 opens round 2 of a 4-team snake, which belongs to seat 4.
        self.assertEqual(result["picks"][0]["teamNum"], 4)


class TestProviderIdMatching(unittest.TestCase):
    def test_espn_matching_still_prefers_id_over_name(self):
        wrong_name = _p("John Smith", "WR", metadata={"espn_id": 7})
        local = _p("Different Imported Name", "WR", metadata={"espn_id": 42})
        rosters = [SyncedRosterTeam("T1", [
            SyncedRosterPlayer("Name Changed", "WR", provider_id="espn:42")])]

        result = synced_rosters_to_picks(rosters, [wrong_name, local], {})

        self.assertEqual(result["picks"][0]["playerId"], "Different Imported Name|WR")

    def test_a_sleeper_id_does_not_match_an_espn_id(self):
        players = [_p("Justin Jefferson", "WR", metadata={"espn_id": "4034"})]
        rosters = [SyncedRosterTeam("T1", [
            SyncedRosterPlayer("", "", provider_id="sleeper:4034")])]

        result = synced_rosters_to_picks(rosters, players, {})

        self.assertEqual(result["matched"], 0)


if __name__ == "__main__":
    unittest.main()
