"""Lineup optimization and snake-draft pick math.

These are the primitives the rollout engine (``rollout.py``) is built on:
``roster_value`` scores a set of players as a legal starting lineup plus bench,
and the pick helpers derive who picks when from the league's own settings.

The pre-rollout scoring engine that used to live here (``draft_aware_values``
and its Monte Carlo board simulation) has been removed — the rollout engine
supersedes it and nothing called it.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Set

from .models import DraftState, FLEX_TYPES, LeagueConfig, Player


LINEUP_POSITIONS = ["QB", "RB", "WR", "TE", "K", "DST"]
FLEX_ELIGIBLE = set(FLEX_TYPES["FLEX"])


@dataclass(frozen=True)
class LineupResult:
    starter_value: float
    bench_value: float
    total_value: float
    starters: List[Player]
    bench: List[Player]


def roster_value(players: Sequence[Player], points_map: Dict[str, float], roster: Dict[str, int]) -> LineupResult:
    # Resolve each player's key + points ONCE (keyed by object identity). This
    # is the rollout engine's hottest function; previously `p.key()` rebuilt the
    # "name|POS" string inside every sort comparison and every sum, which the
    # profiler showed dominating runtime. Caching here is exact — same result,
    # far fewer string builds and dict lookups.
    pts: Dict[int, float] = {}
    pkey: Dict[int, str] = {}
    by_pos: Dict[str, List[Player]] = {}
    for player in players:
        pid = id(player)
        key = player.key()
        pkey[pid] = key
        pts[pid] = points_map.get(key, 0.0)
        by_pos.setdefault(player.position, []).append(player)
    for group in by_pos.values():
        group.sort(key=lambda p: pts[id(p)], reverse=True)

    starters: List[Player] = []
    ptr: Dict[str, int] = {}  # how many of each position are already starting
    for position in LINEUP_POSITIONS:
        count = max(0, int(roster.get(position, 0)))
        group = by_pos.get(position, [])
        starters.extend(group[:count])
        ptr[position] = min(count, len(group))

    # Typed flex slots: fill the most restrictive (e.g. WR/TE) first, each taking
    # the best still-unstarted ELIGIBLE player — so a WR/TE slot never takes an
    # RB, a superflex can take a QB, etc.
    flex_slots: List[tuple] = []
    for fkey, elig in FLEX_TYPES.items():
        flex_slots.extend([elig] * max(0, int(roster.get(fkey, 0))))
    flex_slots.sort(key=len)
    for elig in flex_slots:
        best_pos = None
        best_pts = 0.0
        for pos in elig:
            group = by_pos.get(pos, [])
            i = ptr.get(pos, 0)
            if i < len(group):
                pv = pts[id(group[i])]
                if best_pos is None or pv > best_pts:
                    best_pos, best_pts = pos, pv
        if best_pos is not None:
            starters.append(by_pos[best_pos][ptr[best_pos]])
            ptr[best_pos] += 1

    used: Set[str] = {pkey[id(player)] for player in starters}
    bench_count = max(0, int(roster.get("BN", roster.get("BENCH", 0))))
    bench_pool = [player for player in players if pkey[id(player)] not in used]
    bench_pool.sort(key=lambda p: pts[id(p)], reverse=True)
    bench = bench_pool[:bench_count]

    starter_value = sum(pts[id(player)] for player in starters)
    bench_value = sum(pts[id(player)] * _bench_multiplier(player) for player in bench)
    return LineupResult(
        starter_value=round(starter_value, 2),
        bench_value=round(bench_value, 2),
        total_value=round(starter_value + bench_value, 2),
        starters=starters,
        bench=bench,
    )


def _flatten_roster(my_roster: Dict[str, List[Player]]) -> List[Player]:
    players: List[Player] = []
    for group in my_roster.values():
        players.extend(group)
    return players


def _bench_multiplier(player: Player) -> float:
    if player.position in {"RB", "WR"}:
        return 0.18
    if player.position == "TE":
        return 0.12
    if player.position == "QB":
        return 0.08
    return 0.0


def _draft_slot(config: LeagueConfig, state: Optional[DraftState]) -> int:
    teams = max(1, int(config.teams))
    if state and state.my_picks:
        for my_pick in state.my_picks:
            if my_pick not in state.picks:
                continue
            overall = state.picks.index(my_pick) + 1
            round_number = (overall - 1) // teams + 1
            pick_in_round = ((overall - 1) % teams) + 1
            if round_number % 2 == 1:
                return min(max(pick_in_round, 1), teams)
            return min(max(teams - pick_in_round + 1, 1), teams)
    settings = config.draft or {}
    return min(max(int(settings.get("slot", 1)), 1), teams)


def _snake_pick_numbers(teams: int, draft_slot: int, rounds: int) -> List[int]:
    picks: List[int] = []
    for round_number in range(1, rounds + 1):
        if round_number % 2 == 1:
            pick_in_round = draft_slot
        else:
            pick_in_round = teams - draft_slot + 1
        picks.append((round_number - 1) * teams + pick_in_round)
    return picks


def _bye_week_penalty(player: Player, roster_players: List[Player], points_map: Dict[str, float], roster: Dict[str, int]) -> float:
    if not player.bye_week or player.position in {"K", "DST"}:
        return 0.0
    lineup = roster_value(roster_players + [player], points_map, roster)
    # Count starters OTHER than the candidate sharing his bye — the candidate
    # may land on the bench, in which case subtracting one would undercount.
    shared = [
        p for p in lineup.starters
        if p.key() != player.key()
        and p.position not in {"K", "DST"}
        and p.bye_week == player.bye_week
    ]
    same_position = [p for p in shared if p.position == player.position]
    penalty = len(shared) * 0.75 + len(same_position) * 0.75
    return round(min(3.0, penalty), 2)


def _simulation_seed(config: LeagueConfig, state: Optional[DraftState]) -> int:
    pick_count = len(state.picks) if state else 0
    slot = int((config.draft or {}).get("slot", 1))
    return 7919 + pick_count * 101 + max(1, int(config.teams)) * 17 + slot
