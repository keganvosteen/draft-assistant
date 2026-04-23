from __future__ import annotations

from dataclasses import dataclass
import random
from typing import Dict, List, Optional, Sequence, Set, Tuple

from .models import DraftState, LeagueConfig, Player
from .projections import compute_points, replacement_levels


LINEUP_POSITIONS = ["QB", "RB", "WR", "TE", "K", "DST"]
FLEX_ELIGIBLE = {"RB", "WR", "TE"}


@dataclass(frozen=True)
class LineupResult:
    starter_value: float
    bench_value: float
    total_value: float
    starters: List[Player]
    bench: List[Player]


@dataclass(frozen=True)
class DraftWindow:
    draft_slot: int
    current_pick: int
    next_my_pick: int
    following_my_pick: int
    picks_until_next: int


@dataclass(frozen=True)
class DraftValue:
    player: Player
    points: float
    vor: float
    score: float
    lineup_gain: float
    scarcity: float
    next_pick_value: float
    bye_penalty: float


def roster_value(players: Sequence[Player], points_map: Dict[str, float], roster: Dict[str, int]) -> LineupResult:
    by_pos: Dict[str, List[Player]] = {}
    for player in players:
        by_pos.setdefault(player.position, []).append(player)
    for group in by_pos.values():
        group.sort(key=lambda p: points_map.get(p.key(), 0.0), reverse=True)

    starters: List[Player] = []
    used: Set[str] = set()
    for position in LINEUP_POSITIONS:
        count = max(0, int(roster.get(position, 0)))
        for player in by_pos.get(position, [])[:count]:
            starters.append(player)
            used.add(player.key())

    flex_count = max(0, int(roster.get("FLEX", 0)))
    flex_pool = [
        player
        for player in players
        if player.position in FLEX_ELIGIBLE and player.key() not in used
    ]
    flex_pool.sort(key=lambda p: points_map.get(p.key(), 0.0), reverse=True)
    for player in flex_pool[:flex_count]:
        starters.append(player)
        used.add(player.key())

    bench_count = max(0, int(roster.get("BN", roster.get("BENCH", 0))))
    bench_pool = [player for player in players if player.key() not in used]
    bench_pool.sort(key=lambda p: points_map.get(p.key(), 0.0), reverse=True)
    bench = bench_pool[:bench_count]

    starter_value = sum(points_map.get(player.key(), 0.0) for player in starters)
    bench_value = sum(points_map.get(player.key(), 0.0) * _bench_multiplier(player) for player in bench)
    return LineupResult(
        starter_value=round(starter_value, 2),
        bench_value=round(bench_value, 2),
        total_value=round(starter_value + bench_value, 2),
        starters=starters,
        bench=bench,
    )


def draft_window(config: LeagueConfig, state: Optional[DraftState]) -> DraftWindow:
    teams = max(1, int(config.teams))
    current_pick = len(state.picks) + 1 if state else 1
    draft_slot = _draft_slot(config, state)

    my_picks = _snake_pick_numbers(teams, draft_slot, rounds=40)
    next_my_pick = next((pick for pick in my_picks if pick >= current_pick), my_picks[-1])
    following_my_pick = next((pick for pick in my_picks if pick > next_my_pick), next_my_pick + teams)
    picks_until_next = max(0, following_my_pick - next_my_pick - 1)
    return DraftWindow(
        draft_slot=draft_slot,
        current_pick=current_pick,
        next_my_pick=next_my_pick,
        following_my_pick=following_my_pick,
        picks_until_next=picks_until_next,
    )


