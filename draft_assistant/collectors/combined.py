"""Combined collector that merges the free-source pull with deeper sources.

This is the primary data collection entry point. It orchestrates:
  1. Free sources - the full free-source consensus pull (Sleeper projections,
     FFC ADP, nflverse rosters and season stats, FFToday, ESPN). This is the
     player pool; the steps below only enrich it.
  2. nfl_data_py - age, draft capital, injury history, extra stat seasons
  3. Sleeper season-stats archive - additional historical seasons
  4. Fantasy Football Calculator - ADP gap-fill when step 1 didn't supply it

The result is a fully enriched Player list ready for the draft assistant, and
a strict superset of what the free-source pull returns.
"""
from __future__ import annotations

import copy
from typing import Dict, List, Optional

from ..models import LeagueConfig, Player
from ..fuzzy import best_match, normalize_player_key, normalize_player_name
from ..importers.free_sources import (
    FreeDataResult,
    SourceReport,
    _fill_missing_byes,
    _merge_key,
    _merge_many,
    pull_free_data,
)
from ..scoring import fantasy_points


def _normalize_name(name: str) -> str:
    """Lowercase, strip suffixes like Jr./Sr./III, collapse whitespace."""
    return normalize_player_name(name)


def _match_key(name: str, position: str) -> str:
    return normalize_player_key(name, position)


def _pair_fuzzy_keys(
    nfl_keys: set,
    sleeper_keys: set,
    max_distance: int = 2,
) -> Dict[str, str]:
    """Pair near-miss normalized keys between the two sources.

    Returns {nfl_key: sleeper_key} for names that differ by small typos or
    punctuation within the same position. Keys with exact matches in the other
    source are excluded, and each sleeper key is claimed at most once so the
    same record can't merge into two players.
    """
    sleeper_names_by_pos: Dict[str, List[str]] = {}
    for key in sleeper_keys:
        if key in nfl_keys:
            continue
        name, pos = key.rsplit("|", 1)
        sleeper_names_by_pos.setdefault(pos, []).append(name)

    pairs: Dict[str, str] = {}
    claimed: set = set()
    for key in sorted(nfl_keys):
        if key in sleeper_keys:
            continue
        name, pos = key.rsplit("|", 1)
        candidates = [
            cand for cand in sleeper_names_by_pos.get(pos, [])
            if f"{cand}|{pos}" not in claimed
        ]
        match = best_match(name, candidates, max_distance=max_distance)
        if match:
            sleeper_key = f"{match}|{pos}"
            pairs[key] = sleeper_key
            claimed.add(sleeper_key)
    return pairs


def _default_config(scoring_format: str, teams: int) -> LeagueConfig:
    """A stand-in league for callers that don't have one loaded.

    Only the ADP format and the sort tiebreak depend on it, but
    ``pull_free_data`` requires a config, so synthesize one from app defaults.
    """
    from ..config import DEFAULT_CONFIG

    data = copy.deepcopy(DEFAULT_CONFIG)
    data["teams"] = teams
    data["scoring"]["rec"] = {"ppr": 1.0, "half-ppr": 0.5, "standard": 0.0}.get(
        scoring_format, 1.0
    )
    return LeagueConfig(**data)


def _align_names(pool: Dict[str, Player], incoming: List[Player]) -> List[Player]:
    """Rename near-miss incoming players onto their pool counterpart.

    The enrichment sources spell some names differently from the free-source
    pool ("D'Andre Swift" vs "Deandre Swift"). Rewriting the incoming name to
    the pool's spelling makes ``_merge_key`` line up, so the record enriches
    the existing player instead of landing beside it as a duplicate.
    """
    if not incoming:
        return incoming

    # DST merges on team code, not name, so it never needs fuzzy alignment.
    pool_by_norm: Dict[str, Player] = {}
    for player in pool.values():
        if player.position == "DST":
            continue
        pool_by_norm[_match_key(player.name, player.position)] = player

    incoming_keys = {
        _match_key(p.name, p.position) for p in incoming if p.position != "DST"
    }
    pairs = _pair_fuzzy_keys(incoming_keys, set(pool_by_norm))

    for player in incoming:
        if player.position == "DST":
            continue
        paired = pairs.get(_match_key(player.name, player.position))
        target = pool_by_norm.get(paired) if paired else None
        if target is not None:
            player.name = target.name
    return incoming


