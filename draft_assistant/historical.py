"""Historical trend analysis and age-curve adjustments.

This module provides:
  - Positional aging curves derived from NFL historical data.
  - A projection adjuster that blends raw projections with historical
    trends, age expectations, and situation changes.
"""
from __future__ import annotations
from typing import Dict, List, Optional

from .models import Player

# ---------------------------------------------------------------------------
# Age curves: multiplier relative to peak-age production at each position.
# These are derived from aggregate NFL data showing how fantasy-relevant
# stats change with age.  Peak = 1.00.
# ---------------------------------------------------------------------------

AGE_CURVES: Dict[str, Dict[int, float]] = {
    "QB": {
        21: 0.70, 22: 0.78, 23: 0.85, 24: 0.91, 25: 0.95, 26: 0.98,
        27: 1.00, 28: 1.00, 29: 0.99, 30: 0.97, 31: 0.95, 32: 0.92,
        33: 0.88, 34: 0.84, 35: 0.79, 36: 0.74, 37: 0.68, 38: 0.62,
        39: 0.55, 40: 0.48,
    },
    "RB": {
        20: 0.72, 21: 0.82, 22: 0.90, 23: 0.95, 24: 0.99, 25: 1.00,
        26: 0.97, 27: 0.92, 28: 0.85, 29: 0.76, 30: 0.66, 31: 0.55,
        32: 0.44, 33: 0.34, 34: 0.25,
    },
    "WR": {
        20: 0.60, 21: 0.70, 22: 0.80, 23: 0.87, 24: 0.93, 25: 0.97,
        26: 1.00, 27: 1.00, 28: 0.98, 29: 0.95, 30: 0.91, 31: 0.86,
        32: 0.80, 33: 0.73, 34: 0.65, 35: 0.56,
    },
    "TE": {
        21: 0.55, 22: 0.65, 23: 0.74, 24: 0.82, 25: 0.89, 26: 0.94,
        27: 0.98, 28: 1.00, 29: 0.99, 30: 0.96, 31: 0.92, 32: 0.86,
        33: 0.79, 34: 0.70, 35: 0.60,
    },
    "K": {
        22: 0.90, 23: 0.93, 24: 0.95, 25: 0.97, 26: 0.99, 27: 1.00,
        28: 1.00, 29: 1.00, 30: 1.00, 31: 0.99, 32: 0.98, 33: 0.97,
        34: 0.96, 35: 0.94, 36: 0.92, 37: 0.90, 38: 0.87, 39: 0.84,
        40: 0.80, 41: 0.76, 42: 0.72,
    },
    "DST": {},  # not age-dependent
}


def age_curve_factor(position: str, age: Optional[int]) -> float:
    """Return the age-curve multiplier for a player's position and age.

    Returns 1.0 when age is unknown or the position has no curve data.
    For ages between defined points, linearly interpolates.
    """
    if age is None:
        return 1.0
    curve = AGE_CURVES.get(position, {})
    if not curve:
        return 1.0

    ages = sorted(curve.keys())
    if age <= ages[0]:
        return curve[ages[0]]
    if age >= ages[-1]:
        return curve[ages[-1]]

    # Linear interpolation
    for i in range(len(ages) - 1):
        if ages[i] <= age <= ages[i + 1]:
            lo, hi = ages[i], ages[i + 1]
            frac = (age - lo) / (hi - lo)
            return curve[lo] + (curve[hi] - curve[lo]) * frac
    return 1.0


def age_progression_factor(position: str, age: Optional[int]) -> float:
    """Expected year-over-year production change going into the upcoming season.

    Returns curve(age) / curve(age - 1). Projections (and last seasons' stats)
    already reflect the player's established level — what they don't price is
    the change the next year of aging brings, so only that ratio is applied.
    Using the absolute curve value here would double-count age and, e.g., dock
    a 30-year-old RB 34% on top of an already age-aware projection.
    """
    if age is None:
        return 1.0
    if not AGE_CURVES.get(position):
        return 1.0
    prev = age_curve_factor(position, age - 1)
    if prev <= 0:
        return 1.0
    return age_curve_factor(position, age) / prev


def _historical_trend(
    historical: Dict[int, Dict[str, float]],
    stat: str,
) -> Optional[float]:
    """Compute a recency-weighted trend value across all accumulated seasons.

    Weight decays exponentially from the most recent season
    (1.0, 0.6, 0.36, 0.216, ...), so recent form dominates while a longer
    history still contributes. Returns None if no data exists for this stat.
    """
    if not historical:
        return None
    years = sorted(historical.keys(), reverse=True)
    decay = 0.6
    total_weight = 0.0
    weighted_sum = 0.0
    for i, year in enumerate(years):
        val = historical[year].get(stat)
        if val is None:
            continue
        weight = decay ** i
        weighted_sum += val * weight
        total_weight += weight
    if total_weight == 0:
        return None
    return weighted_sum / total_weight


# Situation-change adjustments: empirical multipliers for common scenarios
TEAM_CHANGE_PENALTY = 0.92       # Changing teams hurts ~8% on average in year 1
COACHING_CHANGE_FACTOR = 0.97    # New OC: small uncertainty penalty


def adjust_projections(player: Player, scoring: Dict[str, float]) -> Dict[str, float]:
    """Return adjusted projections blending raw projection with historical trends.

    Priority:
      1. If the player has historical stats, blend with raw projection (60/40
         raw/historical), then apply the year-over-year age progression.
      2. If only age is known, apply the age progression to raw projections.
      3. If there is no published projection at all, fall back to the
         recency-weighted trend aged forward one season.
      4. If the player changed teams, apply a small penalty.
    """
    raw = dict(player.projections)
    adjusted = {}

    has_history = bool(player.historical_stats)
    age_factor = age_progression_factor(player.position, player.age)

    if not raw and has_history:
        stat_keys = set()
        for season_stats in player.historical_stats.values():
            stat_keys.update(season_stats.keys())
        for stat in sorted(stat_keys):
            trend_val = _historical_trend(player.historical_stats, stat)
            if trend_val is not None:
                adjusted[stat] = round(trend_val * age_factor, 2)

    for stat, raw_val in raw.items():
        trend_val = _historical_trend(player.historical_stats, stat) if has_history else None
        if trend_val is not None:
            # Blend: 60% raw projection, 40% historical trend
            blended = 0.6 * raw_val + 0.4 * trend_val
        else:
            blended = raw_val

        # Expected change from one more year of aging
        blended *= age_factor

        adjusted[stat] = round(blended, 2)

    # Team-change penalty
    if player.previous_team and player.team and player.previous_team != player.team:
        for stat in adjusted:
            adjusted[stat] = round(adjusted[stat] * TEAM_CHANGE_PENALTY, 2)

    return adjusted


def confidence_score(player: Player) -> float:
    """Return a 0-1 confidence score for this player's projection.

    Higher when we have more historical data and the projection aligns
    with the trend.  Lower for rookies, team changers, or players with
    injury history.
    """
    score = 0.5  # baseline

    # More historical seasons -> higher confidence
    n_seasons = len(player.historical_stats)
    score += min(n_seasons, 3) * 0.10  # up to +0.30

    # Age in peak range -> higher confidence (only if age is known)
    if player.age is not None:
        age_f = age_curve_factor(player.position, player.age)
        if age_f >= 0.95:
            score += 0.10

    # Team change -> lower confidence
    if player.previous_team and player.team and player.previous_team != player.team:
        score -= 0.15

    # Injury history -> lower confidence
    if player.injury_history:
        score -= min(len(player.injury_history), 3) * 0.05

    return max(0.0, min(1.0, score))
