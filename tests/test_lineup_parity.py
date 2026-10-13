"""Pin the engine's lineup assignment and the browser's copy to one fixture file.

The lineup is assigned twice. ``draft_assistant/slot_assignment.py`` does it for
the engine (``draft_value.roster_value``, ``scoring_utils.needs_by_position``,
rollout feasibility); ``buildLineup``/``getRosterNeeds`` in
``web/static/components/shared-utils.js`` do it again for the draft room's team
panel and the waiver roster panel. Nothing made the two agree, so a change to
either one showed the user a lineup the recommendations were not computed for.

``tests/fixtures/lineup_parity.json`` is the contract. This module is the Python
half: it rebuilds the file from production code, fails if the checked-in copy
differs, and checks every case against an exhaustive search so the file cannot
simply enshrine a bug both sides share. ``scripts/check_lineup_parity.js`` is
the browser half and replays the same file through ``shared-utils.js``.

After an intended change, regenerate from the repository root and re-run both:

    python -m tests.test_lineup_parity --write
    node scripts/check_lineup_parity.js

What a case pins, and why only that:

* ``starters``/``points`` - the ids in the best lineup and their total. Points
  are distinct within a case, which makes the best lineup unique; with ties
  the two sides may legitimately seat different equal-valued players.
* ``open`` - starter slots still empty. ``IR`` is a roster slot but never a
  lineup slot, and bench seats are not starters.
* ``needs`` - positions where one more player would fill another starter slot.
  The two sides report needs differently BY DESIGN: ``getRosterNeeds`` returns
  exactly this list, while ``needs_by_position`` counts open slots per roster
  key (``{"RB": 1, "WRTE": 1, ...}``). The comparable reading of the Python
  result, used here, is "adding this position lowers the total". The per-key
  split is not compared: when overlapping flex slots are not all filled, which
  one is called the empty one is arbitrary, and the two sides choose differently.
* ``bench`` - who is seated when there are more spare players than bench seats.
  Both sides rank spares by projection times the same per-position multiplier.
  The search below does not re-derive this; it is pinned so the browser's copy
  of the multipliers cannot drift from ``draft_value._bench_multiplier``.
"""
import itertools
import json
import sys
import unittest
import zlib
from functools import lru_cache
from pathlib import Path

from draft_assistant.draft_value import _bench_multiplier, roster_value
from draft_assistant.models import FLEX_TYPES, LeagueConfig, Player
from draft_assistant.scoring_utils import flex_need_for_position, needs_by_position
from draft_assistant.slot_assignment import STARTER_POSITIONS, filled_starter_count
from tests.test_slot_assignment import exhaustive_lineup as every_player_search

FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "lineup_parity.json"
REGENERATE = "python -m tests.test_lineup_parity --write"
NOT_LINEUP_SLOTS = ("BN", "BENCH", "IR")

ABOUT = [
    "Lineup results that draft_assistant/slot_assignment.py (the engine) and buildLineup/getRosterNeeds in"
    " draft_assistant/web/static/components/shared-utils.js (the browser) must both reproduce.",
    "Generated from the Python side - never edit by hand. tests/test_lineup_parity.py fails when this file is"
    " stale and checks every case against an exhaustive search; scripts/check_lineup_parity.js replays it"
    " through the browser code.",
    "Each roster lists its slots once. A case's players are [id, pos, projPts]; points are distinct within a"
    " case, so exactly one lineup is best. Grid case names are the QB/RB/WR/TE counts; draft case names are"
    " <script>@<picks made>.",
    "starters: ids in the best lineup. points: their total. open: starter slots still empty (IR is a roster"
    " slot but never a lineup slot). bench: ids seated on BN/BENCH when spares outnumber the seats.",
    "needs: positions where one more player would fill another starter slot. getRosterNeeds returns this"
    " list; Python's needs_by_position counts open slots per roster key instead, so its comparable reading"
    " is 'adding this position lowers the total'.",
    "Not pinned, because neither side defines it: which of several overlapping flex slots is the empty one,"
    " and the order of equally valued players.",
]

