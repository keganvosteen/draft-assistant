"""signals_for_player answers from a per-context index instead of a scan.

Two things have to hold. The answers are exactly what the scan gave, in the
same order -- primary_availability returns the first injury it meets, so order
is behaviour. And they stay that way however the signal list is changed after
the first lookup, because nothing obliges a caller to announce a change.
"""
import random
import sys
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone

from draft_assistant.context import (
    _parse_time,
    _replace_signals,
    confidence_for_player,
    context_to_dict,
    is_candidate_eligible,
    player_context_ids,
    primary_availability,
    season_adjusted_players,
    season_ending,
    signal_summary,
    signals_for_player,
    urgency_for_player,
    weekly_availability_factor,
)
from draft_assistant.models import Player, PlayerContext, PlayerSignal


NOW = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
PAST = (NOW - timedelta(days=1)).isoformat()
FUTURE = (NOW + timedelta(days=1)).isoformat()
SOURCES = ("sleeper_players", "sleeper_trending", "nflverse_injuries", "nflverse_snaps")
VALUES = {
    "injury": ("Questionable", "Doubtful", "Out", "Out for season"),
    "practice": ("Limited", "Full", "DNP"),
    "roster_status": ("Active", "Free Agent", "Practice Squad", "Injured Reserve"),
    "depth_chart": ("WR1", "RB2"),
    "trend_add": ("80", "5"),
    "trend_drop": ("40", "5"),
    "snap_share": ("71%",),
}


def _scan(context, player, now):
    """signals_for_player as it was before the index: one pass over everything."""
    aliases = set(player_context_ids(player))
    kept = []
    for signal in context.signals:
        if signal.player_id not in aliases:
            continue
        expires = _parse_time(signal.expires_at)
        if expires is not None and expires < now:
            continue
        if signal.effective_week is not None and signal.kind in {"injury", "practice"}:
            if signal.effective_week != context.selected_week:
                continue
        kept.append(signal)
    return kept


def _board():
    """Rows reachable through every id shape player_context_ids produces."""
    players = []
    for n in range(1, 31):
        gsis = f"00-{n:04d}"
        shape = n % 6
        if shape == 0:  # Sleeper-keyed row that also knows its gsis id
            players.append(Player(f"sleeper:{n}", f"Sleeper Row {n}", "WR",
                                  metadata={"sleeper_id": str(n), "gsis_id": gsis}))
        elif shape == 1:  # nflverse-keyed row, whose signals arrive under gsis:
            players.append(Player(f"nflverse:{gsis}", f"Nflverse Row {n}", "RB"))
        elif shape == 2:
            players.append(Player(f"gsis:{gsis}", f"Gsis Row {n}", "TE"))
        elif shape == 3:  # refreshed board that kept old providers only as aliases
            players.append(Player(f"ffc:{n}", f"Alias Row {n}", "QB", metadata={
                "identity_aliases": [f"sleeper:{n}", f"nflverse:{gsis}"]}))
        elif shape == 4:  # hand-authored: nothing to join on but the name
            players.append(Player("", f"Named Row {n}", "RB"))
        else:  # rows sharing a name share its name: signals
            players.append(Player(f"espn:{n}", "Shared Name", "WR"))
    return players


def _signal_ids(players):
    """Every id the first 24 rows answer to, plus ids no row owns.

    The last six rows are left out on purpose: a player the feed has never
    mentioned is the common case on a real board.
    """
    ids = [identity for player in players[:24] for identity in player_context_ids(player)]
    return sorted(set(ids)) + ["sleeper:9001", "gsis:00-9999", "name:nobodyontheboard"]


def _random_signal(rng, ids):
    kind = rng.choice(sorted(VALUES))
    return PlayerSignal(
        player_id=rng.choice(ids), kind=kind, value=rng.choice(VALUES[kind]),
        source=rng.choice(SOURCES), observed_at=NOW.isoformat(),
        effective_week=rng.choice((None, 1, 2, 3)),
        expires_at=rng.choice((None, PAST, FUTURE, "not a timestamp")),
    )


def _signal(kind, value, player_id="sleeper:1", week=None):
    return PlayerSignal(player_id=player_id, kind=kind, value=value, source="test",
                        observed_at=NOW.isoformat(), effective_week=week)


class _CountedSignals(list):
    """A signal list that counts every pass Python makes over it."""

    passes = 0

    def __iter__(self):
        self.passes += 1
        return super().__iter__()


