from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence

from .draft_value import roster_value
from .models import DraftState, FLEX_TYPES, LeagueConfig, Player
from .profiles import DEFAULT_PROFILE, ensure_profile, load_profile_config
from .projections import compute_points
from .rollout import rollout_values
from .storage import load_players
from .web.server import scoring_for_league


@dataclass(frozen=True)
class TeamScore:
    team_num: int
    starter_value: float
    bench_value: float
    total_value: float
    picks: List[str]


@dataclass(frozen=True)
class DraftSimulation:
    draft_slot: int
    strategy: str
    teams: List[TeamScore]

    @property
    def user_team(self) -> TeamScore:
        return self.teams[self.draft_slot - 1]


@dataclass(frozen=True)
class SlotComparison:
    draft_slot: int
    score_draft: DraftSimulation
    adp_draft: DraftSimulation
    starter_delta: float
    total_delta: float
    score_rank: int
    adp_rank: int


@dataclass(frozen=True)
class LeagueSweep:
    name: str
    config: LeagueConfig
    slots: List[SlotComparison]

    @property
    def average_starter_delta(self) -> float:
        return _avg(slot.starter_delta for slot in self.slots)

    @property
    def average_total_delta(self) -> float:
        return _avg(slot.total_delta for slot in self.slots)


def compare_all_slots(
    config: LeagueConfig,
    players: Sequence[Player],
    *,
    rollout_sims: Optional[int] = None,
) -> List[SlotComparison]:
    return [
        compare_slot(config, players, slot, rollout_sims=rollout_sims)
        for slot in range(1, max(1, int(config.teams)) + 1)
    ]


def compare_slot(
    config: LeagueConfig,
    players: Sequence[Player],
    draft_slot: int,
    *,
    rollout_sims: Optional[int] = None,
) -> SlotComparison:
    score_draft = simulate_draft(
        config, players, draft_slot, user_strategy="score", rollout_sims=rollout_sims
    )
    adp_draft = simulate_draft(
        config, players, draft_slot, user_strategy="adp", rollout_sims=rollout_sims
    )
    return SlotComparison(
        draft_slot=draft_slot,
        score_draft=score_draft,
        adp_draft=adp_draft,
        starter_delta=round(score_draft.user_team.starter_value - adp_draft.user_team.starter_value, 2),
        total_delta=round(score_draft.user_team.total_value - adp_draft.user_team.total_value, 2),
        score_rank=_rank(score_draft.teams, draft_slot, key="starter_value"),
        adp_rank=_rank(adp_draft.teams, draft_slot, key="starter_value"),
    )


def simulate_draft(
    config: LeagueConfig,
    players: Sequence[Player],
    draft_slot: int,
    *,
    user_strategy: str = "score",
    rollout_sims: Optional[int] = None,
) -> DraftSimulation:
    cfg = _simulation_config(config, draft_slot, rollout_sims)
    teams = max(1, int(cfg.teams))
    rounds = _draft_rounds(cfg.roster)
    by_key = _unique_players(players)
    all_players = list(by_key.values())
    points_map = compute_points(all_players, cfg.scoring)
    available = set(by_key)
    rosters: Dict[int, List[Player]] = {team: [] for team in range(1, teams + 1)}
    picks: List[str] = []
    my_picks: List[str] = []

    for pick_no in range(1, teams * rounds + 1):
        team_num = snake_team(pick_no, teams)
        if team_num == draft_slot and user_strategy == "score":
            key = _score_pick(cfg, by_key, available, rosters[team_num], picks, my_picks)
        else:
            key = _adp_pick_for_roster(by_key, available, points_map, rosters[team_num], cfg.roster)
        if key is None:
            break
        player = by_key[key]
        available.remove(key)
        rosters[team_num].append(player)
        picks.append(key)
        if team_num == draft_slot:
            my_picks.append(key)

    scores = []
    for team_num in range(1, teams + 1):
        value = roster_value(rosters[team_num], points_map, cfg.roster)
        scores.append(TeamScore(
            team_num=team_num,
            starter_value=value.starter_value,
            bench_value=value.bench_value,
            total_value=value.total_value,
            picks=[player.key() for player in rosters[team_num]],
        ))
    return DraftSimulation(draft_slot=draft_slot, strategy=user_strategy, teams=scores)


def snake_team(pick_no: int, teams: int) -> int:
    round_number = (pick_no - 1) // teams + 1
    pick_in_round = (pick_no - 1) % teams + 1
    if round_number % 2 == 1:
        return pick_in_round
    return teams - pick_in_round + 1


