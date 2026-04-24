"""Suggestion engine: Monte Carlo draft-value composed with gradient need model.

Base scoring: `draft_value.draft_aware_values()` runs Monte Carlo simulation of
opponent picks via ADP to compute lineup gain, scarcity, VOR.

On top of that we apply:
  - Gradient position need multiplier (unfilled starters + draft progress)
  - FLEX overflow awareness (RB/WR/TE overflow fills FLEX slots)
  - Extra bye-week stacking penalty
"""
from __future__ import annotations
from typing import Dict, List, Optional, Tuple

from .draft_value import draft_aware_values
from .models import DraftState, LeagueConfig, Player

FLEX_ELIGIBLE = {"RB", "WR", "TE"}

# Tunable constants for the gradient need model
FILLED_BASE = 0.60
PARTIAL_FLOOR = 0.85
NEED_CEILING = 1.25
BYE_PENALTY = 0.04


def needs_by_position(
    config: LeagueConfig,
    my_roster: Dict[str, List[Player]],
) -> Dict[str, int]:
    """Return unfilled starter slots per position, including FLEX."""
    needs: Dict[str, int] = {}
    for pos in ["QB", "RB", "WR", "TE", "K", "DST"]:
        target = int(config.roster.get(pos, 0))
        have = len(my_roster.get(pos, []))
        needs[pos] = max(target - have, 0)

    # FLEX slots filled by RB/WR/TE overflow beyond starter slots
    flex_target = int(config.roster.get("FLEX", 0))
    flex_filled = 0
    for pos in FLEX_ELIGIBLE:
        starter_slots = int(config.roster.get(pos, 0))
        have = len(my_roster.get(pos, []))
        overflow = max(have - starter_slots, 0)
        flex_filled += overflow
    needs["FLEX"] = max(flex_target - flex_filled, 0)
    return needs


def _position_need_multiplier(
    position: str,
    needs: Dict[str, int],
    config: LeagueConfig,
    my_roster: Dict[str, List[Player]],
    total_picks: int,
    total_rounds: int,
) -> float:
    """Scale 0.60 (filled) to ~1.25 (empty) by need fraction + draft progress."""
    pos_need = needs.get(position, 0)
    flex_need = needs.get("FLEX", 0) if position in FLEX_ELIGIBLE else 0
    effective_need = pos_need + flex_need

    if effective_need <= 0:
        return FILLED_BASE

    starter_target = int(config.roster.get(position, 0))
    if position in FLEX_ELIGIBLE:
        starter_target += int(config.roster.get("FLEX", 0))

    need_frac = min(effective_need / max(starter_target, 1), 1.0)

    if total_rounds > 0:
        progress = min(total_picks / max(total_rounds * config.teams, 1), 1.0)
    else:
        progress = 0.0

    multiplier = PARTIAL_FLOOR + (NEED_CEILING - PARTIAL_FLOOR) * need_frac
    multiplier += 0.15 * progress * need_frac
    return multiplier


def _bye_week_penalty(
    player: Player,
    my_roster: Dict[str, List[Player]],
) -> float:
    """Extra penalty for stacking bye weeks with existing roster."""
    if not player.bye_week:
        return 0.0
    bye_counts = 0
    for pos_players in my_roster.values():
        for p in pos_players:
            if p.bye_week == player.bye_week:
                bye_counts += 1
    return BYE_PENALTY * bye_counts


def suggest_players(
    config: LeagueConfig,
    available: List[Player],
    my_roster: Dict[str, List[Player]],
    top_n: int = 12,
    total_picks: int = 0,
    draft_state: Optional[DraftState] = None,
) -> List[Tuple[Player, float, float, float]]:
    """Return ranked (Player, points, vor, score) tuples.

    Uses draft_aware_values() for the Monte Carlo base then applies our
    gradient need multiplier and extra bye penalty.
    """
    needs = needs_by_position(config, my_roster)
    total_roster_spots = sum(int(v) for v in config.roster.values())
    total_rounds = total_roster_spots

    # Wide pool so need re-ranking can promote high-need players
    pool_size = max(top_n * 4, 40)
    base = draft_aware_values(
        config=config,
        available=available,
        my_roster=my_roster,
        state=draft_state,
        top_n=pool_size,
    )

    ranked: List[Tuple[Player, float, float, float]] = []
    for item in base:
        p = item.player
        need_mult = _position_need_multiplier(
            p.position, needs, config, my_roster, total_picks, total_rounds,
        )
        bye_pen = _bye_week_penalty(p, my_roster)
        score = round(item.score * need_mult - bye_pen, 2)
        ranked.append((p, item.points, item.vor, score))

    ranked.sort(key=lambda t: (t[3], t[2], t[1]), reverse=True)
    return ranked[:top_n]