class TestIndexedLookupMatchesTheScan(unittest.TestCase):
    def setUp(self):
        self.players = _board()
        self.ids = _signal_ids(self.players)

    def assertMatchesScan(self, context, now=NOW):
        for player in self.players:
            self.assertEqual(
                signals_for_player(context, player, now=now), _scan(context, player, now),
                player.key())

    def _note_coverage(self, seen, context):
        for player in self.players:
            aliases = set(player_context_ids(player))
            mine = [signal for signal in context.signals if signal.player_id in aliases]
            if not mine:
                seen.add("no signals")
            if len({signal.player_id for signal in mine}) > 1:
                seen.add("several ids")
            for signal in mine:
                seen.add(signal.player_id.split(":")[0] + ":")
                expires = _parse_time(signal.expires_at)
                if expires is not None and expires < NOW:
                    seen.add("expired")
                if (signal.kind in {"injury", "practice"}
                        and signal.effective_week not in (None, context.selected_week)):
                    seen.add("wrong week")

    def test_random_contexts_survive_every_kind_of_change(self):
        seen = set()
        for seed in range(40):
            rng = random.Random(seed)
            fresh = lambda count: [_random_signal(rng, self.ids) for _ in range(count)]
            context = PlayerContext(2026, rng.choice((1, 2, 3)),
                                    signals=fresh(rng.randint(2, 120)))
            self._note_coverage(seen, context)

            def swap_two(context):
                signals = context.signals
                signals[0], signals[-1] = signals[-1], signals[0]

            def drop_then_add(context):
                del context.signals[rng.randrange(len(context.signals))]
                context.signals.append(_random_signal(rng, self.ids))

            # Each step is a way the list can change behind the index's back.
            # Several leave both the list object and its length untouched,
            # which is exactly what an (identity, length) check cannot see.
            steps = [
                ("first lookup", lambda context: None),
                ("append", lambda context: context.signals.append(_random_signal(rng, self.ids))),
                ("replace one in place", lambda context: context.signals.__setitem__(
                    rng.randrange(len(context.signals)), _random_signal(rng, self.ids))),
                ("swap two in place", swap_two),
                ("reverse in place", lambda context: context.signals.reverse()),
                ("drop one, add one", drop_then_add),
                ("_replace_signals", lambda context: _replace_signals(
                    context, rng.choice(SOURCES), fresh(rng.randint(0, 30)))),
                ("rebind the list", lambda context: setattr(
                    context, "signals", rng.sample(context.signals, len(context.signals)))),
                ("extend", lambda context: context.signals.extend(fresh(5))),
                ("another week", lambda context: setattr(
                    context, "selected_week", context.selected_week % 3 + 1)),
                ("clear", lambda context: context.signals.clear()),
            ]
            for name, change in steps:
                with self.subTest(seed=seed, step=name):
                    change(context)
                    self.assertMatchesScan(context)
                    # Expiry is judged against the caller's clock on every
                    # lookup; it must not be frozen into the index.
                    self.assertMatchesScan(context, now=NOW + timedelta(days=30))

        # A random test that never generated the hard cases proves nothing.
        self.assertLessEqual({
            "sleeper:", "gsis:", "nflverse:", "name:", "several ids",
            "no signals", "expired", "wrong week",
        }, seen)

    def test_signals_keep_list_order_across_a_players_ids(self):
        # Sleeper and nflverse each report an injury, under different ids. Which
        # one the UI shows is decided by list order, so grouping by id must not
        # hand them back in the order of the player's ids instead.
        player = Player("sleeper:1", "Test Player", "WR",
                        metadata={"sleeper_id": "1", "gsis_id": "00-1"})
        by_gsis = _signal("injury", "Out", player_id="gsis:00-1")
        by_name = _signal("practice", "Limited", player_id="name:testplayer")
        by_sleeper = _signal("injury", "Questionable", player_id="sleeper:1")
        context = PlayerContext(2026, 1, signals=[by_gsis, by_name, by_sleeper])

        self.assertEqual(signals_for_player(context, player, now=NOW),
                         [by_gsis, by_name, by_sleeper])
        self.assertEqual(primary_availability(context, player), "Out")

        # Same list object, same length, different answer.
        context.signals.reverse()
        self.assertEqual(primary_availability(context, player), "Questionable")

    def test_reweeked_copy_answers_for_its_own_week(self):
        # free_agents.py moves a context to another week with
        # dataclasses.replace(), which shares the signal list with the original.
        player = Player("sleeper:1", "Test Player", "WR")
        this_week = _signal("injury", "Questionable", week=1)
        next_week = _signal("injury", "Out", week=2)
        context = PlayerContext(2026, 1, signals=[this_week, next_week])
        self.assertEqual(signals_for_player(context, player, now=NOW), [this_week])

        moved = replace(context, selected_week=2)
        self.assertEqual(signals_for_player(moved, player, now=NOW), [next_week])
        self.assertEqual(signals_for_player(context, player, now=NOW), [this_week])

        # One list, two contexts: a change through either reaches both.
        status = _signal("roster_status", "Free Agent")
        moved.signals.append(status)
        self.assertEqual(signals_for_player(context, player, now=NOW), [this_week, status])
        self.assertEqual(signals_for_player(moved, player, now=NOW), [next_week, status])

    def test_index_never_leaks_into_the_saved_or_compared_context(self):
        player = Player("sleeper:1", "Test Player", "WR")
        signals = [_signal("injury", "Questionable", week=1)]
        looked_up = PlayerContext(2026, 1, signals=list(signals))
        untouched = PlayerContext(2026, 1, signals=list(signals))
        self.assertEqual(len(signals_for_player(looked_up, player, now=NOW)), 1)

        self.assertEqual(context_to_dict(looked_up), context_to_dict(untouched))
        self.assertEqual(asdict(looked_up), asdict(untouched))
        self.assertEqual(looked_up, untouched)


