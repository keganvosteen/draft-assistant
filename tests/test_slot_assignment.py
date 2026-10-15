"""Compare production assignment against an exhaustive independent reference."""
import itertools
import unittest

from draft_assistant.draft_value import roster_value
from draft_assistant.models import FLEX_TYPES, LeagueConfig, Player
from draft_assistant.scoring_utils import needs_by_position


def exhaustive_lineup(players, points, roster):
    slots = []
    for key, count in roster.items():
        if key in {"BN", "BENCH", "IR"}:
            continue
        slots.extend([FLEX_TYPES.get(key, (key,))] * count)

    def choose(index, remaining):
        if index == len(slots):
            return (0, 0)
        best = choose(index + 1, remaining)
        for player_index in remaining:
            player = players[player_index]
            if player.position in slots[index]:
                count, value = choose(index + 1, remaining - {player_index})
                best = max(best, (count + 1, value + points[player.key()]))
        return best

    return choose(0, set(range(len(players))))


class TestExactAssignment(unittest.TestCase):
    def test_overlapping_flex_is_independent_of_player_and_roster_order(self):
        players = [Player("wr", "WR", "WR"), Player("te", "TE", "TE"), Player("rb", "RB", "RB")]
        points = {"wr": 110, "te": 100, "rb": 1}
        for permutation in itertools.permutations(players):
            for roster in ({"WRTE": 1, "RBWR": 1}, {"RBWR": 1, "WRTE": 1}):
                with self.subTest(order=[p.id for p in permutation], roster=roster):
                    result = roster_value(permutation, points, roster)
                    self.assertEqual(result.starter_value, 210)
                    self.assertEqual({p.id for p in result.starters}, {"wr", "te"})

    def test_lineup_and_needs_match_exhaustive_small_rosters(self):
        configurations = [
            {"WRTE": 1, "RBWR": 1},
            {"WRTE": 1, "RBWR": 1, "SUPERFLEX": 1},
            {"WR": 1, "RBWR": 1, "WRTE": 1},
            {"FLEX": 1, "WRTE": 1, "SUPERFLEX": 1},
            {"QB": 1, "OP": 1, "RBWR": 1},
            {"TE": 1, "WRTE": 2},
        ]
        for counts in itertools.product(range(3), repeat=4):
            players = [
                Player(f"{pos}{index}", f"{pos}{index}", pos)
                for pos, count in zip(("QB", "RB", "WR", "TE"), counts)
                for index in range(count)
            ]
            points = {player.key(): 150 - i * 17 for i, player in enumerate(players)}
            for roster in configurations:
                with self.subTest(counts=counts, roster=roster):
                    expected_count, expected_points = exhaustive_lineup(players, points, roster)
                    actual = roster_value(players, points, roster)
                    self.assertEqual(len(actual.starters), expected_count)
                    self.assertEqual(actual.starter_value, expected_points)
                    config = LeagueConfig(1, roster, {}, {})
                    # A bench bucket still contains players at their real NFL positions.
                    needs = needs_by_position(config, {"BN": players})
                    self.assertEqual(sum(needs.values()), sum(roster.values()) - expected_count)


if __name__ == "__main__":
    unittest.main()
