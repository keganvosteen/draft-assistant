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
from .scoring_utils import (
    BYE_PENALTY,
    FILLED_BASE,
    FLEX_ELIGIBLE,
    NEED_CEILING,
    PARTIAL_FLOOR,
    _apply_need_multiplier,
    _position_need_multiplier,
    needs_by_position,
)


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