class TestLookupsStopScanning(unittest.TestCase):
    def test_per_player_helpers_walk_the_signal_list_once(self):
        players = [
            Player(f"sleeper:{n}", f"Player {n}", "WR", projections={"rec_yd": 100},
                   metadata={"sleeper_id": str(n), "gsis_id": f"00-{n}"})
            for n in range(60)
        ]
        signals = _CountedSignals()
        for n in range(60):
            signals += [
                _signal("depth_chart", "WR2", player_id=f"sleeper:{n}"),
                _signal("injury", "Questionable", player_id=f"gsis:00-{n}", week=1),
                _signal("trend_add", "12", player_id=f"sleeper:{n}"),
            ]
        context = PlayerContext(2026, 1, signals=signals)
        self.assertEqual(signals.passes, 0)

        helpers = (
            season_ending, is_candidate_eligible, primary_availability,
            confidence_for_player, urgency_for_player, weekly_availability_factor,
            signal_summary,
        )
        for player in players:
            self.assertEqual(len(signals_for_player(context, player, now=NOW)), 3)
            for helper in helpers:
                helper(context, player)
        season_adjusted_players(players, context)

        # One pass builds the index. The scan made one per call: 540 of them
        # here, and 6,000 signals x 2,200 players x several helpers per request
        # on the real board. (The index still compares the list against its own
        # copy on each lookup; that happens in C and is not a pass in this
        # sense -- what must not come back is Python visiting every signal for
        # every player.)
        self.assertEqual(signals.passes, 1)

        # A change costs one rebuild, not a return to scanning per player.
        signals.append(_signal("roster_status", "Free Agent", player_id="sleeper:7"))
        eligible = [player for player in players if is_candidate_eligible(context, player)]
        self.assertEqual(len(eligible), 59)
        self.assertEqual(signals.passes, 2)


class TestThreadsSharingAContext(unittest.TestCase):
    def test_readers_stay_correct_while_another_thread_adds_signals(self):
        # Requests load their own context today, so this is not a path the
        # server takes -- it pins that the index does not become the reason a
        # shared context would be unsafe. The writer only ever adds signals for
        # a player the readers do not ask about, so their right answers do not
        # move while the index is rebuilt underneath them again and again.
        players = _board()
        rng = random.Random(7)
        ids = [identity for identity in _signal_ids(players) if identity != "sleeper:9001"]
        context = PlayerContext(2026, 1, signals=[_random_signal(rng, ids) for _ in range(150)])
        expected = {player.key(): _scan(context, player, NOW) for player in players}
        outsider = Player("sleeper:9001", "Outsider", "WR")
        added = [_signal("trend_add", str(n), player_id="sleeper:9001") for n in range(200)]

        wrong = []
        start = threading.Barrier(5)  # no timeouts here: nothing may depend on the clock

        def read():
            start.wait()
            for _ in range(25):
                for player in players:
                    if signals_for_player(context, player, now=NOW) != expected[player.key()]:
                        wrong.append(player.key())

        def write():
            start.wait()
            for signal in added:
                context.signals.append(signal)
                signals_for_player(context, outsider, now=NOW)

        interval = sys.getswitchinterval()
        sys.setswitchinterval(1e-5)  # make the threads actually interleave
        try:
            with ThreadPoolExecutor(max_workers=5) as pool:
                jobs = [pool.submit(read) for _ in range(4)] + [pool.submit(write)]
                for job in jobs:
                    job.result()  # a thread that raised must fail the test, not vanish
        finally:
            sys.setswitchinterval(interval)

        self.assertEqual(wrong, [])
        self.assertEqual(signals_for_player(context, outsider, now=NOW), added)


if __name__ == "__main__":
    unittest.main()
