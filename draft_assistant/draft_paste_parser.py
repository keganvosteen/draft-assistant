"""Parser for raw copy-pasted draft room logs (ESPN, Yahoo, Sleeper, plain text lists).

Parses lines into candidate player names, matches them against known/available players,
and assigns pick numbers and snake-draft team positions.
"""
from __future__ import annotations
import math
import re
from typing import Any, Dict, List, Optional, Tuple

from .fuzzy import score_player_query, _normalize_str


def get_snake_team(pick_num: int, num_teams: int) -> int:
    """Calculate the 1-indexed team number for a given 1-indexed pick in a snake draft."""
    if num_teams <= 0 or pick_num <= 0:
        return 1
    round_num = math.ceil(pick_num / num_teams)
    pick_in_round = ((pick_num - 1) % num_teams) + 1
    if round_num % 2 == 1:
        return pick_in_round
    else:
        return num_teams - pick_in_round + 1


def clean_line_text(line: str) -> Tuple[Optional[int], str]:
    """Clean draft line and attempt to extract explicit pick number and candidate player name.

    Handles formats like:
      - "1. (1) Team 1 - Bijan Robinson RB"
      - "1.01 Bijan Robinson (ATL - RB)"
      - "Pick 5: CeeDee Lamb"
      - "Bijan Robinson"
    """
    raw = line.strip()
    if not raw:
        return None, ""

    explicit_pick = None

    m_pick_num = re.search(r"\b(?:pick|#)\s*(\d+)\b", line, re.IGNORECASE)
    if m_pick_num:
        explicit_pick = int(m_pick_num.group(1))

    # Pattern: 1.01 or 2.12
    m_round_pick = re.match(r"^(\d+)\.(\d{1,2})\b", raw)
    if m_round_pick:
        raw = raw[m_round_pick.end():].strip()

    m_indexed = re.match(r"^(\d+)[\.\)\:]\s*", raw)
    if m_indexed:
        if not explicit_pick:
            explicit_pick = int(m_indexed.group(1))
        raw = raw[m_indexed.end():].strip()

    # Strip pick index in parens e.g. (1)
    raw = re.sub(r"^\(\d+\)\s*", "", raw).strip()

    # Strip team prefixes like "Team 1 - ", "Team 1:", "Pick 1 -"
    raw = re.sub(r"^(?:team\s*\d+|pick\s*\d+)\s*[\-\:]\s*", "", raw, flags=re.IGNORECASE).strip()

    # Strip parenthetical annotations e.g. (ATL - RB), (Round 1)
    cleaned_name = re.sub(r"\([^\)]*\)", "", raw).strip()

    # Strip trailing position/team noise e.g. " RB ATL", " WR", " QB"
    cleaned_name = re.sub(r"\b(QB|RB|WR|TE|K|DST|DEF)\b.*$", "", cleaned_name, flags=re.IGNORECASE).strip()

    # Remove extra spaces/dashes
    cleaned_name = re.sub(r"^[\-\:\.\s]+|[\-\:\.\s]+$", "", cleaned_name).strip()

    return explicit_pick, cleaned_name if cleaned_name else raw


def match_player_against_candidates(
    query_name: str,
    players: List[Dict[str, Any]]
) -> Tuple[Optional[Dict[str, Any]], str, float]:
    """Find the best matching player from candidates.

    Returns (best_player, confidence_label, match_score).
    Confidence labels: 'HIGH', 'MEDIUM', 'LOW', 'UNMATCHED'.
    """
    if not query_name or not players:
        return None, "UNMATCHED", 0.0

    scored = []
    for p in players:
        score = score_player_query(query_name, p)
        if score > 0:
            scored.append((score, p))

    if not scored:
        return None, "UNMATCHED", 0.0

    scored.sort(key=lambda item: item[0], reverse=True)
    best_score, best_p = scored[0]

    if best_score >= 85.0:
        confidence = "HIGH"
    elif best_score >= 65.0:
        confidence = "MEDIUM"
    elif best_score >= 40.0:
        confidence = "LOW"
    else:
        confidence = "UNMATCHED"
        best_p = None

    return best_p, confidence, best_score


def parse_draft_text(
    raw_text: str,
    all_players: List[Dict[str, Any]],
    num_teams: int = 12,
    start_pick: int = 1,
) -> List[Dict[str, Any]]:
    """Parse raw draft room text and map entries into snake-draft picks.

    Returns a list of pick result dictionaries.
    """
    lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
    results = []

    current_pick_counter = start_pick

    for line in lines:
        explicit_pick, candidate_name = clean_line_text(line)

        pick_num = explicit_pick if (explicit_pick and explicit_pick >= current_pick_counter) else current_pick_counter
        team_num = get_snake_team(pick_num, num_teams)

        matched_player, confidence, score = match_player_against_candidates(candidate_name, all_players)

        results.append({
            "pickNum": pick_num,
            "teamNum": team_num,
            "rawText": line,
            "candidateName": candidate_name,
            "matchedPlayerId": matched_player.get("id") if matched_player else None,
            "matchedPlayerName": matched_player.get("name") if matched_player else candidate_name,
            "matchedPlayerPos": matched_player.get("pos") or matched_player.get("position", "") if matched_player else "",
            "matchedPlayerTeam": matched_player.get("team", "") if matched_player else "",
            "confidence": confidence,
            "score": score,
            "isConfirmed": confidence in ("HIGH", "MEDIUM"),
        })

        current_pick_counter = pick_num + 1

    return results
