"""Rest-of-draft Monte Carlo rollout engine.

Ranks each available player by the EXPECTED TOTAL SEASON POINTS of the final
roster you would end up with if you draft that player now and keep drafting
optimally for the rest of the draft, while opponents pick by (noisy) ADP.

Everything is driven by the league you configure:
  * ``config.scoring`` turns raw stats into points (``compute_points``),
  * ``config.roster`` defines the starting lineup / FLEX / bench that determine
    "roster value" (``roster_value``),
  * ``config.teams`` + your draft slot define the snake order, and therefore
    which players survive to each of your future picks.
No roster shape or scoring weight is hard-coded here — create any league and the
engine adapts.

The headline number per player is ``impact``::

    impact(P) = E[ final-roster season points | I draft P now ]
              - E[ final-roster season points | I make my default greedy pick ]

A positive impact means "taking P now is worth this many extra season points
versus the obvious pick, once you account for who is still on the board at all of
your later picks." That is exactly the RB-now-vs-WR-now question: if the WR's
position falls off a cliff while RB stays deep, the WR-now rollouts finish with
more total points and the WR floats to the top — even when the RB scores more in
isolation.
"""
from __future__ import annotations

from dataclasses import dataclass
import random
from typing import Dict, List, Optional, Tuple

from .draft_value import (
    _bye_week_penalty,
    _draft_slot,
    _simulation_seed,
    _snake_pick_numbers,
    roster_value,
)
from .models import DraftState, LeagueConfig, Player
from .projections import compute_points, replacement_levels
from .scoring_utils import (
    _apply_need_multiplier,
    _position_need_multiplier,
    needs_by_position,
)

# Positions we only draft once forced to (the owner fills K/DST last unless a
# rollout shows a standout is actually worth more season points). This is a
# *structural* default, not a league number — counts still come from config.
DEFER_LAST = {"K", "DST"}

DEFAULT_SIMS = 48
DEFAULT_MIN_CANDIDATES = 16


@dataclass(frozen=True)
class RolloutResult:
    player: Player
    points: float                  # projected season points (raw, league scoring)
    vor: float                     # points - positional replacement level
    immediate_gain: float          # marginal optimal-lineup gain if added right now
    expected_roster_points: float  # E[final roster season pts | drafted now]
    impact: float                  # expected_roster_points vs. the default greedy pick
    gone_risk: float               # P(taken by an opponent before your next pick)
    bye_penalty: float
    sims: int


def _flatten(my_roster: Dict[str, List[Player]]) -> List[Player]:
    players: List[Player] = []
    for group in my_roster.values():
        players.extend(group)
    return players