def _absorb(pool: Dict[str, Player], incoming: List[Player], source: str) -> None:
    """Merge an enrichment source into the pool without dropping anyone."""
    _merge_many(pool, _align_names(pool, incoming), source)


def _collect_nflverse(
    current_season: int,
    history_seasons: int,
    reports: List[SourceReport],
) -> List[Player]:
    print()
    print("=" * 60)
    print("STEP 2: nfl_data_py enrichment (rosters, injuries, draft capital)")
    print("=" * 60)
    try:
        import nfl_data_py  # noqa: F401
    except ImportError:
        msg = "nfl_data_py not installed (pip install -r requirements-data.txt)"
        print(msg)
        reports.append(SourceReport("nfl_data_py", 0, ok=False, detail=msg))
        return []
    try:
        from .nflverse import collect_players as nflverse_collect
        players = nflverse_collect(
            current_season=current_season,
            history_seasons=history_seasons,
        )
        reports.append(SourceReport("nfl_data_py", len(players),
                                    detail=f"{history_seasons} season(s)"))
        return players
    except Exception as exc:
        print(f"nfl_data_py collection failed: {exc}")
        reports.append(SourceReport("nfl_data_py", 0, ok=False, detail=str(exc)))
        return []


def _collect_sleeper_history(
    current_season: int,
    history_seasons: int,
    reports: List[SourceReport],
) -> List[Player]:
    print()
    print("=" * 60)
    print("STEP 3: Sleeper season-stats archive")
    print("=" * 60)
    try:
        from .sleeper_historical import collect_players as sleeper_collect
        players = sleeper_collect(
            current_season=current_season,
            history_seasons=history_seasons,
        )
        reports.append(SourceReport("Sleeper season stats", len(players),
                                    detail=f"{history_seasons} season(s)"))
        return players
    except Exception as exc:
        print(f"Sleeper collection failed: {exc}")
        reports.append(SourceReport("Sleeper season stats", 0, ok=False, detail=str(exc)))
        return []


def _fill_adp_gaps(
    pool: Dict[str, Player],
    current_season: int,
    scoring_format: str,
    teams: int,
    reports: List[SourceReport],
) -> None:
    print()
    print("=" * 60)
    print("STEP 4: Fantasy Football Calculator ADP")
    print("=" * 60)
    try:
        from .ffc_adp import fetch_adp
        raw_adp = fetch_adp(year=current_season, scoring=scoring_format, teams=teams)
    except Exception as exc:
        print(f"ADP fetch failed: {exc}")
        reports.append(SourceReport("Fantasy Football Calculator ADP", 0, ok=False,
                                    detail=str(exc)))
        return

    by_norm = {_match_key(p.name, p.position): p for p in pool.values()}
    filled = 0
    for key, val in raw_adp.items():
        name, pos = key.rsplit("|", 1)
        player = by_norm.get(_match_key(name, pos))
        if player is not None and (player.adp is None or val < player.adp):
            player.adp = val
            filled += 1
    reports.append(SourceReport("Fantasy Football Calculator ADP", filled,
                                detail=f"{current_season} {scoring_format}"))


