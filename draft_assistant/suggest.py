from __future__ import annotations
from collections import Counter
from typing import Dict, List, Tuple

from .models import LeagueConfig, Player
from .projections import compute_points, replacement_levels

FLEX_ELIGIBLE = {"RB", "WR", "TE"}

# --- Tunable constants for the gradient need model ---
# Base multiplier when a position is completely filled (starters + bench)
FILLED_BASE = 0.60
# Multiplier floor for partially filled positions
PARTIAL_FLOOR = 0.85
# Ceiling multiplier when a position is completely empty
NEED_CEILING = 1.25
# Bye-week stacking penalty per duplicate bye among starters
BYE_PENALTY = 0.04


def needs_by_position(
    config: LeagueConfig,
    my_roster: Dict[str, List[Player]],
) -> Dict[str, int]:
    """Return unfilled *starter* slots per position, including FLEX."""
    needs: Dict[str, int] = {}
    for pos in ["QB", "RB", "WR", "TE", "K", "DST"]:
        target = int(config.roster.get(pos, 0))
        have = len(my_roster.get(pos, []))
        needs[pos] = max(target - have, 0)

    # FLEX slots: filled by any FLEX-eligible player beyond their starter slots
    flex_target = int(config.roster.get("FLEX", 0))
    flex_filled = 0
    for pos in FLEX_ELIGIBLE:
        starter_slots = int(config.roster.get(pos, 0))
        have = len(my_roster.get(pos, []))
        overflow = max(have - starter_slots, 0)
        flex_filled += overflow
    needs["FLEX"] = max(flex_target - flex_filled, 0)
    return needs


def _position_need_multiplier(
    position: str,
    needs: Dict[str, int],
    config: LeagueConfig,
    my_roster: Dict[str, List[Player]],
    total_picks: int,
    total_rounds: int,
) -> float:
    """Compute a gradient need multiplier for *position*.

    The multiplier scales smoothly between NEED_CEILING (high urgency) and
    FILLED_BASE (position fully stocked) based on:
      - How many starter slots remain unfilled at that position.
      - How late we are in the draft (urgency rises in later rounds).
      - For FLEX-eligible positions, open FLEX slots still count as need.
    """
    pos_need = needs.get(position, 0)

    # For FLEX-eligible positions, factor in open FLEX slots
    flex_need = needs.get("FLEX", 0) if position in FLEX_ELIGIBLE else 0

    effective_need = pos_need + flex_need

    if effective_need <= 0:
        return FILLED_BASE

    # Total starter slots at this position (including FLEX share)
    starter_target = int(config.roster.get(position, 0))
    if position in FLEX_ELIGIBLE:
        starter_target += int(config.roster.get("FLEX", 0))

    # Fraction of slots still needed (0..1)
    need_frac = min(effective_need / max(starter_target, 1), 1.0)

    # Draft progress factor: urgency rises as draft advances
    if total_rounds > 0:
        progress = min(total_picks / max(total_rounds * config.teams, 1), 1.0)
    else:
        progress = 0.0

    # Blend: base grows linearly with need_frac, boosted further by draft progress
    multiplier = PARTIAL_FLOOR + (NEED_CEILING - PARTIAL_FLOOR) * need_frac
    # Add up to 15% extra urgency in the final third of the draft
    multiplier += 0.15 * progress * need_frac

    return multiplier


def _bye_week_penalty(
    player: Player,
    my_roster: Dict[str, List[Player]],
) -> float:
    """Return a penalty (subtracted from score) for bye-week stacking."""
    if not player.bye_week:
        return 0.0
    # Count how many of my current starters share this bye week
    bye_counts = 0
    for pos_players in my_roster.values():
        for p in pos_players:
            if p.bye_week == player.bye_week:
                bye_counts += 1
    return BYE_PENALTY * bye_counts


def suggest_players(
    config: LeagueConfig,
    available: List[Player],
    my_roster: Dict[str, List[Player]],
    top_n: int = 12,
    total_picks: int = 0,
) -> List[Tuple[Player, float, float, float]]:
    """Return ranked suggestions as (player, points, vor, score) tuples."""
    pts_map = compute_points(available, config.scoring)
    repl = replacement_levels(available, config.scoring, config.teams, config.roster)
    needs = needs_by_position(config, my_roster)

    # Estimate total rounds from roster size
    total_roster_spots = sum(int(v) for v in config.roster.values())
    total_rounds = total_roster_spots

    ranked: List[Tuple[Player, float, float, float]] = []
    for p in available:
        pts = pts_map.get(p.key(), 0.0)
        rep = repl.get(p.position, 0.0)
        vor = pts - rep

        need_mult = _position_need_multiplier(
            p.position, needs, config, my_roster, total_picks, total_rounds,
        )
        bye_pen = _bye_week_penalty(p, my_roster)
        score = vor * need_mult - bye_pen
        ranked.append((p, pts, vor, score))

    ranked.sort(key=lambda t: (t[3], t[2], t[1]), reverse=True)
    return ranked[:top_n]