def rollout_values(
    config: LeagueConfig,
    available: List[Player],
    my_roster: Dict[str, List[Player]],
    state: Optional[DraftState] = None,
    top_n: int = 20,
) -> List[RolloutResult]:
    """Rank available players by expected final-roster season points.

    Returns up to ``top_n`` ``RolloutResult`` rows sorted by ``impact`` (then by
    absolute expected roster points). Fully config-driven; safe on tiny pools
    (falls back to an immediate-lineup-gain ranking when there is nothing to
    simulate).
    """
    settings = config.draft or {}
    sims = max(0, int(settings.get("rollout_sims", DEFAULT_SIMS)))
    noise = float(settings.get("adp_noise", 8.0))
    n_candidates = max(int(settings.get("rollout_candidates", 0) or 0), top_n, DEFAULT_MIN_CANDIDATES)
    roster = config.roster

    roster_players = _flatten(my_roster)
    all_players = available + roster_players
    points_map = compute_points(all_players, config.scoring)
    by_key: Dict[str, Player] = {p.key(): p for p in all_players}
    repl = replacement_levels(
        available, config.scoring, config.teams, roster, points_map=points_map
    )

    surplus_map = {
        p.key(): max(0.0, points_map.get(p.key(), 0.0) - repl.get(p.position, 0.0))
        for p in all_players
    }

    base_value = roster_value(roster_players, points_map, roster).total_value

    # ---- cheap prelim ranking (immediate optimal-lineup gain + VOR) ------------
    prelim: List[Tuple[Player, float, float]] = []  # (player, combined_score, vor)
    for p in available:
        gain = roster_value(roster_players + [p], points_map, roster).total_value - base_value
        vor = points_map.get(p.key(), 0.0) - repl.get(p.position, 0.0)
        combined = gain + (0.5 if gain > 0 else 0.05) * max(0.0, vor)
        prelim.append((p, round(combined, 2), round(vor, 2)))
    prelim.sort(key=lambda t: (t[1], t[2]), reverse=True)
    prelim_gain = {p.key(): gain for p, gain, _ in prelim}

    # ---- snake-draft pick structure, derived entirely from config -----------
    teams = max(1, int(config.teams))
    draft_slot = _draft_slot(config, state)
    total_rounds = sum(int(v) for k, v in roster.items() if k != "IR")
    my_picks_all = _snake_pick_numbers(teams, draft_slot, rounds=max(total_rounds, 1))
    used = len(roster_players)
    my_remaining = my_picks_all[used:] if used < len(my_picks_all) else []
    current_pick = (len(state.picks) + 1) if state else (my_remaining[0] if my_remaining else 1)

    # Degenerate cases: no lookahead possible -> return prelim ranking.
    if sims <= 0 or not my_remaining or not available:
        return [
            RolloutResult(
                player=p,
                points=round(points_map.get(p.key(), 0.0), 2),
                vor=vor,
                immediate_gain=gain,
                expected_roster_points=round(base_value + gain, 2),
                impact=gain,
                gone_risk=0.0,
                bye_penalty=_bye_week_penalty(p, roster_players, points_map, roster),
                sims=0,
            )
            for (p, gain, vor) in prelim[:top_n]
        ]

    decision_pick = my_remaining[0]
    start_pick = min(current_pick, decision_pick)
    last_pick = my_remaining[-1]
    my_set = set(my_remaining)

    def picks_left_from(pick_no: int) -> int:
        return sum(1 for x in my_remaining if x >= pick_no)

    # available keys grouped by position, each sorted best-first by points
    avail_keys = [p.key() for p in available]
    by_pos_sorted: Dict[str, List[str]] = {}
    for p in available:
        by_pos_sorted.setdefault(p.position, []).append(p.key())
    for keys in by_pos_sorted.values():
        keys.sort(key=lambda k: points_map.get(k, 0.0), reverse=True)

    def greedy_pick(my_players: List[Player], avail: set, picks_left: int) -> Optional[str]:
        """Pick the available player that most raises lineup value + VOR surplus.

        For a fixed position the highest-projected available player always gives
        the largest lineup gain, so we only evaluate the best survivor per
        position. K/DST are ignored until the remaining picks can no longer all be
        skill players.
        """
        base = roster_value(my_players, points_map, roster).total_value
        have: Dict[str, int] = {}
        for pl in my_players:
            have[pl.position] = have.get(pl.position, 0) + 1
        k_need = max(0, int(roster.get("K", 0)) - have.get("K", 0))
        d_need = max(0, int(roster.get("DST", 0)) - have.get("DST", 0))
        must_fill_kdst = picks_left <= (k_need + d_need)

        best_key: Optional[str] = None
        best_score = float("-inf")
        for pos, keys in by_pos_sorted.items():
            if pos in DEFER_LAST:
                need = k_need if pos == "K" else d_need
                if not (must_fill_kdst and need > 0):
                    continue
            cand = next((k for k in keys if k in avail), None)
            if cand is None:
                continue
            gain = roster_value(my_players + [by_key[cand]], points_map, roster).total_value - base
            vor = points_map.get(cand, 0.0) - repl.get(pos, 0.0)
            score = gain + (0.5 if gain > 0 else 0.05) * max(0.0, vor)
            if score > best_score:
                best_score, best_key = score, cand
        return best_key

    def one_rollout(order: List[str], forced_key: Optional[str]) -> float:
        avail = set(avail_keys)
        if forced_key is not None:
            avail.discard(forced_key)  # reserve it for my decision pick
        my_players = list(roster_players)
        opp = 0
        for pick_no in range(start_pick, last_pick + 1):
            if pick_no in my_set:
                if pick_no == decision_pick and forced_key is not None:
                    choice: Optional[str] = forced_key
                else:
                    choice = greedy_pick(my_players, avail, picks_left_from(pick_no))
                if choice is not None:
                    my_players.append(by_key[choice])
                    avail.discard(choice)
            else:
                while opp < len(order) and order[opp] not in avail:
                    opp += 1
                if opp < len(order):
                    avail.discard(order[opp])
                    opp += 1
        return roster_value(my_players, points_map, roster).total_value

    # ---- common random numbers: one opponent ordering per sim, shared across
    #      the baseline and every candidate so comparisons are apples-to-apples.
    seed = _simulation_seed(config, state)
    base_adp = [
        (float(p.adp) if p.adp is not None else 999.0, p.key()) for p in available
    ]
    orders: List[List[str]] = []
    for s in range(sims):
        rng = random.Random(seed + s * 7919)
        sampled = sorted((adp + rng.gauss(0.0, noise), key) for adp, key in base_adp)
        orders.append([key for _, key in sampled])

    baseline = [one_rollout(order, None) for order in orders]
    baseline_mean = sum(baseline) / sims

    # gone-risk: opponents take the top `gap` of the board before my next pick
    following = my_remaining[1] if len(my_remaining) > 1 else None
    gap = (following - decision_pick - 1) if following is not None else 0

    def gone_risk(key: str) -> float:
        if gap <= 0:
            return 0.0
        hit = sum(1 for order in orders if key in order[:gap])
        return round(hit / len(orders), 2)

    # Make sure candidates pool includes top prelim + top 3 VOR per position
    candidates = [t[0] for t in prelim[:n_candidates]]
    cand_keys = {p.key() for p in candidates}

    for pos in ["QB", "RB", "WR", "TE"]:
        pos_avail = [p for p in available if p.position == pos]
        pos_avail.sort(key=lambda p: points_map.get(p.key(), 0.0) - repl.get(p.position, 0.0), reverse=True)
        for p in pos_avail[:3]:
            if p.key() not in cand_keys:
                candidates.append(p)
                cand_keys.add(p.key())

    g0 = greedy_pick(roster_players, set(avail_keys), picks_left_from(decision_pick))
    if g0 is not None and g0 not in cand_keys and g0 in by_key:
        candidates.append(by_key[g0])

    results: List[RolloutResult] = []
    needs = needs_by_position(config, my_roster)

    for p in candidates:
        key = p.key()
        finals = [one_rollout(order, key) for order in orders]
        expected_final = sum(finals) / sims
        bye = _bye_week_penalty(p, roster_players, points_map, roster)
        impact = (expected_final - baseline_mean) - bye
        results.append(RolloutResult(
            player=p,
            points=round(points_map.get(key, 0.0), 2),
            vor=round(points_map.get(key, 0.0) - repl.get(p.position, 0.0), 2),
            immediate_gain=prelim_gain.get(key, 0.0),
            expected_roster_points=round(expected_final, 2),
            impact=round(impact, 2),
            gone_risk=gone_risk(key),
            bye_penalty=bye,
            sims=sims,
        ))

    results.sort(
        key=lambda r: (
            _apply_need_multiplier(r.impact, _position_need_multiplier(r.player.position, needs, config, my_roster, used, total_rounds)),
            r.expected_roster_points,
            r.vor,
        ),
        reverse=True,
    )
    return results[:top_n]
