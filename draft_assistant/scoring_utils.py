"""Shared roster-need utilities.

The draft/waiver engines use exact lineup optimization for final scoring. These
helpers are the cheaper read of roster needs used by the CLI, the desktop UI,
and the strategy simulator, so they must preserve the same typed-flex
eligibility semantics.
"""
from __future__ import annotations
from typing import Dict, List, Mapping

from .models import FLEX_TYPES, LeagueConfig, Player

STARTER_POSITIONS = ("QB", "RB", "WR", "TE", "K", "DST")
ALL_FLEX_ELIGIBLE = set().union(*FLEX_TYPES.values())


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


# The gradient need-multiplier model that used to live here is gone: the
# rollout engine's impact score already prices positional need end to end
# (see rollout.py), so nothing layered a multiplier on top of it any more.