def draft_aware_values(
    config: LeagueConfig,
    available: List[Player],
    my_roster: Dict[str, List[Player]],
    state: Optional[DraftState] = None,
    top_n: int = 12,
) -> List[DraftValue]:
    roster_players = _flatten_roster(my_roster)
    all_players = available + roster_players
    points_map = compute_points(all_players, config.scoring)
    repl = replacement_levels(available, config.scoring, config.teams, config.roster)
    surplus_map = {
        player.key(): max(0.0, points_map.get(player.key(), 0.0) - repl.get(player.position, 0.0))
        for player in all_players
    }
    current_value = roster_value(roster_players, surplus_map, config.roster).total_value
    window = draft_window(config, state)
    settings = config.draft or {}
    sims = max(0, int(settings.get("monte_carlo_sims", 250)))
    candidate_pool_size = max(top_n * 4, int(settings.get("candidate_pool", 120)))

    prelim: List[DraftValue] = []
    for player in available:
        value_with_player = roster_value(roster_players + [player], surplus_map, config.roster).total_value
        lineup_gain = round(value_with_player - current_value, 2)
        pts = points_map.get(player.key(), 0.0)
        vor = round(pts - repl.get(player.position, 0.0), 2)
        bye_penalty = _bye_week_penalty(player, roster_players, surplus_map, config.roster)
        adp_adj = _adp_discount(player, window.next_my_pick)
        score = _base_score(lineup_gain, vor, adp_adj, bye_penalty)
        prelim.append(DraftValue(player, pts, vor, score, lineup_gain, 0.0, 0.0, bye_penalty))

    prelim.sort(key=lambda item: (item.score, item.vor, item.points), reverse=True)
    candidate_values = prelim[: min(len(prelim), candidate_pool_size)]
    candidate_keys = {item.player.key() for item in candidate_values}
    next_pick_pool = _next_pick_pool(available, surplus_map, candidate_keys, candidate_pool_size)

    if sims <= 0 or window.picks_until_next <= 0 or not candidate_values:
        return prelim[:top_n]

    boards = _simulate_boards(
        available,
        picks_until_next=window.picks_until_next,
        sims=sims,
        adp_noise=float(settings.get("adp_noise", 8.0)),
        seed=_simulation_seed(config, state),
    )
    scored: List[DraftValue] = []
    for item in candidate_values:
        player = item.player
        roster_after = roster_players + [player]
        next_options = _rank_next_options(roster_after, next_pick_pool, surplus_map, config.roster, exclude_key=player.key())
        same_position_options = [
            option
            for option in next_options
            if option[0].position == player.position
        ]
        expected_next = _expected_available_value(next_options, boards, player.key(), window.picks_until_next)
        expected_same = _expected_available_value(same_position_options, boards, player.key(), window.picks_until_next)
        scarcity = max(0.0, item.lineup_gain - expected_same)
        adp_adj = _adp_discount(player, window.next_my_pick)
        score = round(
            item.lineup_gain
            + 0.60 * scarcity
            + 0.25 * expected_next
            + 0.20 * item.vor
            + adp_adj
            - item.bye_penalty,
            2,
        )
        scored.append(DraftValue(
            player=player,
            points=item.points,
            vor=item.vor,
            score=score,
            lineup_gain=item.lineup_gain,
            scarcity=round(scarcity, 2),
            next_pick_value=round(expected_next, 2),
            bye_penalty=item.bye_penalty,
        ))

    scored_keys = {item.player.key() for item in scored}
    for item in prelim:
        if item.player.key() not in scored_keys:
            scored.append(item)
    scored.sort(key=lambda item: (item.score, item.lineup_gain, item.vor, item.points), reverse=True)
    return scored[:top_n]


def _flatten_roster(my_roster: Dict[str, List[Player]]) -> List[Player]:
    players: List[Player] = []
    for group in my_roster.values():
        players.extend(group)
    return players


def _bench_multiplier(player: Player) -> float:
    if player.position in {"RB", "WR"}:
        return 0.18
    if player.position == "TE":
        return 0.12
    if player.position == "QB":
        return 0.08
    return 0.0


def _draft_slot(config: LeagueConfig, state: Optional[DraftState]) -> int:
    teams = max(1, int(config.teams))
    if state and state.my_picks:
        for my_pick in state.my_picks:
            if my_pick not in state.picks:
                continue
            overall = state.picks.index(my_pick) + 1
            round_number = (overall - 1) // teams + 1
            pick_in_round = ((overall - 1) % teams) + 1
            if round_number % 2 == 1:
                return min(max(pick_in_round, 1), teams)
            return min(max(teams - pick_in_round + 1, 1), teams)
    settings = config.draft or {}
    return min(max(int(settings.get("slot", 1)), 1), teams)


