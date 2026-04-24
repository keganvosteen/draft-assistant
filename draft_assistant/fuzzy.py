"""Lightweight fuzzy string matching (no external dependencies).

Uses Levenshtein distance for approximate player name matching.
"""
from __future__ import annotations
from typing import List, Optional, Tuple


def _levenshtein(s1: str, s2: str) -> int:
    """Compute Levenshtein edit distance between two strings."""
    if len(s1) < len(s2):
        return _levenshtein(s2, s1)
    if len(s2) == 0:
        return len(s1)

    prev_row = list(range(len(s2) + 1))
    for i, c1 in enumerate(s1):
        curr_row = [i + 1]
        for j, c2 in enumerate(s2):
            ins = prev_row[j + 1] + 1
            dele = curr_row[j] + 1
            sub = prev_row[j] + (0 if c1 == c2 else 1)
            curr_row.append(min(ins, dele, sub))
        prev_row = curr_row
    return prev_row[-1]


def fuzzy_match(
    query: str,
    candidates: List[str],
    max_distance: int = 3,
) -> List[Tuple[str, int]]:
    """Find candidates within max_distance edits of query.

    Returns list of (candidate, distance) sorted by distance ascending.
    """
    query_lower = query.lower()
    results: List[Tuple[str, int]] = []
    for c in candidates:
        dist = _levenshtein(query_lower, c.lower())
        if dist <= max_distance:
            results.append((c, dist))
    results.sort(key=lambda t: t[1])
    return results


def best_match(
    query: str,
    candidates: List[str],
    max_distance: int = 3,
) -> Optional[str]:
    """Return the best fuzzy match, or None if nothing is close enough."""
    matches = fuzzy_match(query, candidates, max_distance)
    return matches[0][0] if matches else None
