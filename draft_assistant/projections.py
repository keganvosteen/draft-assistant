from __future__ import annotations
from typing import Dict, List, Tuple

from .models import Player
from .scoring import fantasy_points


FLEX_ELIGIBLE = {"RB", "WR", "TE"}


def compute_points(players: List[Player], scoring: Dict[str, float]) -> Dict[str, float]:
    pts: Dict[str, float] = {}
    for p in players:
        pts[p.key()] = fantasy_points(p.projections, scoring)
    return pts


def _allocate_flex_baseline(points_by_pos: Dict[str, List[Tuple[str, float]]], flex_slots: int) -> Dict[str, int]:
    # Merge top candidates across eligible positions and allocate flex to those with
    # highest points, then count how many per position.
    pool: List[Tuple[str, float, str]] = []  # (key, pts, pos)
    for pos in FLEX_ELIGIBLE:
        for key, pts in points_by_pos.get(pos, []):
            pool.append((key, pts, pos))
    pool.sort(key=lambda t: t[1], reverse=True)
    alloc: Dict[str, int] = {"RB": 0, "WR": 0, "TE": 0}
    for i in range(min(flex_slots, len(pool))):
        alloc[pool[i][2]] += 1
    return alloc


def replacement_levels(players: List[Player], scoring: Dict[str, float], teams: int, roster: Dict[str, int]) -> Dict[str, float]:
    # Build per-position sorted lists
    by_pos: Dict[str, List[Player]] = {}
    for p in players:
        by_pos.setdefault(p.position, []).append(p)
    pts_map = compute_points(players, scoring)
    points_by_pos: Dict[str, List[Tuple[str, float]]] = {}
    for pos, plist in by_pos.items():
        points_by_pos[pos] = sorted(
            [(p.key(), pts_map.get(p.key(), 0.0)) for p in plist], key=lambda t: t[1], reverse=True
        )

    starters: Dict[str, int] = {}
    for pos in ["QB", "RB", "WR", "TE", "K", "DST"]:
        starters[pos] = teams * int(roster.get(pos, 0))

    # Distribute FLEX among eligible positions
    flex_slots = teams * int(roster.get("FLEX", 0))
    flex_alloc = _allocate_flex_baseline(points_by_pos, flex_slots)
    starters["RB"] += flex_alloc.get("RB", 0)
    starters["WR"] += flex_alloc.get("WR", 0)
    starters["TE"] += flex_alloc.get("TE", 0)

    repl: Dict[str, float] = {}
    for pos, count in starters.items():
        if count <= 0:
            repl[pos] = 0.0
            continue
        lst = points_by_pos.get(pos, [])
        idx = min(max(count - 1, 0), max(len(lst) - 1, 0))
        repl[pos] = lst[idx][1] if lst else 0.0
    return repl

