"""Collect player metadata and historical stats from the Sleeper API.

Sleeper provides:
  - Player metadata: full_name, position, team, age, years_exp, etc.
  - Weekly stats via: https://api.sleeper.app/v1/stats/nfl/regular/<season>
  - Projections via: https://api.sleeper.app/v1/projections/nfl/regular/<season>

This collector builds an enriched player dataset with multi-year history.
"""
from __future__ import annotations
import json
import time
from typing import Any, Dict, List, Optional
from urllib.request import urlopen, Request
from urllib.error import URLError

from ..models import Player

SLEEPER_PLAYERS_URL = "https://api.sleeper.app/v1/players/nfl"
SLEEPER_STATS_URL = "https://api.sleeper.app/v1/stats/nfl/regular/{season}"
SLEEPER_PROJECTIONS_URL = "https://api.sleeper.app/v1/projections/nfl/regular/{season}"

VALID_POSITIONS = {"QB", "RB", "WR", "TE", "K", "DEF"}

# Map Sleeper stat keys to our internal stat keys
STAT_MAP = {
    "pass_yd": "pass_yd",
    "pass_td": "pass_td",
    "pass_int": "pass_int",
    "pass_2pt": "pass_2pt",
    "rush_yd": "rush_yd",
    "rush_td": "rush_td",
    "rush_2pt": "rush_2pt",
    "rec": "rec",
    "rec_yd": "rec_yd",
    "rec_td": "rec_td",
    "rec_2pt": "rec_2pt",
    "fum_lost": "fumbles",
    "fum": "fumbles",
}


def _fetch_json(url: str, retries: int = 3) -> Any:
    """Fetch JSON from URL with retry logic."""
    for attempt in range(retries):
        try:
            req = Request(url, headers={"User-Agent": "DraftAssistant/1.0"})
            with urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except (URLError, OSError, json.JSONDecodeError) as e:
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
            else:
                print(f"  Warning: failed to fetch {url}: {e}")
                return None


def _extract_stats(raw_stats: Dict[str, Any]) -> Dict[str, float]:
    """Extract fantasy-relevant stats from Sleeper raw stats dict."""
    out: Dict[str, float] = {}
    for sleeper_key, our_key in STAT_MAP.items():
        val = raw_stats.get(sleeper_key)
        if val is not None:
            out[our_key] = float(val)
    return out


def fetch_player_metadata() -> Dict[str, Dict[str, Any]]:
    """Fetch all NFL player metadata from Sleeper."""
    print("Fetching player metadata from Sleeper...")
    data = _fetch_json(SLEEPER_PLAYERS_URL)
    if not data or not isinstance(data, dict):
        return {}
    return data


def fetch_season_stats(season: int) -> Dict[str, Dict[str, float]]:
    """Fetch season-total stats for a given year. Returns {player_id: stats}."""
    url = SLEEPER_STATS_URL.format(season=season)
    print(f"  Fetching {season} season stats...")
    data = _fetch_json(url)
    if not data or not isinstance(data, dict):
        return {}
    result: Dict[str, Dict[str, float]] = {}
    for pid, stats in data.items():
        if isinstance(stats, dict):
            extracted = _extract_stats(stats)
            if extracted:
                result[pid] = extracted
    return result


def fetch_season_projections(season: int) -> Dict[str, Dict[str, float]]:
    """Fetch season projections for a given year."""
    url = SLEEPER_PROJECTIONS_URL.format(season=season)
    print(f"  Fetching {season} projections...")
    data = _fetch_json(url)
    if not data or not isinstance(data, dict):
        return {}
    result: Dict[str, Dict[str, float]] = {}
    for pid, stats in data.items():
        if isinstance(stats, dict):
            extracted = _extract_stats(stats)
            if extracted:
                result[pid] = extracted
    return result


def collect_players(
    current_season: int = 2025,
    history_seasons: int = 3,
) -> List[Player]:
    """Build enriched Player list with metadata and historical stats.

    Args:
        current_season: The upcoming/current fantasy season year.
        history_seasons: How many prior seasons of stats to collect.

    Returns:
        List of Player objects with historical_stats, age, experience, etc.
    """
    metadata = fetch_player_metadata()
    if not metadata:
        print("Could not fetch player metadata. Returning empty list.")
        return []

    # Fetch historical stats for the last N seasons
    historical: Dict[int, Dict[str, Dict[str, float]]] = {}
    for year in range(current_season - history_seasons, current_season):
        stats = fetch_season_stats(year)
        if stats:
            historical[year] = stats
        time.sleep(0.5)  # be polite to the API

    # Fetch current-season projections
    projections = fetch_season_projections(current_season)
    time.sleep(0.5)

    # Build player objects
    players: List[Player] = []
    for pid, meta in metadata.items():
        if not isinstance(meta, dict):
            continue
        pos = (meta.get("position") or "").upper()
        if pos not in VALID_POSITIONS:
            continue
        if pos == "DEF":
            pos = "DST"

        name = meta.get("full_name") or meta.get("last_name") or ""
        if not name:
            continue

        team = meta.get("team")
        # Skip players not on a team (free agents) unless they have projections
        if not team and pid not in (projections or {}):
            continue

        age = meta.get("age")
        years_exp = meta.get("years_exp")
        injury = meta.get("injury_status")

        # Build historical stats dict
        player_history: Dict[int, Dict[str, float]] = {}
        for year, year_stats in historical.items():
            if pid in year_stats:
                player_history[year] = year_stats[pid]

        # Current projections
        proj = (projections or {}).get(pid, {})

        # Detect team change
        previous_team = None
        if player_history:
            # Use Sleeper metadata for previous team if available
            prev = meta.get("previous_team")
            if prev and prev != team:
                previous_team = prev

        injury_list: List[str] = []
        if injury and injury not in ("", "Active"):
            injury_list.append(injury)

        players.append(Player(
            id=str(pid),
            name=name,
            position=pos,
            team=team,
            bye_week=meta.get("bye_week"),
            adp=None,
            projections=proj,
            age=int(age) if age is not None else None,
            experience=int(years_exp) if years_exp is not None else None,
            historical_stats=player_history,
            previous_team=previous_team,
            draft_capital=None,
            injury_history=injury_list,
        ))

    # Filter to players who have at least projections or recent history
    players = [
        p for p in players
        if p.projections or any(
            year >= current_season - 2 for year in p.historical_stats
        )
    ]

    print(f"Collected {len(players)} players with metadata and history.")
    return players
