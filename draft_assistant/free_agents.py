from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence

from .context import (
    actual_stats_for,
    confidence_for_player,
    is_candidate_eligible,
    primary_availability,
    signal_summary,
    urgency_for_player,
    weekly_availability_factor,
    weekly_projection_for,
)
from .draft_value import roster_value
from .models import LeagueConfig, Player, PlayerContext
from .projections import compute_points, replacement_levels
from .scoring import fantasy_points


@dataclass(frozen=True)
class FreeAgentRecommendation:
    # Backwards-compatible ROS fields used by the CLI/tests and older clients.
    player: Player
    points: float
    vor: float
    score: float
    roster_gain: float
    starter_gain: float
    bench_gain: float
    drop_player: Optional[Player]
    drop_points: Optional[float]
    reason: str

    # Explicit dual-horizon fields used by the web UI.
    weekly_points: float
    ros_points: float
    weekly_vor: float
    ros_vor: float
    weekly_score: float
    ros_score: float
    weekly_gain: float
    ros_gain: float
    weekly_starter_gain: float
    ros_starter_gain: float
    weekly_bench_gain: float
    ros_bench_gain: float
    weekly_drop_player: Optional[Player]
    ros_drop_player: Optional[Player]
    weekly_drop_points: Optional[float]
    ros_drop_points: Optional[float]
    weekly_reason: str
    ros_reason: str
    urgency: int
    availability: Optional[str]
    confidence: float
    signals: List[dict]
    weekly_projection_origin: str


@dataclass(frozen=True)
class _Horizon:
    points: float
    vor: float
    score: float
    roster_gain: float
    starter_gain: float
    bench_gain: float
    drop_player: Optional[Player]
    drop_points: Optional[float]
    reason: str
    kept: bool


def free_agent_recommendations(
    config: LeagueConfig,
    available: Sequence[Player],
    my_roster: Dict[str, List[Player]],
    top_n: Optional[int] = 10,
    *,
    context: Optional[PlayerContext] = None,
    week: Optional[int] = None,
    sort_by: str = "ros",
) -> List[FreeAgentRecommendation]:
    """Rank waiver adds independently for this week and rest of season.

    Season projections remain the persisted baseline. Current-season actuals
    are subtracted to derive ROS value; weekly raw projections are scored under
    the league's own rules and fall back to ROS points per remaining game.
    """
    if sort_by not in {"weekly", "ros"}:
        raise ValueError("sort_by must be 'weekly' or 'ros'")
    if week is not None and not 1 <= int(week) <= 18:
        raise ValueError("week must be between 1 and 18")
    selected_week = int(week or (context.selected_week if context else 1))
    remaining_games = max(1, 18 - selected_week + 1)

    roster_players = _flatten_roster(my_roster)
    eligible_available = [
        player for player in available if is_candidate_eligible(context, player)
    ]
    all_players = eligible_available + roster_players
    season_map = compute_points(all_players, config.scoring)

    ros_map: Dict[str, float] = {}
    weekly_map: Dict[str, float] = {}
    weekly_origins: Dict[str, str] = {}
    for player in all_players:
        season_points = float(season_map.get(player.key(), 0.0))
        actual_stats = actual_stats_for(context, player)
        if actual_stats is not None:
            ros_points = max(0.0, season_points - fantasy_points(actual_stats, config.scoring))
        elif selected_week > 1:
            ros_points = max(0.0, season_points * remaining_games / 18.0)
        else:
            ros_points = max(0.0, season_points)
        ros_map[player.key()] = round(ros_points, 2)

        weekly_stats = weekly_projection_for(context, player)
        if weekly_stats is not None:
            weekly_points = fantasy_points(weekly_stats, config.scoring)
            weekly_origins[player.key()] = "Sleeper weekly projection"
        else:
            weekly_points = ros_points / remaining_games
            weekly_origins[player.key()] = "ROS per-game fallback"
        weekly_points *= weekly_availability_factor(context, player)
        weekly_map[player.key()] = round(max(0.0, weekly_points), 2)

    ros_repl = replacement_levels(
        eligible_available, config.scoring, config.teams, config.roster,
        points_map=ros_map,
    )
    weekly_repl = replacement_levels(
        eligible_available, config.scoring, config.teams, config.roster,
        points_map=weekly_map,
    )
    capacity = _roster_capacity(config.roster)
    roster_full = capacity > 0 and len(roster_players) >= capacity
    ros_current = roster_value(roster_players, ros_map, config.roster)
    weekly_current = roster_value(roster_players, weekly_map, config.roster)

    rows: List[FreeAgentRecommendation] = []
    for player in eligible_available:
        ros = _horizon(
            player, roster_players, ros_map, ros_repl, config, roster_full, ros_current)
        weekly = _horizon(
            player, roster_players, weekly_map, weekly_repl, config, roster_full,
            weekly_current)
        if not ros.kept and not weekly.kept:
            continue
        if roster_full and max(ros.roster_gain, weekly.roster_gain) <= 0 and max(
            ros.score, weekly.score) <= 0:
            continue
        rows.append(FreeAgentRecommendation(
            player=player,
            points=ros.points, vor=ros.vor, score=ros.score,
            roster_gain=ros.roster_gain, starter_gain=ros.starter_gain,
            bench_gain=ros.bench_gain, drop_player=ros.drop_player,
            drop_points=ros.drop_points, reason=ros.reason,
            weekly_points=weekly.points, ros_points=ros.points,
            weekly_vor=weekly.vor, ros_vor=ros.vor,
            weekly_score=weekly.score, ros_score=ros.score,
            weekly_gain=weekly.roster_gain, ros_gain=ros.roster_gain,
            weekly_starter_gain=weekly.starter_gain,
            ros_starter_gain=ros.starter_gain,
            weekly_bench_gain=weekly.bench_gain, ros_bench_gain=ros.bench_gain,
            weekly_drop_player=weekly.drop_player, ros_drop_player=ros.drop_player,
            weekly_drop_points=weekly.drop_points, ros_drop_points=ros.drop_points,
            weekly_reason=weekly.reason, ros_reason=ros.reason,
            urgency=urgency_for_player(context, player),
            availability=primary_availability(context, player),
            confidence=confidence_for_player(context, player),
            signals=signal_summary(context, player),
            weekly_projection_origin=weekly_origins.get(player.key(), "ROS per-game fallback"),
        ))

    return rank_recommendations(rows, sort_by, top_n)


