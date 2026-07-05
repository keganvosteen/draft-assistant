from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence

from .draft_value import roster_value
from .models import LeagueConfig, Player
from .projections import compute_points, replacement_levels


@dataclass(frozen=True)
class FreeAgentRecommendation:
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


def free_agent_recommendations(
    config: LeagueConfig,
    available: Sequence[Player],
    my_roster: Dict[str, List[Player]],
    top_n: int = 10,
) -> List[FreeAgentRecommendation]:
    """Rank waiver/free-agent adds for the user's current roster.

    The score is based on the same config-driven scoring and roster optimizer as
    the draft engine. If the roster is already full, the "after" roster is the
    best legal roster after adding the candidate, and the omitted current player
    becomes the suggested drop.
    """
    roster_players = _flatten_roster(my_roster)
    all_players = list(available) + roster_players
    points_map = compute_points(all_players, config.scoring)
    repl = replacement_levels(
        list(available), config.scoring, config.teams, config.roster, points_map=points_map
    )

    current = roster_value(roster_players, points_map, config.roster)
    current_value = current.total_value
    current_starter = current.starter_value
    capacity = _roster_capacity(config.roster)
    roster_full = capacity > 0 and len(roster_players) >= capacity

    rows: List[FreeAgentRecommendation] = []
    for player in available:
        after = roster_value(roster_players + [player], points_map, config.roster)
        kept_players = after.starters + after.bench
        kept_keys = {kept.key() for kept in kept_players}
        if roster_full and player.key() not in kept_keys:
            continue
        roster_gain = round(after.total_value - current_value, 2)
        starter_gain = round(after.starter_value - current_starter, 2)
        bench_gain = round(roster_gain - starter_gain, 2)
        points = round(points_map.get(player.key(), 0.0), 2)
        vor = round(points - repl.get(player.position, 0.0), 2)
        drop_player = (
            _suggested_drop(roster_players, kept_players, points_map)
            if roster_full else None
        )
        if roster_full and drop_player is None:
            continue
        drop_points = round(points_map.get(drop_player.key(), 0.0), 2) if drop_player else None
        score = _score(player, roster_gain, starter_gain, bench_gain, vor, drop_player)

        # Hide no-upgrade full-roster churn unless the board is tiny. Open
        # rosters still show useful fill-ins even when they are not above
        # replacement yet.
        if roster_full and roster_gain <= 0 and score <= 0:
            continue

        rows.append(FreeAgentRecommendation(
            player=player,
            points=points,
            vor=vor,
            score=score,
            roster_gain=roster_gain,
            starter_gain=starter_gain,
            bench_gain=bench_gain,
            drop_player=drop_player,
            drop_points=drop_points,
            reason=_reason(player, roster_gain, starter_gain, drop_player),
        ))

    rows.sort(
        key=lambda r: (
            r.score,
            r.roster_gain,
            r.starter_gain,
            r.vor,
            r.points,
            -(r.player.adp if r.player.adp is not None else 9999.0),
        ),
        reverse=True,
    )
    return rows[:top_n]


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


def _suggested_drop(
    roster_players: List[Player],
    keepers: Sequence[Player],
    points_map: Dict[str, float],
) -> Optional[Player]:
    kept = {player.key() for player in keepers}
    dropped = [player for player in roster_players if player.key() not in kept]
    if not dropped:
        return None
    # The optimizer may omit more than one player if the roster was already
    # oversized; surface the clearest single cut.
    return min(dropped, key=lambda player: points_map.get(player.key(), 0.0))


def _score(
    player: Player,
    roster_gain: float,
    starter_gain: float,
    bench_gain: float,
    vor: float,
    drop_player: Optional[Player],
) -> float:
    adp_tiebreak = 0.0
    if player.adp is not None:
        adp_tiebreak = max(0.0, min(3.0, (220.0 - float(player.adp)) / 80.0))
    drop_bonus = 0.75 if drop_player else 0.0
    return round(
        roster_gain
        + max(0.0, starter_gain) * 0.55
        + max(0.0, bench_gain) * 0.20
        + max(0.0, vor) * 0.12
        + adp_tiebreak
        + drop_bonus,
        2,
    )


def _reason(
    player: Player,
    roster_gain: float,
    starter_gain: float,
    drop_player: Optional[Player],
) -> str:
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
