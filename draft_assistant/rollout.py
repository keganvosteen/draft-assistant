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
from typing import Dict, List, Optional, Sequence, Tuple

from .draft_value import (
    _bye_week_penalty,
    _draft_slot,
    _simulation_seed,
    _snake_pick_numbers,
    roster_value,
)
from .models import DraftState, LeagueConfig, Player
from .projections import compute_points, replacement_levels

# Positions we only draft once forced to (the owner fills K/DST last unless a
# rollout shows a standout is actually worth more season points). This is a
# *structural* default, not a league number — counts still come from config.
DEFER_LAST = {"K", "DST"}

DEFAULT_SIMS = 48
DEFAULT_MIN_CANDIDATES = 16

# How many candidates get the full rest-of-draft rollout. Deliberately NOT tied
# to ``top_n``: the caller asks for 30 rows to paint the board, but the decision
# is always among the top handful, and every extra candidate costs a full set of
# simulations. Players beyond this are still returned — ranked by the cheap
# prelim score and flagged ``simulated=False`` — so the board stays fully
# populated without paying to simulate a player nobody is about to draft.
DEFAULT_SIM_CANDIDATES = 16


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
    # True when this row came from the full rest-of-draft rollout. False means
    # ``impact`` is the cheap immediate-lineup-gain estimate instead — fine for
    # filling out the board, not comparable to a simulated row's impact.
    simulated: bool = True


def _flatten(my_roster: Dict[str, List[Player]]) -> List[Player]:
    players: List[Player] = []
    for group in my_roster.values():
        players.extend(group)
    return players


def _unmatched_roster_players(
    state: Optional[DraftState], roster_players: List[Player]
) -> List[Player]:
    """Represent synced picks that are not present on the projection board.

    Live provider sync deliberately retains an unmatched pick as ``name|POS``
    so the draft clock remains correct.  It must also occupy a roster slot:
    silently dropping it here made the engine believe the user had extra picks
    and still needed a player at that position.  A zero-point placeholder is a
    conservative value estimate while preserving roster shape.
    """
    if state is None:
        return []
    known = {
        key
        for player in roster_players
        for key in (player.key(), player.legacy_key())
    }
    placeholders: List[Player] = []
    valid_positions = {"QB", "RB", "WR", "TE", "K", "DST"}
    for key in state.my_picks:
        if key in known:
            continue
        name, separator, position = str(key).rpartition("|")
        position = position.upper() if separator else "UNKNOWN"
        if position not in valid_positions:
            position = "UNKNOWN"
        placeholders.append(Player(
            id=f"unmatched:{key}",
            name=name or str(key),
            position=position,
            metadata={"unmatched_roster_placeholder": True},
        ))
        known.add(key)
    return placeholders