def _snake_pick_numbers(teams: int, draft_slot: int, rounds: int) -> List[int]:
    picks: List[int] = []
    for round_number in range(1, rounds + 1):
        if round_number % 2 == 1:
            pick_in_round = draft_slot
        else:
            pick_in_round = teams - draft_slot + 1
        picks.append((round_number - 1) * teams + pick_in_round)
    return picks


def _base_score(lineup_gain: float, vor: float, adp_adj: float, bye_penalty: float) -> float:
    return round(lineup_gain + 0.25 * vor + adp_adj - bye_penalty, 2)


def _adp_discount(player: Player, target_pick: int) -> float:
    if player.adp is None:
        return 0.0
    # Falling past ADP is useful; reaching far ahead of ADP should be a small warning, not a veto.
    return max(-8.0, min(8.0, (target_pick - float(player.adp)) / 6.0))


def _bye_week_penalty(player: Player, roster_players: List[Player], points_map: Dict[str, float], roster: Dict[str, int]) -> float:
    if not player.bye_week or player.position in {"K", "DST"}:
        return 0.0
    lineup = roster_value(roster_players + [player], points_map, roster)
    starters = [p for p in lineup.starters if p.position not in {"K", "DST"} and p.bye_week == player.bye_week]
    same_position = [p for p in starters if p.position == player.position]
    penalty = max(0, len(starters) - 1) * 0.75 + max(0, len(same_position) - 1) * 0.75
    return round(min(3.0, penalty), 2)


def _next_pick_pool(
    available: List[Player],
    points_map: Dict[str, float],
    candidate_keys: Set[str],
    candidate_pool_size: int,
) -> List[Player]:
    pool = sorted(
        available,
        key=lambda p: (
            0 if p.key() in candidate_keys else 1,
            -(points_map.get(p.key(), 0.0)),
            p.adp if p.adp is not None else 9999.0,
        ),
    )
    return pool[: max(candidate_pool_size, 160)]


def _rank_next_options(
    roster_after: List[Player],
    options: List[Player],
    points_map: Dict[str, float],
    roster: Dict[str, int],
    exclude_key: str,
) -> List[Tuple[Player, float]]:
    base = roster_value(roster_after, points_map, roster).total_value
    ranked: List[Tuple[Player, float]] = []
    for option in options:
        if option.key() == exclude_key:
            continue
        gain = roster_value(roster_after + [option], points_map, roster).total_value - base
        ranked.append((option, round(gain, 2)))
    ranked.sort(key=lambda item: item[1], reverse=True)
    return ranked


def _expected_available_value(
    options: List[Tuple[Player, float]],
    boards: List[List[str]],
    excluded_key: str,
    picks_until_next: int,
) -> float:
    if not options:
        return 0.0
    total = 0.0
    for board in boards:
        taken_list = [key for key in board if key != excluded_key][:picks_until_next]
        taken = set(taken_list)
        value = 0.0
        for player, gain in options:
            key = player.key()
            if key != excluded_key and key not in taken:
                value = gain
                break
        total += value
    return round(total / max(1, len(boards)), 2)


def _simulate_boards(
    available: List[Player],
    picks_until_next: int,
    sims: int,
    adp_noise: float,
    seed: int,
) -> List[List[str]]:
    boards: List[List[str]] = []
    for sim in range(sims):
        rng = random.Random(seed + sim)
        ranked = sorted(
            available,
            key=lambda p: _sampled_adp_rank(p, rng, adp_noise),
        )
        boards.append([player.key() for player in ranked])
    return boards


def _sampled_adp_rank(player: Player, rng: random.Random, adp_noise: float) -> float:
    adp = float(player.adp) if player.adp is not None else 999.0
    return adp + rng.gauss(0.0, adp_noise)


def _simulation_seed(config: LeagueConfig, state: Optional[DraftState]) -> int:
    pick_count = len(state.picks) if state else 0
    slot = int((config.draft or {}).get("slot", 1))
    return 7919 + pick_count * 101 + max(1, int(config.teams)) * 17 + slot