# The six overlapping-flex shapes tests/test_slot_assignment.py proves against
# its own exhaustive reference, crossed below with 0-2 players at each of
# QB/RB/WR/TE: the 486 small rosters.
GRID_ROSTERS = [
    {"WRTE": 1, "RBWR": 1},
    {"WRTE": 1, "RBWR": 1, "SUPERFLEX": 1},
    {"WR": 1, "RBWR": 1, "WRTE": 1},
    {"FLEX": 1, "WRTE": 1, "SUPERFLEX": 1},
    {"QB": 1, "OP": 1, "RBWR": 1},
    {"TE": 1, "WRTE": 2},
]
GRID_POSITIONS = ("QB", "RB", "WR", "TE")

# Whole leagues, sampled as a draft fills them. The small grid has no K, DST,
# bench or IR, and never has enough players for the bench to turn one away.
LEAGUE_ROSTERS = {
    "one-flex": {"QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 1, "K": 1, "DST": 1, "BN": 6},
    # league.config.json's own shape.
    "two-flex-ir": {"QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 2, "K": 1, "DST": 1, "BN": 7, "IR": 1},
    "superflex": {
        "QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 1, "SUPERFLEX": 1, "K": 1, "DST": 1, "BN": 5, "IR": 2,
    },
    "wrte-rbwr": {"QB": 1, "RB": 2, "WR": 2, "TE": 1, "WRTE": 1, "RBWR": 1, "K": 1, "DST": 1, "BN": 5, "IR": 1},
    # BENCH is the alias both sides accept for BN.
    "op-bench-alias": {"QB": 1, "RB": 2, "WR": 2, "TE": 1, "OP": 1, "K": 1, "DST": 1, "BENCH": 4},
    "every-flex": {
        "QB": 1, "RB": 1, "WR": 1, "TE": 1, "WRTE": 1, "RBWR": 1, "FLEX": 1, "SUPERFLEX": 1,
        "K": 1, "DST": 1, "BN": 3,
    },
}
DRAFTS = {
    "balanced": "RB WR WR RB TE QB WR RB WR RB TE QB WR RB DST K QB",
    "wr-heavy": "WR WR QB WR TE QB WR RB RB WR TE RB QB K DST WR RB",
    "rb-heavy": "RB RB RB WR RB WR QB RB WR WR K DST TE WR QB TE K",
}
DRAFT_CHECKPOINTS = (3, 6, 9, 11, 13, 15, 17)

# Hand-picked cases the generated ones cannot be relied on to hit.
EDGE_ROSTERS = [
    # The regression slot_assignment.py exists for: the WR must move to R/W so
    # the TE can start in W/T, whichever order the players arrive in.
    ("wr-moves-so-te-starts", {"WRTE": 1, "RBWR": 1},
     [["wr", "WR", 110], ["te", "TE", 100], ["rb", "RB", 1]]),
    # A required slot is filled even by a projection that lowers the total.
    ("negative-still-starts", {"QB": 1, "FLEX": 1, "BN": 1},
     [["QB0", "QB", -3], ["RB0", "RB", -11], ["WR0", "WR", -5]]),
    # 0 is falsy in JavaScript. A zero projection is still a player, and still
    # outranks a negative one for the RB slot.
    ("zero-projection", {"RB": 1, "FLEX": 1},
     [["RB0", "RB", 0], ["RB1", "RB", -4], ["WR0", "WR", 3]]),
    # Raw points would bench the spare QB (299) and the TE (121); the
    # multipliers seat the RB first and leave the TE out behind a 91-point WR.
    ("bench-one-seat", {"QB": 1, "RB": 1, "WR": 1, "BN": 1},
     [["QB0", "QB", 301], ["QB1", "QB", 299], ["RB0", "RB", 201], ["RB1", "RB", 151],
      ["WR0", "WR", 181], ["WR1", "WR", 91], ["TE0", "TE", 121]]),
    ("bench-three-seats", {"QB": 1, "RB": 1, "WR": 1, "BN": 3},
     [["QB0", "QB", 301], ["QB1", "QB", 299], ["RB0", "RB", 201], ["RB1", "RB", 151],
      ["WR0", "WR", 181], ["WR1", "WR", 91], ["TE0", "TE", 121]]),
    # Two spare players and two IR slots: nobody is seated, nothing is open.
    ("ir-seats-nobody", {"QB": 1, "RB": 1, "IR": 2},
     [["QB0", "QB", 21], ["QB1", "QB", 15], ["RB0", "RB", 9], ["RB1", "RB", 5]]),
    # Every other projection here is a whole number and no real one is, so a
    # side that rounded or truncated before ranking passed every case. Each
    # pair below collapses to one value under round, floor and ceil alike, and
    # the better player has the later id and comes later in the list - so
    # either side's tie-break would then start the wrong RB and flex the TE.
    ("fractions-decide", {"RB": 1, "FLEX": 1, "BN": 1},
     [["RB0", "RB", 100.5], ["RB1", "RB", 100.75], ["TE0", "TE", 110.5], ["WR0", "WR", 110.75]]),
    # No roster above has a second QB, TE, K or DST slot, a third RB or WR
    # slot, or a third FLEX - though two-QB and three-WR leagues are ordinary.
    # A side that stopped counting at the usual number passed every case, so
    # this one fills one more of everything and leaves a single TE out.
    ("one-more-of-every-slot", {"QB": 2, "RB": 3, "WR": 3, "TE": 2, "FLEX": 3, "K": 2, "DST": 2},
     [["QB0", "QB", 351], ["QB1", "QB", 331],
      ["RB0", "RB", 291], ["RB1", "RB", 271], ["RB2", "RB", 251], ["RB3", "RB", 171],
      ["WR0", "WR", 281], ["WR1", "WR", 261], ["WR2", "WR", 241], ["WR3", "WR", 181], ["WR4", "WR", 161],
      ["TE0", "TE", 221], ["TE1", "TE", 201], ["TE2", "TE", 151],
      ["K0", "K", 141], ["K1", "K", 131], ["DST0", "DST", 121], ["DST1", "DST", 111]]),
]


def _draws(label):
    """Deterministic integers for one case, seeded by its name.

    A hand-rolled LCG rather than ``random``: the checked-in file is compared
    character for character on every supported Python, and the stdlib only
    promises ``Random.random()`` stable across versions - not ``shuffle`` or
    ``sample``. Seeding by name keeps one added case from renumbering the rest.
    """
    state = zlib.crc32(label.encode("utf-8"))
    while True:
        state = (state * 6364136223846793005 + 1442695040888963407) % 2 ** 64
        yield state >> 33


def _scored(positions, label):
    """Give each position an id and a distinct projection, in shuffled order.

    Projections are odd on purpose. The bench multipliers are .08/.18/.12, and
    two spares at different positions can only tie (.18a == .12b, .18a == .08b,
    .12a == .08b) when ``a`` is even - so odd points keep the bench unambiguous.
    The shuffle keeps either side from leaning on the order players arrive in.
    """
    draws = _draws(label)
    seen = {}
    players = []
    for position in positions:
        points = 2 * (next(draws) % 200) + 1
        while any(points == other[2] for other in players):
            points = 2 * (next(draws) % 200) + 1
        number = seen[position] = seen.get(position, -1) + 1
        players.append([f"{position}{number}", position, points])
    for index in range(len(players) - 1, 0, -1):
        swap = next(draws) % (index + 1)
        players[index], players[swap] = players[swap], players[index]
    return players


def production_case(name, slots, players):
    """One fixture case, computed only from the engine's own functions."""
    # Totals are compared exactly, and each side adds its starters up in its own
    # order. Whole quarters keep every partial sum exact in binary; 187.4 would
    # fail in Node alone, on a 0.00000000000003 that is nobody's bug.
    if any(value * 4 != int(value * 4) for _, _, value in players):
        raise AssertionError(
            f"{name}: projections must be whole quarters (x.0, x.25, x.5, x.75) so both sides total them exactly."
        )
    board = [Player(pid, pid, position) for pid, position, _ in players]
    points = {pid: value for pid, _, value in players}
    lineup = roster_value(board, points, slots)
    config = LeagueConfig(1, slots, {}, {})

    def open_slots(*extra):
        # A bench bucket still contains players at their real NFL positions.
        return sum(needs_by_position(config, {"BN": board + list(extra)}).values())

    still_open = open_slots()
    needs = [
        position for position in STARTER_POSITIONS
        if open_slots(Player("need", "need", position)) < still_open
    ]

    # The one bench question neither side answers: who gets the last seat when
    # the candidates are worth the same there (every spare K and DST is worth
    # 0). Python keeps input order, the browser keeps projection order.
    starting = {id(player) for player in lineup.starters}
    spare = sorted(
        (points[player.id] * _bench_multiplier(player) for player in board if id(player) not in starting),
        reverse=True,
    )
    seats = len(lineup.bench)
    if 0 < seats < len(spare) and spare[seats - 1] == spare[seats]:
        raise AssertionError(
            f"{name}: the last bench seat is a tie, which neither implementation defines. "
            "Change the case so the cut falls between different bench values."
        )
    return {
        "name": name,
        "players": [list(player) for player in players],
        "starters": sorted(player.id for player in lineup.starters),
        "points": lineup.starter_value,
        "open": still_open,
        "needs": needs,
        "bench": sorted(player.id for player in lineup.bench),
    }


def build_document():
    """Every fixture, rebuilt in memory from production Python."""
    rosters = []
    for slots in GRID_ROSTERS:
        name = "grid " + "+".join(key if count == 1 else f"{count}{key}" for key, count in slots.items())
        cases = []
        for counts in itertools.product(range(3), repeat=len(GRID_POSITIONS)):
            case = "".join(map(str, counts))
            positions = [pos for pos, count in zip(GRID_POSITIONS, counts) for _ in range(count)]
            cases.append(production_case(case, slots, _scored(positions, f"{name}/{case}")))
        rosters.append({"name": name, "slots": slots, "cases": cases})
    for name, slots in LEAGUE_ROSTERS.items():
        cases = []
        for script, picks in DRAFTS.items():
            for made in DRAFT_CHECKPOINTS:
                case = f"{script}@{made}"
                cases.append(production_case(case, slots, _scored(picks.split()[:made], f"{name}/{case}")))
        rosters.append({"name": "draft " + name, "slots": slots, "cases": cases})
    for name, slots, players in EDGE_ROSTERS:
        rosters.append({"name": "edge " + name, "slots": slots, "cases": [production_case("only", slots, players)]})
    return {
        "about": ABOUT,
        "regenerate": REGENERATE,
        "flexTypes": {key: list(eligible) for key, eligible in FLEX_TYPES.items()},
        "rosters": rosters,
    }


def render(document):
    """Compact JSON, one case per line, so a change diffs as the cases it moved."""
    def dump(value):
        return json.dumps(value, separators=(",", ":"))

    about = ",\n".join(f"  {dump(line)}" for line in document["about"])
    rosters = []
    for roster in document["rosters"]:
        cases = ",\n".join(f"   {dump(case)}" for case in roster["cases"])
        rosters.append(
            f'  {{"name":{dump(roster["name"])},"slots":{dump(roster["slots"])},"cases":[\n{cases}\n  ]}}'
        )
    return (
        "{\n"
        f' "about":[\n{about}\n ],\n'
        f' "regenerate":{dump(document["regenerate"])},\n'
        f' "flexTypes":{dump(document["flexTypes"])},\n'
        ' "rosters":[\n' + ",\n".join(rosters) + "\n ]\n"
        "}\n"
    )


# ── The independent reference ────────────────────────────────────────────────
# No matching and no greedy order, so it shares no logic with either
# implementation. tests/test_slot_assignment.py's reference tries every player
# in every slot, which is the definition but exponential in both: even
# memoized it took over a minute across these fixtures, nearly all of it on
# the 17-player leagues. This one enumerates head-counts instead - every way of
# leaving each slot empty or handing it to one more player of an eligible
# position - and is held to the every-player search wherever that is affordable.

def _lineup_slots(slots):
    return tuple(
        FLEX_TYPES.get(key, (key,))
        for key, count in slots.items() if key not in NOT_LINEUP_SLOTS
        for _ in range(count)
    )


@lru_cache(maxsize=None)
def _seatable_head_counts(lineup_slots):
    """Every per-position head-count (in STARTER_POSITIONS order) a roster can start."""
    seatable = {(0,) * len(STARTER_POSITIONS)}
    for eligible in lineup_slots:
        seatable |= {
            counts[:index] + (counts[index] + 1,) + counts[index + 1:]
            for counts in seatable
            for index, position in enumerate(STARTER_POSITIONS) if position in eligible
        }
    return frozenset(seatable)


def most_starters(slots, have):
    """How many starter slots a roster holding ``have[position]`` players can fill."""
    return max(
        sum(counts) for counts in _seatable_head_counts(_lineup_slots(slots))
        if all(count <= have.get(position, 0) for position, count in zip(STARTER_POSITIONS, counts))
    )


def best_lineups(slots, players):
    """Every best lineup as ``(sorted ids, points)``; a sound fixture has exactly one.

    Filling more slots beats scoring more points, the order both
    implementations promise (a negative projection still starts). Players at
    one position are interchangeable to every slot, so a lineup starting ``n``
    of them is only ever best with the ``n`` highest projections.
    """
    ranked = {
        position: sorted((p for p in players if p[1] == position), key=lambda p: p[2], reverse=True)
        for position in STARTER_POSITIONS
    }
    have = {position: len(group) for position, group in ranked.items()}
    filled = most_starters(slots, have)
    lineups = []
    for counts in _seatable_head_counts(_lineup_slots(slots)):
        if sum(counts) != filled or any(n > have[pos] for pos, n in zip(STARTER_POSITIONS, counts)):
            continue
        seated = [p for pos, n in zip(STARTER_POSITIONS, counts) for p in ranked[pos][:n]]
        lineups.append((sorted(p[0] for p in seated), sum(p[2] for p in seated)))
    top = max(points for _, points in lineups)
    return [lineup for lineup in lineups if lineup[1] == top]


def _cases(document):
    for roster in document["rosters"]:
        for case in roster["cases"]:
            yield f'{roster["name"]}/{case["name"]}', roster["slots"], case


class TestLineupParityFixtures(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.document = build_document()

    def test_checked_in_file_is_what_production_python_produces(self):
        rendered = render(self.document)
        # The renderer is hand-rolled for the one-case-per-line layout; make
        # sure that never costs a field.
        self.assertEqual(json.loads(rendered), self.document)
        self.assertTrue(
            FIXTURE_PATH.is_file(),
            f"tests/fixtures/lineup_parity.json is missing. Recreate it with `{REGENERATE}`.",
        )
        checked_in = FIXTURE_PATH.read_text(encoding="utf-8")
        if checked_in == rendered:
            return
        try:
            before = {label: case for label, _, case in _cases(json.loads(checked_in))}
        except (ValueError, KeyError, TypeError):
            before = {}
        after = {label: case for label, _, case in _cases(self.document)}
        moved = sorted(label for label in before.keys() | after.keys() if before.get(label) != after.get(label))
        detail = f"{len(moved)} case(s) differ, e.g. {', '.join(moved[:5])}" if moved else "header or layout only"
        self.fail(
            f"tests/fixtures/lineup_parity.json no longer matches the Python engine ({detail}). "
            f"If the engine change is intended, regenerate with `{REGENERATE}` and commit the file - then run "
            "`node scripts/check_lineup_parity.js`, because the browser must reproduce the new file too."
        )

    def test_every_case_matches_an_exhaustive_search(self):
        for label, slots, case in _cases(self.document):
            with self.subTest(case=label):
                players = case["players"]
                projections = [value for _, _, value in players]
                # Ties would make the pinned starters one arbitrary choice of
                # several, and the two sides break ties differently.
                self.assertEqual(len(set(projections)), len(projections), "projections must be distinct")
                lineups = best_lineups(slots, players)
                self.assertEqual(len(lineups), 1, "more than one lineup is best")
                self.assertEqual((case["starters"], case["points"]), lineups[0])

                have = {}
                for _, position, _ in players:
                    have[position] = have.get(position, 0) + 1
                filled = most_starters(slots, have)
                self.assertEqual(len(case["starters"]), filled)
                self.assertEqual(case["open"], len(_lineup_slots(slots)) - filled)
                self.assertEqual(case["needs"], [
                    position for position in STARTER_POSITIONS
                    if most_starters(slots, {**have, position: have.get(position, 0) + 1}) > filled
                ])
                # Rollout feasibility counts by position instead of seating
                # players: a third reading of the same assignment.
                self.assertEqual(filled_starter_count(slots, have), filled)

    def test_reference_agrees_with_the_every_player_search(self):
        checked = 0
        for label, slots, case in _cases(self.document):
            if len(case["players"]) > 8 or len(_lineup_slots(slots)) > 4:
                continue  # the every-player search is exponential in both
            checked += 1
            board = [Player(pid, pid, position) for pid, position, _ in case["players"]]
            points = {pid: value for pid, _, value in case["players"]}
            have = {}
            for player in board:
                have[player.position] = have.get(player.position, 0) + 1
            ids, total = best_lineups(slots, case["players"])[0]
            with self.subTest(case=label):
                self.assertEqual(every_player_search(board, points, slots), (len(ids), total))
                for position in STARTER_POSITIONS:
                    one_more = board + [Player("need", "need", position)]
                    self.assertEqual(
                        every_player_search(one_more, {**points, "need": 0}, slots)[0],
                        most_starters(slots, {**have, position: have.get(position, 0) + 1}),
                    )
        self.assertGreaterEqual(checked, 486)

    def test_fixtures_keep_the_cases_that_tell_the_two_sides_apart(self):
        cases = list(_cases(self.document))
        self.assertEqual(len({label for label, _, _ in cases}), len(cases), "case names must be unique")
        grid = [label for label, _, _ in cases if label.startswith("grid ")]
        self.assertEqual(len(grid), len(GRID_ROSTERS) * 3 ** len(GRID_POSITIONS))
        self.assertGreaterEqual(len(grid), 486)

        used = {key for _, slots, _ in cases for key, count in slots.items() if count}
        # A slot type no fixture roster has could drift without failing, so a
        # flex type added to FLEX_TYPES needs a roster here too.
        self.assertEqual(set(FLEX_TYPES) | set(STARTER_POSITIONS) | set(NOT_LINEUP_SLOTS), used)

        def position(case, pid):
            return next(pos for other, pos, _ in case["players"] if other == pid)

        def started(case, pos):
            return sum(1 for pid in case["starters"] if position(case, pid) == pos)

        def spares(case):
            seated = set(case["starters"]) | set(case["bench"])
            return [player for player in case["players"] if player[0] not in seated]

        def bench_overrules_raw_points(case):
            worst_seated = min(
                (value for pid, _, value in case["players"] if pid in case["bench"]), default=None,
            )
            return worst_seated is not None and any(value > worst_seated for _, _, value in spares(case))

        def needs_a_starter_to_move(slots, case):
            # flex_need_for_position reads the per-key counts and misses these:
            # the position fits no slot counted as open, only one that frees up
            # once a starter moves. A browser port of that reading must fail.
            board = [Player(pid, pid, pos) for pid, pos, _ in case["players"]]
            by_key = needs_by_position(LeagueConfig(1, slots, {}, {}), {"BN": board})
            return any(not by_key[pos] and not flex_need_for_position(pos, by_key) for pos in case["needs"])

        def decided_by_a_fraction(slots, case):
            # Dropping the fractions seats someone else: the case a side that
            # rounds its projections gets wrong.
            board = [Player(pid, pid, pos) for pid, pos, _ in case["players"]]
            whole = {pid: int(value) for pid, _, value in case["players"]}
            return sorted(player.id for player in roster_value(board, whole, slots).starters) != case["starters"]

        situations = {
            "W/T and R/W both filled": lambda slots, case: (
                slots.get("WRTE") and slots.get("RBWR") and not case["open"]),
            "a QB starting in a superflex slot": lambda slots, case: (
                slots.get("SUPERFLEX") and started(case, "QB") > slots.get("QB", 0)),
            "two FLEX slots both filled": lambda slots, case: (
                slots.get("FLEX", 0) >= 2 and sum(started(case, pos) for pos in ("RB", "WR", "TE"))
                >= slots.get("RB", 0) + slots.get("WR", 0) + slots.get("TE", 0) + 2),
            "K and DST both starting": lambda slots, case: started(case, "K") and started(case, "DST"),
            "a bench that turns a spare away": lambda slots, case: case["bench"] and spares(case),
            "a bench ordered by multiplier, not raw points": lambda slots, case: bench_overrules_raw_points(case),
            "spares that IR does not seat": lambda slots, case: slots.get("IR") and spares(case),
            "a need only reachable by moving a starter": needs_a_starter_to_move,
            "a starter decided by a fraction of a point": decided_by_a_fraction,
            "a second QB, a third WR and a third FLEX all starting": lambda slots, case: (
                slots.get("QB", 0) >= 2 and slots.get("WR", 0) >= 3 and slots.get("FLEX", 0) >= 3
                and not case["open"]),
        }
        for situation, applies in situations.items():
            with self.subTest(situation=situation):
                self.assertTrue(any(applies(slots, case) for _, slots, case in cases))


if __name__ == "__main__":
    if "--write" in sys.argv[1:]:
        document = build_document()
        FIXTURE_PATH.parent.mkdir(exist_ok=True)
        FIXTURE_PATH.write_text(render(document), encoding="utf-8", newline="\n")
        print(f"Wrote {sum(1 for _ in _cases(document))} cases to {FIXTURE_PATH}")
        print("Now run: node scripts/check_lineup_parity.js")
    else:
        unittest.main()
