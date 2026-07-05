"""Lightweight fuzzy string matching (no external dependencies).

Uses Levenshtein distance, prefix matching, and multi-token query parsing for approximate player name matching.
"""
from __future__ import annotations
import re
from typing import Any, Dict, List, Optional, Tuple

POSITIONS = {"QB", "RB", "WR", "TE", "K", "DST", "DEF"}


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


def _normalize_str(s: str) -> str:
    """Strip special characters for clean matching."""
    return re.sub(r"[^\w\s]", "", s.lower()).strip()


def score_player_query(query: str, player: Dict[str, Any]) -> float:
    """Score how closely a player matches a multi-token query.

    Handles queries like "bij", "allen qb", "ja'm", "kc dst".
    Returns a score float where higher is better (0.0 means no match).
    """
    raw_q = query.strip().lower()
    if not raw_q:
        return 0.0

    name = player.get("name", "")
    pos = (player.get("pos") or player.get("position") or "").upper()
    if pos == "DEF":
        pos = "DST"
    team = (player.get("team") or "").upper()

    tokens = raw_q.split()
    query_pos = None
    query_name_tokens = []

    for t in tokens:
        t_upper = t.upper()
        if t_upper in POSITIONS:
            query_pos = "DST" if t_upper == "DEF" else t_upper
        else:
            query_name_tokens.append(t)

    # Position filter check
    if query_pos and pos != query_pos:
        return 0.0

    if not query_name_tokens:
        # User typed only position (e.g. "qb")
        return 1.0

    clean_name = _normalize_str(name)
    name_words = [_normalize_str(w) for w in name.split()]

    score = 0.0
    matched_tokens = 0

    for qt in query_name_tokens:
        clean_qt = _normalize_str(qt)
        if not clean_qt:
            continue

        token_score = 0.0
        # Check team match
        if team and clean_qt == team.lower():
            token_score = max(token_score, 40.0)

        # Exact full name match or prefix match
        if clean_name == clean_qt:
            token_score = max(token_score, 100.0)
        elif clean_name.startswith(clean_qt):
            token_score = max(token_score, 85.0)

        # Token prefix match against name words
        for word in name_words:
            if word == clean_qt:
                token_score = max(token_score, 90.0)
            elif word.startswith(clean_qt):
                token_score = max(token_score, 75.0)
            else:
                dist = _levenshtein(clean_qt, word)
                if dist <= 1:
                    token_score = max(token_score, 60.0 - dist * 10)
                elif dist <= 2 and len(clean_qt) >= 4:
                    token_score = max(token_score, 40.0 - dist * 10)

        if token_score > 0:
            matched_tokens += 1
            score += token_score

    if matched_tokens < len([qt for qt in query_name_tokens if _normalize_str(qt)]):
        # Did not match all required name tokens
        return 0.0

    return score


def search_players_fuzzy(
    query: str,
    players: List[Dict[str, Any]],
    limit: int = 10,
) -> List[Dict[str, Any]]:
    """Search available players using multi-token fuzzy matching.

    Returns candidates sorted by match score (descending), then ADP (ascending), then name.
    """
    scored = []
    for p in players:
        score = score_player_query(query, p)
        if score > 0:
            adp = p.get("adp")
            adp_val = float(adp) if adp is not None else 999.0
            scored.append((score, adp_val, p.get("name", ""), p))

    # Sort: score descending, ADP ascending, name ascending
    scored.sort(key=lambda item: (-item[0], item[1], item[2]))
    return [item[3] for item in scored[:limit]]
