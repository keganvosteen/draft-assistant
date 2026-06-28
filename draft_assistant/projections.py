from __future__ import annotations
from typing import Dict, List, Tuple

from .models import FLEX_TYPES, Player
from .scoring import fantasy_points


FLEX_ELIGIBLE = set(FLEX_TYPES["FLEX"])


def compute_points(
    players: List[Player],
    scoring: Dict[str, float],
    use_historical: bool = True,
) -> Dict[str, float]:
    """Compute projected fantasy points per player.

    When use_historical=True (default) and a player has age or historical_stats,
    the raw projections are blended with multi-year trends and adjusted by the
    positional age curve before scoring.
    """
    pts: Dict[str, float] = {}
    for p in players:
        if use_historical and (p.age is not None or p.historical_stats):
            from .historical import adjust_projections
            adj = adjust_projections(p, scoring)
            pts[p.key()] = fantasy_points(adj, scoring)
        else:
            pts[p.key()] = fantasy_points(p.projections, scoring)
    return pts


def replacement_levels(
    players: List[Player],
    scoring: Dict[str, float],
    teams: int,
    roster: Dict[str, int],
    use_historical: bool = True,
    points_map: Dict[str, float] = None,
) -> Dict[str, float]:
    # Build per-position sorted lists
    by_pos: Dict[str, List[Player]] = {}
    for p in players:
        by_pos.setdefault(p.position, []).append(p)
    # Callers that already computed points pass them in; recomputing runs the
    # historical adjustment over every player a second time.
    pts_map = points_map if points_map is not None else compute_points(players, scoring, use_historical=use_historical)
    points_by_pos: Dict[str, List[Tuple[str, float]]] = {}
    for pos, plist in by_pos.items():
        points_by_pos[pos] = sorted(
            [(p.key(), pts_map.get(p.key(), 0.0)) for p in plist], key=lambda t: t[1], reverse=True
        )

    starters: Dict[str, int] = {}
    for pos in ["QB", "RB", "WR", "TE", "K", "DST"]:
        starters[pos] = teams * int(roster.get(pos, 0))

    # Allocate typed flex slots league-wide, most restrictive first, each to the
    # eligible position whose next-best available player is highest. A WR/TE slot
    # only deepens WR/TE replacement; it never lifts RB.
    flex_slots: List[tuple] = []
    for fkey, elig in FLEX_TYPES.items():
        flex_slots.extend([elig] * (teams * int(roster.get(fkey, 0))))
    flex_slots.sort(key=len)
    for elig in flex_slots:
        best_pos = None
        best_pts = 0.0
        for pos in elig:
            lst = points_by_pos.get(pos, [])
            i = starters.get(pos, 0)
            if i < len(lst):
                pv = lst[i][1]
                if best_pos is None or pv > best_pts:
                    best_pos, best_pts = pos, pv
        if best_pos is not None:
            starters[best_pos] += 1

    repl: Dict[str, float] = {}
    for pos, count in starters.items():
        if count <= 0:
            repl[pos] = 0.0
            continue
        lst = points_by_pos.get(pos, [])
        idx = min(max(count - 1, 0), max(len(lst) - 1, 0))
        repl[pos] = lst[idx][1] if lst else 0.0
    return repl