def collect_all_result(
    current_season: int = 2025,
    history_seasons: int = 3,
    scoring_format: str = "ppr",
    teams: int = 12,
    skip_sleeper: bool = False,
    skip_adp: bool = False,
    config: Optional[LeagueConfig] = None,
    stats_season: Optional[int] = None,
    include_fftoday: bool = True,
    espn_league_id: Optional[str] = None,
    skip_free_sources: bool = False,
) -> FreeDataResult:
    """Collect and merge every available source, the free ones included.

    Full Collect is a *superset* of the free pull, not an alternative to it:
    the free sources define the player pool, and nfl_data_py plus Sleeper's
    season-stats archive layer deeper metadata (age, draft capital, injury
    history, extra stat seasons) on top. Enrichment only ever adds, so the
    result can't come back smaller than the free pull.

    Args:
        current_season: Upcoming/current fantasy season.
        history_seasons: Number of prior seasons of historical stats.
        scoring_format: ADP format ("ppr", "half-ppr", "standard").
        teams: League size for ADP.
        skip_sleeper: Skip Sleeper's season-stats archive (for offline/testing).
        skip_adp: Skip the FFC ADP gap-fill (for offline/testing).
        config: League whose scoring orders the board; synthesized if omitted.
        stats_season: Most recent completed season for the free pull's stats.
        include_fftoday: Scrape FFToday projections during the free pull.
        espn_league_id: Public ESPN league to fold into the consensus.
        skip_free_sources: Enrichment sources only (for offline/testing).

    Returns:
        Players plus the per-source reports and warnings the UI renders.
    """
    config = config or _default_config(scoring_format, teams)
    reports: List[SourceReport] = []
    warnings: List[str] = []
    consensus_players = 0
    pool: Dict[str, Player] = {}

    # ── Step 1: free sources — the very pull "Free Sources" mode runs ──
    if not skip_free_sources:
        print("=" * 60)
        print("STEP 1: Free consensus sources (Sleeper, FFC, nflverse, FFToday)")
        print("=" * 60)
        try:
            free = pull_free_data(
                config=config,
                season=current_season,
                stats_season=stats_season,
                teams=teams,
                adp_format=scoring_format,
                include_fftoday=include_fftoday,
                espn_league_id=espn_league_id,
                history_seasons=history_seasons,
            )
            reports.extend(free.reports)
            warnings.extend(free.warnings)
            consensus_players = free.consensus_players
            for player in free.players:
                pool[_merge_key(player)] = player
            print(f"Free sources: {len(free.players)} players.")
        except Exception as exc:
            print(f"Free-source pull failed: {exc}")
            reports.append(SourceReport("Free sources", 0, ok=False, detail=str(exc)))
    else:
        print("Skipping free sources (enrichment only).")

    free_players = len(pool)

    # ── Step 2: nfl_data_py — age, draft capital, injuries, deeper stats ──
    _absorb(pool, _collect_nflverse(current_season, history_seasons, reports),
            "nfl_data_py")

    # ── Step 3: Sleeper's season-stats archive ──
    if not skip_sleeper:
        _absorb(pool, _collect_sleeper_history(current_season, history_seasons, reports),
                "sleeper_historical")
    else:
        print("\nSkipping Sleeper season stats (--skip-sleeper).")

    # ── Step 4: ADP gap-fill. The free pull already merges FFC ADP, so only
    # re-fetch when that pull didn't run or came back empty. ──
    have_adp = any(
        r.source.startswith("Fantasy Football Calculator") and r.ok and r.records
        for r in reports
    )
    if skip_adp:
        print("\nSkipping ADP (--skip-adp).")
    elif not have_adp:
        _fill_adp_gaps(pool, current_season, scoring_format, teams, reports)

    _fill_missing_byes(pool.values())

    merged = sorted(
        pool.values(),
        key=lambda p: (
            p.adp if p.adp is not None else 9999.0,
            -fantasy_points(p.projections, config.scoring),
            p.position,
            p.name,
        ),
    )

    print()
    print("=" * 60)
    print("STEP 5: Merged board")
    print("=" * 60)
    print(f"\nMerged {len(merged)} players "
          f"({len(merged) - free_players} added on top of the free pull):")
    print(f"  Projections: {sum(1 for p in merged if p.projections)}")
    print(f"  Historical stats: {sum(1 for p in merged if p.historical_stats)}")
    print(f"  ADP: {sum(1 for p in merged if p.adp is not None)}")
    print(f"  Age data: {sum(1 for p in merged if p.age is not None)}")
    print(f"  Injury history: {sum(1 for p in merged if p.injury_history)}")

    return FreeDataResult(players=merged, reports=reports,
                          consensus_players=consensus_players, warnings=warnings)


def collect_all(
    current_season: int = 2025,
    history_seasons: int = 3,
    scoring_format: str = "ppr",
    teams: int = 12,
    skip_sleeper: bool = False,
    skip_adp: bool = False,
    config: Optional[LeagueConfig] = None,
    stats_season: Optional[int] = None,
    include_fftoday: bool = True,
    espn_league_id: Optional[str] = None,
    skip_free_sources: bool = False,
) -> List[Player]:
    """``collect_all_result`` for callers that only want the player list."""
    return collect_all_result(
        current_season=current_season,
        history_seasons=history_seasons,
        scoring_format=scoring_format,
        teams=teams,
        skip_sleeper=skip_sleeper,
        skip_adp=skip_adp,
        config=config,
        stats_season=stats_season,
        include_fftoday=include_fftoday,
        espn_league_id=espn_league_id,
        skip_free_sources=skip_free_sources,
    ).players
