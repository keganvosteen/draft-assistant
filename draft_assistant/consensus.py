"""Multi-source projection consensus.

Merge projections from multiple files (e.g. FantasyPros + FFToday + custom)
into a single consensus projection using configurable aggregation.
"""
from __future__ import annotations
import statistics
from typing import Dict, List, Optional

from .models import Player
from .storage import load_players, save_players


def _merge_projections(
    sources: List[Dict[str, float]],
    method: str = "median",
) -> Dict[str, float]:
    """Merge multiple projection dicts for the same player.

    method: 'median' (default, robust to outliers) or 'mean'.
    """
    all_stats: Dict[str, List[float]] = {}
    for src in sources:
        for stat, val in src.items():
            all_stats.setdefault(stat, []).append(val)

    merged: Dict[str, float] = {}
    agg = statistics.median if method == "median" else statistics.mean
    for stat, values in all_stats.items():
        merged[stat] = round(agg(values), 2)
    return merged


def build_consensus(
    source_paths: List[str],
    method: str = "median",
    output_path: str = "data/projections.json",
) -> List[Player]:
    """Load players from multiple projection files and merge into consensus.

    Players are matched by name+position key. Fields like age, historical_stats,
    team, etc. are taken from the first source that has them.
    Projections are merged using the specified method.

    Returns the merged player list (also saved to output_path).
    """
    # Load all sources
    all_sources: List[List[Player]] = []
    for path in source_paths:
        players = load_players(path)
        if players:
            all_sources.append(players)
            print(f"  Loaded {len(players)} players from {path}")
        else:
            print(f"  Warning: no players found in {path}")

    if not all_sources:
        print("No sources loaded.")
        return []

    # Index players by key across all sources
    by_key: Dict[str, List[Player]] = {}
    for source in all_sources:
        for p in source:
            by_key.setdefault(p.key(), []).append(p)

    # Merge
    merged_players: List[Player] = []
    for key, variants in by_key.items():
        # Use first variant as base for metadata
        base = variants[0]

        # Merge projections from all sources
        proj_sources = [v.projections for v in variants if v.projections]
        if len(proj_sources) > 1:
            consensus_proj = _merge_projections(proj_sources, method)
        elif proj_sources:
            consensus_proj = dict(proj_sources[0])
        else:
            consensus_proj = {}

        # Take the richest metadata available across sources
        age = next((v.age for v in variants if v.age is not None), None)
        exp = next((v.experience for v in variants if v.experience is not None), None)
        hist = next((v.historical_stats for v in variants if v.historical_stats), {})
        team = next((v.team for v in variants if v.team), base.team)
        bye = next((v.bye_week for v in variants if v.bye_week is not None), None)
        adp_vals = [v.adp for v in variants if v.adp is not None]
        adp = round(statistics.mean(adp_vals), 1) if adp_vals else None
        prev_team = next((v.previous_team for v in variants if v.previous_team), None)

        merged_players.append(Player(
            id=base.id,
            name=base.name,
            position=base.position,
            team=team,
            bye_week=bye,
            adp=adp,
            projections=consensus_proj,
            age=age,
            experience=exp,
            historical_stats=hist,
            previous_team=prev_team,
            draft_capital=base.draft_capital,
            injury_history=base.injury_history,
        ))

    save_players(merged_players, output_path)
    print(f"Consensus: {len(merged_players)} players ({len(all_sources)} sources, {method}) -> {output_path}")
    return merged_players