def rollout_values(
    config: LeagueConfig,
    available: List[Player],
    my_roster: Dict[str, List[Player]],
    state: Optional[DraftState] = None,
    top_n: int = 20,
    drafted_players: Optional[Sequence[Player]] = None,
) -> List[RolloutResult]:
    """Rank available players by expected final-roster season points.

    Returns up to ``top_n`` ``RolloutResult`` rows sorted by ``impact`` (then by
    absolute expected roster points). Fully config-driven; safe on tiny pools
    (falls back to an immediate-lineup-gain ranking when there is nothing to
    simulate).
    """
    settings = config.draft or {}
    sims = max(0, min(int(settings.get("rollout_sims", DEFAULT_SIMS)), 512))
    noise = max(0.0, min(float(settings.get("adp_noise", 8.0)), 100.0))
    n_simulated = max(1, min(
        int(settings.get("rollout_candidates", 0) or 0) or DEFAULT_SIM_CANDIDATES,
        64,
    ))
    roster = config.roster

    roster_players = _flatten(my_roster)
    roster_players.extend(_unmatched_roster_players(state, roster_players))
    all_players = available + roster_players
    points_map = compute_points(all_players, config.scoring)
    by_key: Dict[str, Player] = {p.key(): p for p in all_players}
    occupied_by_key = {
        player.key(): player
        for player in [*(drafted_players or ()), *roster_players]
    }
    repl = replacement_levels(
        available,
        config.scoring,
        config.teams,
        roster,
        points_map=points_map,
        occupied_players=list(occupied_by_key.values()),
    )

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
    if state is not None:
        current_pick = len(state.picks) + 1
        # The actual board clock is authoritative.  Counting matched roster
        # objects loses unmatched provider picks and can point at a turn that is
        # already in the past.
        my_remaining = [pick for pick in my_picks_all if pick >= current_pick]
    else:
        used = len(roster_players)
        my_remaining = my_picks_all[used:] if used < len(my_picks_all) else []
        current_pick = my_remaining[0] if my_remaining else 1

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
                simulated=False,
            )
            for (p, gain, vor) in prelim[:top_n]
        ]

    decision_pick = my_remaining[0]
    start_pick = current_pick
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

    def greedy_pick(
        my_players: List[Player],
        avail: set,
        picks_left: int,
        cursor: Dict[str, int],
    ) -> Optional[str]:
        """Pick the available player that most raises lineup value + VOR surplus.

        For a fixed position the highest-projected available player always gives
        the largest lineup gain, so we only evaluate the best survivor per
        position. K/DST are ignored until the remaining picks can no longer all be
        skill players.

        ``cursor`` holds a per-position index into ``by_pos_sorted`` and belongs
        to one rollout. Within a rollout ``avail`` only ever shrinks, so a
        position's best survivor never moves backwards and the scan can resume
        where it left off. Restarting from the top of each position list every
        pick was the engine's dominant cost — by the late rounds it re-walked
        a couple of hundred taken players per position, per pick, per sim.
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
            if must_fill_kdst and pos not in DEFER_LAST:
                continue
            if pos in DEFER_LAST:
                need = k_need if pos == "K" else d_need
                if not (must_fill_kdst and need > 0):
                    continue
            i = cursor.get(pos, 0)
            while i < len(keys) and keys[i] not in avail:
                i += 1
            cursor[pos] = i
            if i >= len(keys):
                continue
            cand = keys[i]
            gain = roster_value(my_players + [by_key[cand]], points_map, roster).total_value - base
            vor = points_map.get(cand, 0.0) - repl.get(pos, 0.0)
            score = gain + (0.5 if gain > 0 else 0.05) * max(0.0, vor)
            if score > best_score:
                best_score, best_key = score, cand
        return best_key

    def one_rollout(order: List[str], forced_key: Optional[str]) -> float:
        avail = set(avail_keys)
        my_players = list(roster_players)
        cursor: Dict[str, int] = {}
        opp = 0
        for pick_no in range(start_pick, last_pick + 1):
            if pick_no in my_set:
                if (pick_no == decision_pick and forced_key is not None
                        and forced_key in avail):
                    choice: Optional[str] = forced_key
                else:
                    choice = greedy_pick(my_players, avail, picks_left_from(pick_no), cursor)
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

    # A legal finished roster must contain its configured K/DST slots.  When
    # the remaining number of picks equals the number still missing, only a
    # missing K/DST is a feasible decision.  Previously those positions were
    # deferred but never forced, so otherwise-good simulations could finish
    # with an invalid roster.
    have_at_decision: Dict[str, int] = {}
    for player in roster_players:
        have_at_decision[player.position] = have_at_decision.get(player.position, 0) + 1
    deferred_need = {
        pos: max(0, int(roster.get(pos, 0)) - have_at_decision.get(pos, 0))
        for pos in DEFER_LAST
    }
    decision_picks_left = picks_left_from(decision_pick)
    must_fill_deferred = decision_picks_left <= sum(deferred_need.values())

    def feasible_candidate(player: Player) -> bool:
        return (not must_fill_deferred
                or (player.position in DEFER_LAST
                    and deferred_need.get(player.position, 0) > 0))

    eligible_prelim = [entry for entry in prelim if feasible_candidate(entry[0])]
    # If the data pool itself lacks a required position, return the best board
    # available instead of returning no recommendations at all.  The data
    # quality gate prevents this in release datasets.
    if not eligible_prelim:
        eligible_prelim = prelim

    # Make sure the candidate pool includes top prelim + top 3 VOR per position.
    candidates = [t[0] for t in eligible_prelim[:n_simulated]]
    cand_keys = {p.key() for p in candidates}

    for pos in ["QB", "RB", "WR", "TE", "K", "DST"]:
        pos_avail = [p for p in available if p.position == pos and feasible_candidate(p)]
        pos_avail.sort(key=lambda p: points_map.get(p.key(), 0.0) - repl.get(p.position, 0.0), reverse=True)
        for p in pos_avail[:3]:
            if p.key() not in cand_keys:
                candidates.append(p)
                cand_keys.add(p.key())

    g0 = greedy_pick(roster_players, set(avail_keys), picks_left_from(decision_pick), {})
    if g0 is not None and g0 not in cand_keys and g0 in by_key:
        candidates.append(by_key[g0])
        cand_keys.add(g0)

    results: List[RolloutResult] = []

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
            r.impact,
            r.expected_roster_points,
            r.vor,
        ),
        reverse=True,
    )

    # Fill the rest of the requested rows from the prelim ranking, ordered by
    # immediate lineup gain and flagged simulated=False.
    #
    # Their ``impact`` is NOT on the simulated scale and must not be shown as
    # if it were. A simulated impact compares two *completed* rosters; all a
    # prelim row knows is what the player adds to the roster as it stands, which
    # is short by every pick still to come. There is no cheap correction for
    # that — closing the gap is exactly what the simulation does — so callers
    # should surface these as "no score yet" rather than as a weaker score.
    if len(results) < top_n:
        for (p, gain, vor) in prelim:
            if len(results) >= top_n:
                break
            if p.key() in cand_keys:
                continue
            results.append(RolloutResult(
                player=p,
                points=round(points_map.get(p.key(), 0.0), 2),
                vor=vor,
                immediate_gain=gain,
                expected_roster_points=round(base_value + gain, 2),
                impact=gain,
                gone_risk=gone_risk(p.key()),
                bye_penalty=_bye_week_penalty(p, roster_players, points_map, roster),
                sims=0,
                simulated=False,
            ))

    return results[:top_n]