def web_league_config(league: dict, base_config: LeagueConfig) -> LeagueConfig:
    roster = dict(base_config.roster)
    roster.update({
        key: int(value)
        for key, value in (league.get("rosterSlots") or {}).items()
        if value is not None
    })
    draft = dict(base_config.draft or {})
    if league.get("draftPosition"):
        draft["slot"] = int(league["draftPosition"])
    return LeagueConfig(
        teams=int(league.get("numTeams") or base_config.teams),
        roster=roster,
        scoring=scoring_for_league(league, base_config.scoring),
        provider=dict(base_config.provider or {}),
        draft=draft,
    )


def load_league_sweeps(
    *,
    profile: str = DEFAULT_PROFILE,
    leagues_json: Optional[str] = None,
    rollout_sims: Optional[int] = None,
) -> List[LeagueSweep]:
    paths = ensure_profile(profile)
    base_config = load_profile_config(paths)
    players = load_players(paths.projections_path)
    if leagues_json:
        leagues = _read_leagues_json(leagues_json)
        return [
            LeagueSweep(
                name=str(league.get("name") or f"League {index + 1}"),
                config=web_league_config(league, base_config),
                slots=compare_all_slots(
                    web_league_config(league, base_config), players, rollout_sims=rollout_sims
                ),
            )
            for index, league in enumerate(leagues)
        ]
    return [
        LeagueSweep(
            name=profile,
            config=base_config,
            slots=compare_all_slots(base_config, players, rollout_sims=rollout_sims),
        )
    ]


def _simulation_config(
    config: LeagueConfig,
    draft_slot: int,
    rollout_sims: Optional[int],
) -> LeagueConfig:
    draft = dict(config.draft or {})
    draft["slot"] = draft_slot
    if rollout_sims is not None:
        draft["rollout_sims"] = max(0, int(rollout_sims))
    else:
        draft.setdefault("rollout_sims", 24)
    return LeagueConfig(
        teams=config.teams,
        roster=dict(config.roster),
        scoring=dict(config.scoring),
        provider=dict(config.provider or {}),
        draft=draft,
    )


def _score_pick(
    config: LeagueConfig,
    by_key: Dict[str, Player],
    available: set,
    roster_players: List[Player],
    picks: List[str],
    my_picks: List[str],
) -> Optional[str]:
    avail_players = [by_key[key] for key in available]
    my_roster: Dict[str, List[Player]] = {}
    for player in roster_players:
        my_roster.setdefault(player.position, []).append(player)
    state = DraftState(
        my_team_name="Me",
        league_teams=[f"T{i + 1}" for i in range(int(config.teams))],
        picks=list(picks),
        my_picks=list(my_picks),
    )
    ranked = rollout_values(config, avail_players, my_roster, state=state, top_n=1)
    if ranked:
        key = ranked[0].player.key()
        if key in available:
            return key
    points_map = compute_points(avail_players, config.scoring)
    return _adp_pick_for_roster(by_key, available, points_map, roster_players, config.roster)


def _adp_pick(
    by_key: Dict[str, Player],
    available: set,
    points_map: Dict[str, float],
) -> Optional[str]:
    if not available:
        return None
    return min(
        available,
        key=lambda key: (
            by_key[key].adp is None,
            float(by_key[key].adp) if by_key[key].adp is not None else 9999.0,
            -points_map.get(key, 0.0),
            by_key[key].position,
            by_key[key].name,
        ),
    )


def _adp_pick_for_roster(
    by_key: Dict[str, Player],
    available: set,
    points_map: Dict[str, float],
    roster_players: Sequence[Player],
    roster: Dict[str, int],
) -> Optional[str]:
    if not available:
        return None
    ordered = sorted(
        available,
        key=lambda key: (
            by_key[key].adp is None,
            float(by_key[key].adp) if by_key[key].adp is not None else 9999.0,
            -points_map.get(key, 0.0),
            by_key[key].position,
            by_key[key].name,
        ),
    )
    for key in ordered:
        if _can_add_to_roster(roster_players, by_key[key], roster):
            return key
    return _adp_pick(by_key, available, points_map)


def _can_add_to_roster(
    roster_players: Sequence[Player],
    candidate: Player,
    roster: Dict[str, int],
) -> bool:
    capacity = _draft_rounds(roster)
    if len(roster_players) >= capacity:
        return False

    max_by_pos = _max_by_position(roster)
    if max_by_pos.get(candidate.position, 0) <= 0:
        return False

    after = list(roster_players) + [candidate]
    counts: Dict[str, int] = {}
    for player in after:
        counts[player.position] = counts.get(player.position, 0) + 1
    if counts.get(candidate.position, 0) > max_by_pos.get(candidate.position, 0):
        return False

    remaining_picks = capacity - len(after)
    return remaining_picks >= _minimum_required_picks(counts, roster)


