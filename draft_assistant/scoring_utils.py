"""Shared scoring and positional need utilities.

Extracts position-need multiplier calculations and roster need helpers into a neutral
module to eliminate circular dependencies between `suggest.py` and `rollout.py`.
"""
from __future__ import annotations
from typing import Dict, List

from .models import LeagueConfig, Player

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


def _apply_need_multiplier(score: float, mult: float) -> float:
    """Scale a score by positional need without inverting negative scores.

    Multiplying a negative score by a >1 need multiplier would rank a needed
    position BELOW a filled one late in drafts; dividing instead keeps
    "higher multiplier => ranks higher" true on both sides of zero.
    """
    if score >= 0:
        return score * mult
    return score / mult