def rank_recommendations(rows: Sequence[FreeAgentRecommendation], horizon: str,
                         top_n: Optional[int] = None) -> List[FreeAgentRecommendation]:
    """Sort an already-computed result set without rerunning roster optimization."""
    if horizon not in {"weekly", "ros"}:
        raise ValueError("horizon must be 'weekly' or 'ros'")
    if horizon == "weekly":
        key = lambda row: (
            row.weekly_score, row.weekly_gain, row.weekly_starter_gain,
            row.weekly_vor, row.weekly_points, row.urgency,
            -(row.player.adp if row.player.adp is not None else 9999.0),
        )
    else:
        key = lambda row: (
            row.ros_score, row.ros_gain, row.ros_starter_gain,
            row.ros_vor, row.ros_points, row.urgency,
            -(row.player.adp if row.player.adp is not None else 9999.0),
        )
    ranked = sorted(rows, key=key, reverse=True)
    return ranked[:top_n] if top_n is not None else ranked


def _horizon(player: Player, roster_players: List[Player], points_map: Dict[str, float],
             replacement: Dict[str, float], config: LeagueConfig, roster_full: bool,
             current) -> _Horizon:
    after = roster_value(roster_players + [player], points_map, config.roster)
    kept_players = after.starters + after.bench
    kept = player.key() in {item.key() for item in kept_players}
    roster_gain = round(after.total_value - current.total_value, 2)
    starter_gain = round(after.starter_value - current.starter_value, 2)
    bench_gain = round(roster_gain - starter_gain, 2)
    points = round(points_map.get(player.key(), 0.0), 2)
    vor = round(points - replacement.get(player.position, 0.0), 2)
    drop = _suggested_drop(roster_players, kept_players, points_map) if roster_full and kept else None
    drop_points = round(points_map.get(drop.key(), 0.0), 2) if drop else None
    score = _score(player, roster_gain, starter_gain, bench_gain, vor, drop) if kept else -1_000_000.0
    reason = _reason(player, roster_gain, starter_gain, drop) if kept else "No legal roster upgrade"
    return _Horizon(
        points, vor, score, roster_gain, starter_gain, bench_gain,
        drop, drop_points, reason, kept,
    )


def _flatten_roster(my_roster: Dict[str, List[Player]]) -> List[Player]:
    players: List[Player] = []
    for group in my_roster.values():
        players.extend(group)
    return players


def _roster_capacity(roster: Dict[str, int]) -> int:
    total = 0
    for key, value in roster.items():
        if key == "IR":
            continue
        try:
            total += max(0, int(value))
        except (TypeError, ValueError):
            continue
    return total


def _suggested_drop(roster_players: List[Player], keepers: Sequence[Player],
                    points_map: Dict[str, float]) -> Optional[Player]:
    kept = {player.key() for player in keepers}
    dropped = [player for player in roster_players if player.key() not in kept]
    if not dropped:
        return None
    return min(dropped, key=lambda player: points_map.get(player.key(), 0.0))


def _score(player: Player, roster_gain: float, starter_gain: float,
           bench_gain: float, vor: float, drop_player: Optional[Player]) -> float:
    adp_tiebreak = 0.0
    if player.adp is not None:
        adp_tiebreak = max(0.0, min(3.0, (220.0 - float(player.adp)) / 80.0))
    drop_bonus = 0.75 if drop_player else 0.0
    return round(
        roster_gain + max(0.0, starter_gain) * 0.55
        + max(0.0, bench_gain) * 0.20 + max(0.0, vor) * 0.12
        + adp_tiebreak + drop_bonus,
        2,
    )


def _reason(player: Player, roster_gain: float, starter_gain: float,
            drop_player: Optional[Player]) -> str:
    gain = _fmt_delta(roster_gain)
    if drop_player:
        if starter_gain > 0:
            return f"{gain} roster pts; starts over current lineup, drop {drop_player.name}"
        return f"{gain} roster pts over {drop_player.name}"
    if starter_gain > 0:
        return f"{gain} roster pts; improves a starting slot"
    return f"{gain} roster pts; adds {player.position} depth"


def _fmt_delta(value: float) -> str:
    sign = "+" if value >= 0 else ""
    return f"{sign}{value:.1f}"
