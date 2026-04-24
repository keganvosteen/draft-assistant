"""Collect player data from the nflverse ecosystem via nfl_data_py.

This collector builds enriched Player objects using free, public data:
  - Historical stats (seasonal) from nflverse play-by-play aggregates
  - Roster data for names, positions, ages, draft capital, team history
  - Injury reports aggregated across seasons
  - Bye weeks derived from weekly game data

Requires: pip install nfl_data_py pandas
"""
from __future__ import annotations

import warnings
from typing import Any, Dict, List, Optional, Set, Tuple

from ..models import Player

FANTASY_POSITIONS = {"QB", "RB", "WR", "TE", "K"}

# Map nflverse stat columns to our internal stat keys
STAT_MAP = {
    "passing_yards": "pass_yd",
    "passing_tds": "pass_td",
    "interceptions": "pass_int",
    "passing_2pt_conversions": "pass_2pt",
    "rushing_yards": "rush_yd",
    "rushing_tds": "rush_td",
    "rushing_2pt_conversions": "rush_2pt",
    "receptions": "rec",
    "receiving_yards": "rec_yd",
    "receiving_tds": "rec_td",
    "receiving_2pt_conversions": "rec_2pt",
    "sack_fumbles_lost": "fumbles",
    "rushing_fumbles_lost": "fumbles",
    "receiving_fumbles_lost": "fumbles",
}

# Fumble columns that should be summed together
FUMBLE_COLS = ["sack_fumbles_lost", "rushing_fumbles_lost", "receiving_fumbles_lost"]


def _safe_int(val: Any) -> Optional[int]:
    if val is None:
        return None
    try:
        import math
        f = float(val)
        return int(f) if not math.isnan(f) else None
    except (ValueError, TypeError):
        return None


def _safe_float(val: Any) -> Optional[float]:
    if val is None:
        return None
    try:
        import math
        f = float(val)
        return f if not math.isnan(f) else None
    except (ValueError, TypeError):
        return None


def _draft_capital_label(draft_number: Optional[int]) -> Optional[str]:
    if draft_number is None:
        return None
    if draft_number <= 32:
        return "1st-round"
    if draft_number <= 64:
        return "2nd-round"
    if draft_number <= 100:
        return "3rd-round"
    if draft_number <= 135:
        return "4th-round"
    if draft_number <= 176:
        return "5th-round"
    if draft_number <= 220:
        return "6th-round"
    return "7th-round"


def _extract_stats(row: dict) -> Dict[str, float]:
    """Convert a nflverse stats row to our internal stat dict."""
    out: Dict[str, float] = {}
    total_fumbles = 0.0
    for nfl_col, our_key in STAT_MAP.items():
        val = _safe_float(row.get(nfl_col))
        if val is None:
            continue
        if nfl_col in FUMBLE_COLS:
            total_fumbles += val
        else:
            out[our_key] = val
    if total_fumbles > 0:
        out["fumbles"] = total_fumbles
    return out


def _compute_bye_weeks(weekly_df) -> Dict[str, int]:
    """Derive team bye weeks from weekly game data.

    Returns {team_abbr: bye_week_number}.
    """
    import pandas as pd

    reg = weekly_df[weekly_df["season_type"] == "REG"]
    all_weeks = set(range(1, 19))
    byes: Dict[str, int] = {}
    for team in reg["recent_team"].dropna().unique():
        played = set(reg[reg["recent_team"] == team]["week"].unique())
        missing = all_weeks - played
        if len(missing) == 1:
            byes[team] = missing.pop()
    return byes


def _aggregate_injuries(
    injury_df, seasons: List[int]
) -> Dict[str, List[str]]:
    """Aggregate injury history per player across seasons.

    Returns {gsis_id: [unique injury descriptions]}.
    """
    filtered = injury_df[
        (injury_df["report_primary_injury"].notna())
        & (injury_df["report_status"].isin(["Out", "Doubtful", "Questionable"]))
    ]
    result: Dict[str, Set[str]] = {}
    for _, row in filtered.iterrows():
        pid = row.get("gsis_id")
        inj = row.get("report_primary_injury")
        if pid and inj and inj != "None":
            result.setdefault(pid, set()).add(str(inj))
    return {pid: sorted(injuries) for pid, injuries in result.items()}


