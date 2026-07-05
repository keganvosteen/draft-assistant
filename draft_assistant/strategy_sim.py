"""Reusable draft strategy simulation and benchmark helpers."""
from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

from .draft_paste_parser import get_snake_team
from .draft_value import roster_value
from .models import DraftState, LeagueConfig, Player
from .projections import compute_points
from .rollout import rollout_values
from .sample_data import sample_players
from .scoring_utils import (
    flex_slots_filled,
    is_player_eligible_for_roster,
    roster_counts,
)
from .storage import load_players


LogFn = Optional[Callable[[str], None]]


@dataclass(frozen=True)
class DraftSimulationResult:
    user_score: float
    opponent_scores: List[float]
    user_rank: int
    scores: Dict[int, float]


def load_benchmark_players(path: str = "data/projections.json") -> List[Player]:
    players = load_players(path)
    return players if players else sample_players()


def roster_capacity(slots: Dict[str, int]) -> int:
    return sum(max(0, int(v)) for k, v in slots.items() if k != "IR")


def _fills_open_flex(
    player: Player,
    roster: Dict[str, List[Player]],
    slots: Dict[str, int],
) -> bool:
    counts = roster_counts(roster)
    with_player = dict(counts)
    with_player[player.position] = with_player.get(player.position, 0) + 1
    return sum(flex_slots_filled(slots, with_player).values()) > sum(
        flex_slots_filled(slots, counts).values()
    )


def select_adp_pick(
    available: List[Player],
    roster: Dict[str, List[Player]],
    slots: Dict[str, int],
    total_slots: int,
    adp_map: Optional[Dict[str, float]] = None,
) -> Player:
    """Select an ADP-style pick that respects starters, typed flex, and bench.

    ``adp_map`` lets a drafter use their own (e.g. noise-perturbed) board
    instead of consensus ADP.
    """
    def board_value(p: Player) -> float:
        if adp_map is not None and p.key() in adp_map:
            return adp_map[p.key()]
        return p.adp if p.adp is not None else 999.0

    sorted_available = sorted(available, key=lambda p: (board_value(p), p.name))
    remaining_slots = total_slots - sum(len(group) for group in roster.values())

    def kdst_allowed(pos: str) -> bool:
        return pos not in {"K", "DST"} or (slots.get(pos, 0) > 0 and remaining_slots <= 2)

    for player in sorted_available:
        if kdst_allowed(player.position) and len(roster.get(player.position, [])) < int(slots.get(player.position, 0)):
            return player

    for player in sorted_available:
        if kdst_allowed(player.position) and _fills_open_flex(player, roster, slots):
            return player

    for player in sorted_available:
        if kdst_allowed(player.position) and is_player_eligible_for_roster(player, roster, slots):
            return player

    for player in sorted_available:
        if is_player_eligible_for_roster(player, roster, slots):
            return player

    return sorted_available[0]


def run_single_draft_sim(
    config: LeagueConfig,
    user_draft_pos: int,
    all_players: List[Player],
    sims_per_pick: int = 24,
    adp_noise: float = 0.0,
    seed: int = 0,
    log: LogFn = None,
) -> DraftSimulationResult:
    num_teams = int(config.teams)
    slots = config.roster
    total_slots = roster_capacity(slots)
    total_picks = num_teams * total_slots
    team_rosters: Dict[int, Dict[str, List[Player]]] = {
        team: {} for team in range(1, num_teams + 1)
    }
    available = list(all_players)
    pick_history: List[Player] = []

    # Each opponent drafts off their own board: consensus ADP perturbed once per
    # draft by Gaussian noise, so a drafter's reaches/fades stay consistent.
    boards: Dict[int, Dict[str, float]] = {}
    if adp_noise > 0.0:
        for team in range(1, num_teams + 1):
            if team == user_draft_pos:
                continue
            rng = random.Random(1_000_003 * seed + 7919 * team + user_draft_pos)
            boards[team] = {
                p.key(): (float(p.adp) if p.adp is not None else 999.0)
                + rng.gauss(0.0, adp_noise)
                for p in all_players
            }

    sim_config = LeagueConfig(
        teams=config.teams,
        roster=config.roster,
        scoring=config.scoring,
        provider=config.provider,
        draft={
            "slot": user_draft_pos,
            "rollout_sims": sims_per_pick,
            "adp_noise": adp_noise,
            "rollout_candidates": 16,
        },
    )

    for pick_num in range(1, total_picks + 1):
        current_team = get_snake_team(pick_num, num_teams)
        current_roster = team_rosters[current_team]
        if current_team == user_draft_pos:
            my_pick_keys = [
                player.key()
                for index, player in enumerate(pick_history, 1)
                if get_snake_team(index, num_teams) == user_draft_pos
            ]
            draft_state = DraftState(
                my_team_name=f"Team {user_draft_pos}",
                league_teams=[f"Team {i + 1}" for i in range(num_teams)],
                picks=[player.key() for player in pick_history],
                my_picks=my_pick_keys,
            )
            results = rollout_values(
                config=sim_config,
                available=available,
                my_roster=current_roster,
                state=draft_state,
                top_n=5,
            )
            chosen = results[0].player if results else select_adp_pick(available, current_roster, slots, total_slots)
            if log:
                round_num = (pick_num - 1) // num_teams + 1
                log(f"  [USER Pick {pick_num} (R{round_num})] {chosen.name} ({chosen.position}) ADP:{chosen.adp}")
        else:
            chosen = select_adp_pick(
                available, current_roster, slots, total_slots,
                adp_map=boards.get(current_team),
            )

        team_rosters[current_team].setdefault(chosen.position, []).append(chosen)
        available.remove(chosen)
        pick_history.append(chosen)

    points_map = compute_points(all_players, config.scoring)
    scores: Dict[int, float] = {}
    for team in range(1, num_teams + 1):
        team_players = [p for group in team_rosters[team].values() for p in group]
        scores[team] = round(roster_value(team_players, points_map, config.roster).total_value, 2)

    user_score = scores[user_draft_pos]
    opponent_scores = [score for team, score in scores.items() if team != user_draft_pos]
    ranked_teams = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    user_rank = [team for team, _score in ranked_teams].index(user_draft_pos) + 1
    return DraftSimulationResult(user_score, opponent_scores, user_rank, scores)


def run_benchmark(
    config: LeagueConfig,
    players: List[Player],
    sims_per_pick: int = 24,
    slot_filter: Optional[int] = None,
    adp_noise: float = 0.0,
    trials: int = 1,
    log: LogFn = None,
) -> List[dict]:
    slots_to_run = [slot_filter] if slot_filter else list(range(1, int(config.teams) + 1))
    trials = max(1, int(trials))
    rows: List[dict] = []
    for slot in slots_to_run:
        for trial in range(1, trials + 1):
            if log:
                suffix = f" (trial {trial}/{trials})" if trials > 1 else ""
                log(f"Simulating draft from Slot #{slot}/{config.teams}{suffix}...")
            result = run_single_draft_sim(
                config,
                slot,
                players,
                sims_per_pick=sims_per_pick,
                adp_noise=adp_noise,
                seed=trial,
                log=log if slot_filter else None,
            )
            avg_opp = round(sum(result.opponent_scores) / len(result.opponent_scores), 2)
            max_opp = round(max(result.opponent_scores), 2)
            rows.append({
                "slot": slot,
                "trial": trial,
                "user_score": result.user_score,
                "avg_opp": avg_opp,
                "max_opp": max_opp,
                "diff_max": round(result.user_score - max_opp, 2),
                "rank": result.user_rank,
            })
    return rows
