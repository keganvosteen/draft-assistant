"""Suggestion engine.

`suggest_players()` ranks the board by the rest-of-draft Monte Carlo rollout in
`rollout.rollout_values()`: each player's headline score is the expected change
in your FINAL roster's total season points from drafting them now versus your
default pick, accounting for who is likely to survive to each of your later
picks. That single objective already captures positional scarcity / opportunity
cost end to end (the "take the WR now because the WR cliff is steeper than the
RB cliff" problem), so the older gradient need-multiplier is no longer layered
on top.

The need / FLEX / bye helpers below are retained because other modules and the
test-suite use them directly, and they remain a useful cheap read of roster
needs for display.
"""
from __future__ import annotations
from typing import Dict, List, Optional, Tuple

from .models import DraftState, LeagueConfig, Player
from .rollout import rollout_values

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
    """Return ranked ``(player, points, vor, score)`` tuples.

    ``score`` is the rollout engine's *impact*: the expected change in your
    final roster's total season points from drafting this player now versus your
    default greedy pick (see :func:`rollout.rollout_values`). Sorting by it puts
    the player who most improves your whole-season total at the top, which is not
    always the player who scores the most points in isolation.

    ``total_picks`` is accepted for backwards compatibility (callers still pass
    it); pick position is now derived from ``draft_state`` inside the rollout.
    """
    results = rollout_values(
        config=config,
        available=available,
        my_roster=my_roster,
        state=draft_state,
        top_n=top_n,
    )
    return [(r.player, r.points, r.vor, r.impact) for r in results]