def _max_by_position(roster: Dict[str, int]) -> Dict[str, int]:
    bench = max(0, int(roster.get("BN", roster.get("BENCH", 0))))
    flex_counts: Dict[str, int] = {}
    for flex_key, positions in FLEX_TYPES.items():
        count = max(0, int(roster.get(flex_key, 0)))
        for pos in positions:
            flex_counts[pos] = flex_counts.get(pos, 0) + count
    out: Dict[str, int] = {}
    for pos in ("QB", "RB", "WR", "TE", "K", "DST"):
        positional_slots = max(0, int(roster.get(pos, 0)))
        flexible_slots = flex_counts.get(pos, 0)
        out[pos] = positional_slots + flexible_slots + (bench if positional_slots or flexible_slots else 0)
    return out


def _minimum_required_picks(counts: Dict[str, int], roster: Dict[str, int]) -> int:
    required = 0
    for pos in ("QB", "RB", "WR", "TE", "K", "DST"):
        required += max(0, int(roster.get(pos, 0)) - counts.get(pos, 0))

    flex_slots = 0
    flex_eligible = set()
    for flex_key, positions in FLEX_TYPES.items():
        slot_count = max(0, int(roster.get(flex_key, 0)))
        flex_slots += slot_count
        if slot_count:
            flex_eligible.update(positions)
    if flex_slots:
        eligible_overflow = 0
        for pos in flex_eligible:
            eligible_overflow += max(0, counts.get(pos, 0) - int(roster.get(pos, 0)))
        required += max(0, flex_slots - eligible_overflow)
    return required


def _draft_rounds(roster: Dict[str, int]) -> int:
    total = 0
    for key, value in roster.items():
        if key == "IR":
            continue
        total += max(0, int(value))
    return max(1, total)


def _unique_players(players: Sequence[Player]) -> Dict[str, Player]:
    by_key: Dict[str, Player] = {}
    for player in players:
        if player.key() not in by_key:
            by_key[player.key()] = player
    return by_key


def _rank(teams: Sequence[TeamScore], draft_slot: int, *, key: str) -> int:
    ordered = sorted(
        teams,
        key=lambda team: (getattr(team, key), team.total_value, -team.team_num),
        reverse=True,
    )
    for index, team in enumerate(ordered, 1):
        if team.team_num == draft_slot:
            return index
    return len(ordered)


def _avg(values: Iterable[float]) -> float:
    vals = list(values)
    if not vals:
        return 0.0
    return round(sum(vals) / len(vals), 2)


def _read_leagues_json(path: str) -> List[dict]:
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    if isinstance(data, dict):
        data = data.get("leagues") or data.get("fda_leagues") or []
    if not isinstance(data, list):
        raise ValueError("leagues JSON must be an array or an object with a leagues array")
    return [league for league in data if isinstance(league, dict)]


def _print_report(sweeps: Sequence[LeagueSweep]) -> None:
    for sweep in sweeps:
        print(f"\n{sweep.name}: {sweep.config.teams} teams, {_draft_rounds(sweep.config.roster)} rounds")
        print("slot  score_start  adp_start  delta_start  score_total  adp_total  delta_total  score_rank  adp_rank")
        for slot in sweep.slots:
            score = slot.score_draft.user_team
            adp = slot.adp_draft.user_team
            print(
                f"{slot.draft_slot:>4}  "
                f"{score.starter_value:>11.1f}  {adp.starter_value:>9.1f}  {slot.starter_delta:>11.1f}  "
                f"{score.total_value:>11.1f}  {adp.total_value:>9.1f}  {slot.total_delta:>11.1f}  "
                f"{slot.score_rank:>10}  {slot.adp_rank:>8}"
            )
        under = sum(1 for slot in sweep.slots if slot.starter_delta < 0)
        print(
            f"avg starter delta: {sweep.average_starter_delta:+.1f}; "
            f"avg total delta: {sweep.average_total_delta:+.1f}; "
            f"starter underperformance slots: {under}/{len(sweep.slots)}"
        )


def main(argv: Optional[Sequence[str]] = None) -> None:
    parser = argparse.ArgumentParser(description="Compare rollout draft score against ADP autodraft.")
    parser.add_argument("--profile", default=DEFAULT_PROFILE)
    parser.add_argument("--leagues-json", default=None, help="Optional exported web fda_leagues JSON.")
    parser.add_argument("--sims", type=int, default=None, help="Override rollout_sims for each pick.")
    args = parser.parse_args(argv)
    _print_report(load_league_sweeps(
        profile=args.profile,
        leagues_json=args.leagues_json,
        rollout_sims=args.sims,
    ))


if __name__ == "__main__":
    main()
