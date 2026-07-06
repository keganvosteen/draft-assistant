"""Shared roster-need utilities.

The draft/waiver engines use exact lineup optimization for final scoring. These
helpers are the cheaper display/urgency model used by CLIs, panels, and legacy
tests, so they must preserve the same typed-flex eligibility semantics.
"""
from __future__ import annotations
from typing import Dict, List, Mapping

from .models import FLEX_TYPES, LeagueConfig, Player

STARTER_POSITIONS = ("QB", "RB", "WR", "TE", "K", "DST")
FLEX_ELIGIBLE = set(FLEX_TYPES["FLEX"])
ALL_FLEX_ELIGIBLE = set().union(*FLEX_TYPES.values())

# Tunable constants for the gradient need model
FILLED_BASE = 0.60
PARTIAL_FLOOR = 0.85
NEED_CEILING = 1.25
BYE_PENALTY = 0.04


def needs_by_position(
    config: LeagueConfig,
    my_roster: Dict[str, List[Player]],
) -> Dict[str, int]:
    """Return unfilled dedicated and flex starter slots by roster key."""
    needs: Dict[str, int] = {}
    counts = roster_counts(my_roster)
    for pos in STARTER_POSITIONS:
        target = int(config.roster.get(pos, 0))
        have = counts.get(pos, 0)
        needs[pos] = max(target - have, 0)

    flex_filled = flex_slots_filled(config.roster, counts)
    for fkey in FLEX_TYPES:
        target = int(config.roster.get(fkey, 0))
        needs[fkey] = max(target - flex_filled.get(fkey, 0), 0)
    return needs


def roster_counts(my_roster: Mapping[str, List[Player]]) -> Dict[str, int]:
    """Count rostered players by actual NFL fantasy position."""
    counts: Dict[str, int] = {}
    for key, players in my_roster.items():
        if key in FLEX_TYPES:
            for player in players:
                counts[player.position] = counts.get(player.position, 0) + 1
        else:
            counts[key] = counts.get(key, 0) + len(players)
    return counts


def flex_slots_filled(
    roster: Mapping[str, int],
    counts: Mapping[str, int],
) -> Dict[str, int]:
    """Allocate overflow players into typed-flex slots, most restrictive first."""
    overflow = {
        pos: max(0, int(counts.get(pos, 0)) - int(roster.get(pos, 0)))
        for pos in ALL_FLEX_ELIGIBLE
    }
    filled = {fkey: 0 for fkey in FLEX_TYPES}
    slots: List[tuple[str, tuple]] = []
    for fkey, elig in FLEX_TYPES.items():
        slots.extend((fkey, elig) for _ in range(max(0, int(roster.get(fkey, 0)))))
    slots.sort(key=lambda item: len(item[1]))

    for fkey, elig in slots:
        best_pos = max(elig, key=lambda pos: overflow.get(pos, 0))
        if overflow.get(best_pos, 0) > 0:
            overflow[best_pos] -= 1
            filled[fkey] += 1
    return filled


def flex_need_for_position(position: str, needs: Mapping[str, int]) -> int:
    """Return open flex slots that a position is eligible to fill."""
    return sum(
        int(needs.get(fkey, 0))
        for fkey, elig in FLEX_TYPES.items()
        if position in elig
    )


def flex_target_for_position(position: str, roster: Mapping[str, int]) -> int:
    """Return configured flex slot count that a position is eligible to fill."""
    return sum(
        int(roster.get(fkey, 0))
        for fkey, elig in FLEX_TYPES.items()
        if position in elig
    )


def is_player_eligible_for_roster(
    player: Player,
    my_roster: Mapping[str, List[Player]],
    roster: Mapping[str, int],
) -> bool:
    """Return whether adding player can fit a configured roster, incl. typed flex."""
    counts = roster_counts(my_roster)
    position = player.position
    if counts.get(position, 0) < int(roster.get(position, 0)):
        return True

    with_player = dict(counts)
    with_player[position] = with_player.get(position, 0) + 1
    before = flex_slots_filled(roster, counts)
    after = flex_slots_filled(roster, with_player)
    if sum(after.values()) > sum(before.values()):
        return True

    capacity = sum(
        max(0, int(value))
        for key, value in roster.items()
        if key != "IR"
    )
    current_size = sum(counts.values())
    return current_size < capacity


def position_need_multiplier(
    position: str,
    needs: Mapping[str, int],
    config: LeagueConfig,
    my_roster: Dict[str, List[Player]],
    total_picks: int,
    total_rounds: int,
) -> float:
    """Scale 0.60 (filled) to ~1.25 (empty) by need fraction + draft progress."""
    pos_need = needs.get(position, 0)
    flex_need = flex_need_for_position(position, needs)
    effective_need = pos_need + flex_need

    if effective_need <= 0:
        return FILLED_BASE

    starter_target = int(config.roster.get(position, 0))
    starter_target += flex_target_for_position(position, config.roster)

    need_frac = min(effective_need / max(starter_target, 1), 1.0)

    if total_rounds > 0:
        progress = min(total_picks / max(total_rounds * config.teams, 1), 1.0)
    else:
        progress = 0.0

    multiplier = PARTIAL_FLOOR + (NEED_CEILING - PARTIAL_FLOOR) * need_frac
    multiplier += 0.15 * progress * need_frac
    return multiplier


def apply_need_multiplier(score: float, mult: float) -> float:
    """Scale a score by positional need without inverting negative scores.

    Multiplying a negative score by a >1 need multiplier would rank a needed
    position BELOW a filled one late in drafts; dividing instead keeps
    "higher multiplier => ranks higher" true on both sides of zero.
    """
    if score >= 0:
        return score * mult
    return score / mult


# Backward-compatible names retained for existing imports/tests.
_position_need_multiplier = position_need_multiplier
_apply_need_multiplier = apply_need_multiplier
