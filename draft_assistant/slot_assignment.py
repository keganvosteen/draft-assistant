"""Exact typed-flex assignment shared by scoring, needs and draft feasibility.

Players have the same starter value in every eligible slot. Selecting them in
descending value and finding an augmenting path for each gives the maximum
value, maximum-cardinality matching. Reassigning earlier players is essential:
a WR may need to move from WR/TE to RB/WR so that a TE can start too.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Mapping, Optional, Sequence

from .models import FLEX_TYPES

STARTER_POSITIONS = ("QB", "RB", "WR", "TE", "K", "DST")


@lru_cache(maxsize=256)
def _flex_layout(counts: tuple[int, ...]) -> tuple[tuple[str, tuple[str, ...]], ...]:
    slots = [
        (key, eligibility)
        for (key, eligibility), count in zip(FLEX_TYPES.items(), counts)
        for _ in range(count)
    ]
    slots.sort(key=lambda slot: len(slot[1]))
    return tuple(slots)


def flex_layout(roster: Mapping[str, int]) -> tuple[tuple[str, tuple[str, ...]], ...]:
    return _flex_layout(tuple(max(0, int(roster.get(key, 0))) for key in FLEX_TYPES))


def assign_flex_slots(
    slots: Sequence[tuple[str, tuple[str, ...]]],
    positions: Sequence[str],
    values: Optional[Sequence[float]] = None,
) -> dict[int, int]:
    """Map slot indexes to candidate indexes without assigning anyone twice.

    Values are optional: without them this is a maximum-cardinality assignment.
    Ties retain input order. Negative values still fill required starter slots.
    """
    if not slots or not positions:
        return {}
    order = range(len(positions)) if values is None else sorted(
        range(len(positions)), key=lambda index: values[index], reverse=True,
    )
    assigned: dict[int, int] = {}
    # Most leagues have one or two identical FLEX slots. Avoid recursive
    # matching in this hot path, while retaining the exact same objective.
    if all(slot[1] == slots[0][1] for slot in slots):
        eligible = slots[0][1]
        for candidate in order:
            if positions[candidate] in eligible:
                assigned[len(assigned)] = candidate
                if len(assigned) == len(slots):
                    break
        return assigned

    def place(candidate: int, seen: set[int]) -> bool:
        for index, (_, eligible) in enumerate(slots):
            if index in seen or positions[candidate] not in eligible:
                continue
            seen.add(index)
            previous = assigned.get(index)
            if previous is None or place(previous, seen):
                assigned[index] = candidate
                return True
        return False

    for candidate in order:
        place(candidate, set())
        if len(assigned) == len(slots):
            break
    return assigned


@lru_cache(maxsize=8192)
def _filled_flex_counts(
    layout: tuple[tuple[str, tuple[str, ...]], ...],
    overflow: tuple[int, ...],
) -> tuple[int, ...]:
    # Counts beyond the number of slots cannot affect the matching.
    positions = [
        position
        for position, count in zip(STARTER_POSITIONS, overflow)
        for _ in range(min(count, len(layout)))
    ]
    assignment = assign_flex_slots(layout, positions)
    filled = dict.fromkeys(FLEX_TYPES, 0)
    for slot in assignment:
        filled[layout[slot][0]] += 1
    return tuple(filled.values())


def filled_flex_counts(roster: Mapping[str, int], counts: Mapping[str, int]) -> dict[str, int]:
    layout = flex_layout(roster)
    overflow = tuple(
        max(0, int(counts.get(pos, 0)) - max(0, int(roster.get(pos, 0))))
        for pos in STARTER_POSITIONS
    )
    return dict(zip(FLEX_TYPES, _filled_flex_counts(layout, overflow)))


def filled_starter_count(roster: Mapping[str, int], counts: Mapping[str, int]) -> int:
    return sum(
        min(max(0, int(roster.get(pos, 0))), max(0, int(counts.get(pos, 0))))
        for pos in STARTER_POSITIONS
    ) + sum(filled_flex_counts(roster, counts).values())