def collect_players(
    current_season: int = 2025,
    history_seasons: int = 3,
) -> List[Player]:
    """Build enriched Player list from nflverse data.

    Args:
        current_season: The upcoming/current season year. Roster and injury
            data are pulled from the most recent completed season.
        history_seasons: How many prior seasons of stats to collect.

    Returns:
        List of Player objects with historical_stats, age, injuries, etc.
        Projections are left empty (fill from Sleeper or FantasyPros).
    """
    try:
        import nfl_data_py as nfl
        import pandas as pd
    except ImportError:
        print("Error: nfl_data_py and pandas are required.")
        print("Install with: pip install nfl_data_py pandas")
        return []

    warnings.filterwarnings("ignore", category=FutureWarning)

    last_season = current_season - 1
    stat_years = list(range(current_season - history_seasons, current_season))

    # 1. Load roster data for the most recent season
    print(f"Loading {last_season} roster data...")
    try:
        roster_df = nfl.import_seasonal_rosters([last_season])
    except Exception as e:
        print(f"  Warning: could not load rosters: {e}")
        roster_df = pd.DataFrame()

    # 2. Load prior-year roster for team-change detection
    prior_roster_df = pd.DataFrame()
    if last_season - 1 >= stat_years[0]:
        print(f"Loading {last_season - 1} roster for team-change detection...")
        try:
            prior_roster_df = nfl.import_seasonal_rosters([last_season - 1])
        except Exception:
            pass

    # 3. Load historical seasonal stats
    print(f"Loading seasonal stats for {stat_years}...")
    try:
        stats_df = nfl.import_seasonal_data(stat_years)
    except Exception as e:
        print(f"  Warning: could not load seasonal stats: {e}")
        stats_df = pd.DataFrame()

    # 4. Load weekly data for bye week derivation
    print(f"Loading {last_season} weekly data for bye weeks...")
    bye_weeks: Dict[str, int] = {}
    try:
        weekly_df = nfl.import_weekly_data([last_season])
        bye_weeks = _compute_bye_weeks(weekly_df)
        print(f"  Derived bye weeks for {len(bye_weeks)} teams.")
    except Exception as e:
        print(f"  Warning: could not derive bye weeks: {e}")

    # 5. Load injury data
    inj_years = [y for y in stat_years if y >= 2009]
    injuries_by_player: Dict[str, List[str]] = {}
    if inj_years:
        print(f"Loading injury reports for {inj_years}...")
        try:
            injury_df = nfl.import_injuries(inj_years)
            injuries_by_player = _aggregate_injuries(injury_df, inj_years)
            print(f"  Found injury history for {len(injuries_by_player)} players.")
        except Exception as e:
            print(f"  Warning: could not load injuries: {e}")

    # Build player index from roster data
    # Key: player_id (gsis_id)
    roster_map: Dict[str, dict] = {}
    if not roster_df.empty:
        for _, row in roster_df.iterrows():
            pid = row.get("player_id")
            pos = row.get("position", "")
            if not pid or pos not in FANTASY_POSITIONS:
                continue
            roster_map[pid] = {
                "name": row.get("player_name") or row.get("player_display_name") or "",
                "position": pos,
                "team": row.get("team"),
                "age": _safe_int(row.get("age")),
                "years_exp": _safe_int(row.get("years_exp")),
                "draft_number": _safe_int(row.get("draft_number")),
            }

    # Build prior-season team map for team-change detection
    prior_team_map: Dict[str, str] = {}
    if not prior_roster_df.empty:
        for _, row in prior_roster_df.iterrows():
            pid = row.get("player_id")
            team = row.get("team")
            if pid and team:
                prior_team_map[pid] = team

    # Build historical stats per player
    player_history: Dict[str, Dict[int, Dict[str, float]]] = {}
    if not stats_df.empty:
        for _, row in stats_df.iterrows():
            pid = row.get("player_id")
            season = _safe_int(row.get("season"))
            if not pid or season is None:
                continue
            extracted = _extract_stats(row.to_dict())
            if extracted:
                player_history.setdefault(pid, {})[season] = extracted

    # Also pull names/positions from weekly data if roster is sparse
    weekly_player_info: Dict[str, dict] = {}
    if "weekly_df" in dir() and not weekly_df.empty:
        for _, row in weekly_df.drop_duplicates(subset=["player_id"]).iterrows():
            pid = row.get("player_id")
            pos = row.get("position", "")
            if pid and pos in FANTASY_POSITIONS and pid not in roster_map:
                weekly_player_info[pid] = {
                    "name": row.get("player_display_name") or row.get("player_name") or "",
                    "position": pos,
                    "team": row.get("recent_team"),
                }

    # Merge all player IDs
    all_pids = set(roster_map.keys()) | set(player_history.keys()) | set(weekly_player_info.keys())

    players: List[Player] = []
    for pid in all_pids:
        info = roster_map.get(pid) or weekly_player_info.get(pid)
        if not info:
            continue

        name = info.get("name", "")
        position = info.get("position", "")
        if not name or not position:
            continue

        team = info.get("team")
        age = info.get("age")
        years_exp = info.get("years_exp")
        draft_num = info.get("draft_number")

        # Team change detection
        prev_team = prior_team_map.get(pid)
        previous_team = prev_team if prev_team and prev_team != team else None

        # Historical stats
        hist = player_history.get(pid, {})

        # Skip players with no recent activity
        if not hist and pid not in roster_map:
            continue

        # Injuries
        injury_list = injuries_by_player.get(pid, [])

        # Bye week from team
        bye = bye_weeks.get(team) if team else None

        players.append(Player(
            id=pid,
            name=name,
            position=position,
            team=team,
            bye_week=bye,
            adp=None,
            projections={},
            age=age,
            experience=years_exp,
            historical_stats=hist,
            previous_team=previous_team,
            draft_capital=_draft_capital_label(draft_num),
            injury_history=injury_list,
        ))

    # Filter to players who were on a roster or had stats in the last 2 seasons
    recent_cutoff = current_season - 2
    players = [
        p for p in players
        if p.team or any(y >= recent_cutoff for y in p.historical_stats)
    ]

    players.sort(key=lambda p: (-len(p.historical_stats), p.name))
    print(f"Collected {len(players)} players from nflverse data.")
    return players
