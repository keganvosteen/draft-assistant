from __future__ import annotations
from typing import Dict, List, Optional, Sequence, Tuple

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
    points_map: Optional[Dict[str, float]] = None,
    occupied_players: Optional[Sequence[Player]] = None,
) -> Dict[str, float]:
    """Return positional replacement points for the supplied player pool.

    ``players`` is normally the complete board.  During a live draft it is the
    remaining board instead; in that case ``occupied_players`` must contain the
    players already drafted so their starter and flex slots are removed from
    league-wide demand.  Without that adjustment, the fourth remaining RB in a
    four-team/one-RB league was treated as the replacement player even after
    three teams had already drafted an RB.
    """
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

    # A live board only needs enough players to fill the starter slots that
    # remain open across the league.  Fill mandatory positional slots first;
    # drafted overflow may already occupy flex slots (or be bench depth).
    occupied_excess: Dict[str, int] = {}
    if occupied_players is not None:
        occupied_by_pos: Dict[str, int] = {}
        for player in occupied_players:
            occupied_by_pos[player.position] = occupied_by_pos.get(player.position, 0) + 1
        for pos, count in occupied_by_pos.items():
            mandatory = starters.get(pos, 0)
            used = min(count, mandatory)
            if pos in starters:
                starters[pos] -= used
            occupied_excess[pos] = count - used

    # Allocate typed flex slots league-wide, most restrictive first, each to the
    # eligible position whose next-best available player is highest. A WR/TE slot
    # only deepens WR/TE replacement; it never lifts RB.
    flex_slots: List[tuple] = []
    for fkey, elig in FLEX_TYPES.items():
        flex_slots.extend([elig] * (teams * int(roster.get(fkey, 0))))
    flex_slots.sort(key=len)

    remaining_flex_slots: List[tuple] = []
    for elig in flex_slots:
        filled_pos = None
        filled_count = 0
        for pos in elig:
            count = occupied_excess.get(pos, 0)
            if count > filled_count:
                filled_pos, filled_count = pos, count
        if filled_pos is not None:
            occupied_excess[filled_pos] -= 1
        else:
            remaining_flex_slots.append(elig)

    for elig in remaining_flex_slots:
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
        lst = points_by_pos.get(pos, [])
        if count <= 0:
            # Once league-wide starter demand is satisfied, the best remaining
            # player is the replacement option.  Giving the position a zero
            # baseline would make every bench candidate look like elite VOR.
            repl[pos] = lst[0][1] if occupied_players is not None and lst else 0.0
            continue
        idx = min(max(count - 1, 0), max(len(lst) - 1, 0))
        repl[pos] = lst[idx][1] if lst else 0.0
    return repl

