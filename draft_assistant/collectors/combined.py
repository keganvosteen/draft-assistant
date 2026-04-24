"""Combined collector that merges nflverse, Sleeper, and FFC data.

This is the primary data collection entry point. It orchestrates:
  1. nflverse — historical stats, rosters (age, team, draft capital), injuries, bye weeks
  2. Sleeper API — current-season projections and player metadata
  3. Fantasy Football Calculator — ADP data

The result is a fully enriched Player list ready for the draft assistant.
"""
from __future__ import annotations

from typing import Dict, List, Optional

from ..models import Player
from ..fuzzy import best_match


def _normalize_name(name: str) -> str:
    """Lowercase, strip suffixes like Jr./Sr./III, collapse whitespace."""
    import re
    name = name.strip()
    name = re.sub(r"\s+(Jr\.?|Sr\.?|II|III|IV|V)$", "", name, flags=re.IGNORECASE)
    return " ".join(name.lower().split())


def _match_key(name: str, position: str) -> str:
    return f"{_normalize_name(name)}|{position}"


def collect_all(
    current_season: int = 2025,
    history_seasons: int = 3,
    scoring_format: str = "ppr",
    teams: int = 12,
    skip_sleeper: bool = False,
    skip_adp: bool = False,
) -> List[Player]:
    """Collect and merge data from all available sources.

    Args:
        current_season: Upcoming/current fantasy season.
        history_seasons: Number of prior seasons for historical stats.
        scoring_format: ADP format ("ppr", "half-ppr", "standard").
        teams: League size for ADP.
        skip_sleeper: Skip Sleeper API (for offline/testing).
        skip_adp: Skip FFC ADP (for offline/testing).

    Returns:
        Enriched Player list with stats, projections, ADP, injuries, etc.
    """
    # ── Step 1: nflverse (historical stats, roster info, injuries, bye weeks) ──
    print("=" * 60)
    print("STEP 1: Loading nflverse data (historical stats, rosters, injuries)")
    print("=" * 60)
    try:
        from .nflverse import collect_players as nflverse_collect
        nfl_players = nflverse_collect(
            current_season=current_season,
            history_seasons=history_seasons,
        )
    except ImportError:
        print("nfl_data_py not installed. Run: pip install nfl_data_py pandas")
        print("Skipping nflverse data.")
        nfl_players = []
    except Exception as e:
        print(f"nflverse collection failed: {e}")
        nfl_players = []

    # Build lookup by normalized name|position
    nfl_by_key: Dict[str, Player] = {}
    for p in nfl_players:
        key = _match_key(p.name, p.position)
        nfl_by_key[key] = p

    # ── Step 2: Sleeper API (projections + metadata) ──
    sleeper_players: List[Player] = []
    if not skip_sleeper:
        print()
        print("=" * 60)
        print("STEP 2: Fetching Sleeper API projections")
        print("=" * 60)
        try:
            from .sleeper_historical import collect_players as sleeper_collect
            sleeper_players = sleeper_collect(
                current_season=current_season,
                history_seasons=0,
            )
        except Exception as e:
            print(f"Sleeper collection failed: {e}")
    else:
        print("\nSkipping Sleeper API (--skip-sleeper).")

    sleeper_by_key: Dict[str, Player] = {}
    for p in sleeper_players:
        key = _match_key(p.name, p.position)
        sleeper_by_key[key] = p

    # ── Step 3: FFC ADP ──
    adp_map: Dict[str, float] = {}
    if not skip_adp:
        print()
        print("=" * 60)
        print("STEP 3: Fetching ADP data")
        print("=" * 60)
        try:
            from .ffc_adp import fetch_adp
            raw_adp = fetch_adp(
                year=current_season,
                scoring=scoring_format,
                teams=teams,
            )
            # Normalize ADP keys
            for key, val in raw_adp.items():
                name, pos = key.rsplit("|", 1)
                norm_key = _match_key(name, pos)
                adp_map[norm_key] = val
        except Exception as e:
            print(f"ADP fetch failed: {e}")
    else:
        print("\nSkipping ADP (--skip-adp).")

    # ── Step 4: Merge everything ──
    print()
    print("=" * 60)
    print("STEP 4: Merging all sources")
    print("=" * 60)

    # Start with nflverse players as the base (richest metadata)
    all_keys = set(nfl_by_key.keys()) | set(sleeper_by_key.keys())

    # For fuzzy matching Sleeper players to nflverse
    nfl_names_by_pos: Dict[str, List[str]] = {}
    for key in nfl_by_key:
        name, pos = key.rsplit("|", 1)
        nfl_names_by_pos.setdefault(pos, []).append(name)

    merged: List[Player] = []
    matched_sleeper_keys: set = set()

    for key in sorted(all_keys):
        nfl_p = nfl_by_key.get(key)
        slp_p = sleeper_by_key.get(key)

        # Try fuzzy match if exact key doesn't match
        if nfl_p and not slp_p:
            name, pos = key.rsplit("|", 1)
            for skey, sp in sleeper_by_key.items():
                sname, spos = skey.rsplit("|", 1)
                if spos == pos and _normalize_name(sp.name) == name:
                    slp_p = sp
                    matched_sleeper_keys.add(skey)
                    break

        if slp_p and not nfl_p:
            name, pos = key.rsplit("|", 1)
            for nkey, np in nfl_by_key.items():
                nname, npos = nkey.rsplit("|", 1)
                if npos == pos and _normalize_name(np.name) == name:
                    nfl_p = np
                    break

        # Merge: nflverse base + Sleeper projections + ADP
        if nfl_p:
            base = nfl_p
            projections = slp_p.projections if slp_p and slp_p.projections else {}
            adp = adp_map.get(key) or (slp_p.adp if slp_p else None)
            # Prefer Sleeper bye_week if nflverse didn't have it
            bye = base.bye_week or (slp_p.bye_week if slp_p else None)
            # Merge injury lists
            injuries = list(base.injury_history)
            if slp_p and slp_p.injury_history:
                for inj in slp_p.injury_history:
                    if inj not in injuries:
                        injuries.append(inj)

            merged.append(Player(
                id=base.id,
                name=base.name,
                position=base.position,
                team=slp_p.team if slp_p and slp_p.team else base.team,
                bye_week=bye,
                adp=adp,
                projections=projections,
                age=base.age or (slp_p.age if slp_p else None),
                experience=base.experience or (slp_p.experience if slp_p else None),
                historical_stats=base.historical_stats,
                previous_team=base.previous_team or (slp_p.previous_team if slp_p else None),
                draft_capital=base.draft_capital,
                injury_history=injuries,
            ))
        elif slp_p:
            # Sleeper-only player (no nflverse match)
            adp = adp_map.get(key) or slp_p.adp
            merged.append(Player(
                id=slp_p.id,
                name=slp_p.name,
                position=slp_p.position,
                team=slp_p.team,
                bye_week=slp_p.bye_week,
                adp=adp,
                projections=slp_p.projections,
                age=slp_p.age,
                experience=slp_p.experience,
                historical_stats=slp_p.historical_stats,
                previous_team=slp_p.previous_team,
                draft_capital=slp_p.draft_capital,
                injury_history=slp_p.injury_history,
            ))

    # Stats summary
    with_proj = sum(1 for p in merged if p.projections)
    with_hist = sum(1 for p in merged if p.historical_stats)
    with_adp = sum(1 for p in merged if p.adp is not None)
    with_age = sum(1 for p in merged if p.age is not None)
    with_inj = sum(1 for p in merged if p.injury_history)

    print(f"\nMerged {len(merged)} players:")
    print(f"  Projections: {with_proj}")
    print(f"  Historical stats: {with_hist}")
    print(f"  ADP: {with_adp}")
    print(f"  Age data: {with_age}")
    print(f"  Injury history: {with_inj}")

    # Sort: players with projections first, then by name
    merged.sort(key=lambda p: (0 if p.projections else 1, p.name))
    return merged
