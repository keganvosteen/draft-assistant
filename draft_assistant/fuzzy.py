"""Lightweight fuzzy string matching (no external dependencies).

Uses Levenshtein distance, prefix matching, and multi-token query parsing for approximate player name matching.
"""
from __future__ import annotations
import re
from functools import lru_cache
from typing import Any, Dict, List, Optional, Tuple

POSITIONS = {"QB", "RB", "WR", "TE", "K", "DST", "DEF"}
_SUFFIX_RE = re.compile(r"\s+(jr\.?|sr\.?|ii|iii|iv|v)$", re.IGNORECASE)


def _levenshtein(s1: str, s2: str, max_distance: Optional[int] = None) -> int:
    """Levenshtein edit distance between two strings.

    With ``max_distance`` set, gives up as soon as the answer is known to exceed
    it and returns ``max_distance + 1``. Every caller here only cares whether the
    distance is within a small budget, and abandoning hopeless pairs early is
    what makes matching a query against a full player pool affordable.
    """
    if len(s1) < len(s2):
        s1, s2 = s2, s1
    len1, len2 = len(s1), len(s2)
    if len2 == 0:
        return len1
    # Distance is at least the length difference, so this is already decided.
    if max_distance is not None and len1 - len2 > max_distance:
        return max_distance + 1

    prev_row = list(range(len2 + 1))
    for i, c1 in enumerate(s1):
        curr_row = [i + 1]
        row_min = i + 1
        for j, c2 in enumerate(s2):
            # Inlined rather than min(ins, dele, sub): this is the innermost
            # loop of the whole matcher and the call overhead dominated it.
            best = prev_row[j + 1] + 1
            left = curr_row[j] + 1
            if left < best:
                best = left
            sub = prev_row[j] if c1 == c2 else prev_row[j] + 1
            if sub < best:
                best = sub
            curr_row.append(best)
            if best < row_min:
                row_min = best
        # Any alignment path must cross this row, so the final distance is at
        # least the cheapest cell in it. Exact, not a heuristic.
        if max_distance is not None and row_min > max_distance:
            return max_distance + 1
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
    query_len = len(query_lower)
    results: List[Tuple[str, int]] = []
    for c in candidates:
        candidate = c.lower()
        # Edit distance is at least the length difference, so anything further
        # apart than that can't pass — skipping it is exact, and it removes most
        # of the O(n*m) work when scanning a full player pool.
        if abs(len(candidate) - query_len) > max_distance:
            continue
        dist = _levenshtein(query_lower, candidate, max_distance)
        if dist <= max_distance:
            results.append((c, dist))
    # Tie-break on the candidate itself: sorting by distance alone left equally
    # close names in input order, so the "best" match depended on how the player
    # file happened to be ordered.
    results.sort(key=lambda t: (t[1], t[0]))
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


@lru_cache(maxsize=8192)
def _name_forms(name: str) -> Tuple[str, Tuple[str, ...]]:
    """``(normalized full name, normalized words)`` for a candidate name.

    Cached because :func:`score_player_query` runs once per candidate per query:
    parsing a pasted draft log re-derived these regex results for the same ~1000
    player names on every single line, which dominated the parse.
    """
    return _normalize_str(name), tuple(_normalize_str(w) for w in name.split())


def normalize_player_name(name: str, compact: bool = False) -> str:
    """Normalize player names consistently across importers and sync matching."""
    normalized = _SUFFIX_RE.sub("", str(name or "").strip())
    normalized = " ".join(normalized.lower().split())
    if compact:
        return re.sub(r"[^a-z0-9]+", "", normalized)
    return normalized


def normalize_player_key(name: str, position: str, compact: bool = False) -> str:
    return f"{normalize_player_name(name, compact=compact)}|{position}"


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

    clean_name, name_words = _name_forms(name)

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
        qt_len = len(clean_qt)
        for word in name_words:
            if word == clean_qt:
                token_score = max(token_score, 90.0)
            elif word.startswith(clean_qt):
                token_score = max(token_score, 75.0)
            elif abs(len(word) - qt_len) <= 2:
                # Only distances <= 2 score at all, and edit distance is at
                # least the length difference — so a wider gap can be skipped
                # without computing it. This is the hot loop when parsing a
                # pasted draft log against the full player pool.
                dist = _levenshtein(clean_qt, word, 2)
                if dist <= 1:
                    token_score = max(token_score, 60.0 - dist * 10)
                elif dist <= 2 and qt_len >= 4:
                    token_score = max(token_score, 40.0 - dist * 10)

        if token_score == 0:
            # Every non-empty query token has to match something for the player
            # to score at all (the check below), so once one fails there is no
            # point pricing the rest. This is what keeps scanning a full player
            # pool cheap: most candidates fail on the first token.
            return 0.0
        matched_tokens += 1
        score += token_score

    if matched_tokens == 0:
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
