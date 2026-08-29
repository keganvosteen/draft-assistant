"""Backtest: how accurate has each projection source been, historically?

Replays past seasons, scores each source's PRESEASON projections in your league
scoring, and compares to what actually happened (nflverse actuals) to see which
source ranks/predicts players best.

Validity notes (read these — they shape what's a fair comparison):
  * FFToday   — archived per-season PRESEASON projections (clean). Top ~50/pos.
  * Sleeper   — its historical projections endpoint returns IN-SEASON-updated
                numbers (it "projected" rookie Puka Nacua at 87 catches in 2023),
                so it is flagged CONTAMINATED: shown for reference only, NOT a
                fair preseason test (it will look unfairly good).
  * ESPN      — preseason projections read through ESPN's stock league default,
                so no league id and every season back to 2019 (2023 excepted:
                ESPN serves a stub there, ~86 players against ~430). Treated as
                clean: it projected Jonathon Brooks at 129 points in the season
                he tore an ACL and scored 6, and it loses to FFToday at TE —
                neither of which a source revised in-season would do.
Baselines computed from nflverse actuals (clean), as sanity benchmarks any real
projection should beat:
  * prior_year — last season's actual points ("just use last year").
  * trend_3yr  — recency-weighted (decay 0.6) avg of the last 3 seasons' points;
                 mirrors the engine's historical layer in isolation.

Run:  python -m draft_assistant.backtest
Metrics per (source, season, position):
  * spearman — rank correlation of projection vs actual among the
               fantasy-relevant players (the draft-ranking metric).
  * mae      — mean absolute error in league points.
  * coverage — share of relevant players the source even projected.
"""
from __future__ import annotations

import json
import hashlib
import os
from typing import Callable, Dict, List

import numpy as np
import pandas as pd

from .importers.free_sources import (
    _app_stats_from_nflverse,
    _fetch_espn_players,
    _fetch_nflverse_players,
    _fetch_nflverse_stats_rows,
    _fetch_sleeper_players,
    _fetch_sleeper_projection_rows,
    _norm_name,
    _normalize_position,
    _players_from_sleeper_projection_rows,
)
from .importers.fftoday import fetch_all_fftoday
from .projection_archive import archived_projection_points, archived_sources
from .scoring import fantasy_points
from .storage import atomic_write_json

CACHE_DIR = ".backtest_cache"
POSITIONS = ["QB", "RB", "WR", "TE"]
# Fantasy-relevant depth per position (~2-3x starters in a 12-team league).
RELEVANT_TOP = {"QB": 24, "RB": 48, "WR": 60, "TE": 24}
DEFAULT_SCORING = {
    "pass_yd": 0.04, "pass_td": 4, "pass_int": -2,
    "rush_yd": 0.1, "rush_td": 6, "rush_2pt": 2,
    "rec": 0.5, "rec_yd": 0.1, "rec_td": 6, "rec_2pt": 2, "fumbles": -2,
}


def _nkey(name: str, pos: str) -> str:
    return f"{_norm_name(name)}|{pos}"


def _cache(name: str, build: Callable[[], dict]) -> dict:
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = os.path.join(CACHE_DIR, name)
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as fh:
                return json.load(fh)
        except (json.JSONDecodeError, OSError):
            pass
    data = build()
    atomic_write_json(path, data)
    return data


def _scoring_tag(scoring: dict) -> str:
    """Short deterministic cache key for the complete scoring configuration."""
    payload = json.dumps(scoring, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()[:12]


# ── per-(source, season) → {nkey: points} ────────────────────────────────────

def actuals(season: int, scoring: dict) -> Dict[str, list]:
    """{nkey: [pos, actual_points]} for a completed season."""
    def build():
        out: Dict[str, list] = {}
        for row in _fetch_nflverse_stats_rows(season):
            pos = _normalize_position(row.get("position") or "")
            if pos not in POSITIONS:
                continue
            name = row.get("player_display_name") or row.get("player_name")
            if not name:
                continue
            pts = fantasy_points(_app_stats_from_nflverse(row, pos), scoring)
            out[_nkey(name, pos)] = [pos, round(pts, 2)]
        return out
    return _cache(f"actuals_{season}_{_scoring_tag(scoring)}.json", build)


def fftoday_proj(season: int, scoring: dict) -> Dict[str, float]:
    def build():
        return {
            _nkey(p.name, p.position): round(fantasy_points(p.projections, scoring), 2)
            for p in fetch_all_fftoday(season)
        }
    return _cache(f"fftoday_{season}_{_scoring_tag(scoring)}.json", build)


#: ESPN's 2023 projections are a stub -- 86 players against ~430 in every other
#: season, through both a real league and the league default. Calibrating on it
#: would weight a position off a couple of dozen players.
ESPN_SPARSE_SEASONS = {2023}


def espn_proj(season: int, scoring: dict) -> Dict[str, float]:
    """ESPN's preseason projections, read through their stock league default.

    Clean, unlike Sleeper's: ESPN projected Jonathon Brooks at 129 points in
    2024, the season he tore an ACL and scored 6, and it loses to FFToday at TE
    -- neither of which a source revised in-season would do. Its rank
    correlations sit in the same 0.34-0.75 band as FFToday, nowhere near the 0.93
    that marks Sleeper's archive as contaminated.
    """
    def build():
        return {
            _nkey(p.name, p.position): round(fantasy_points(p.projections, scoring), 2)
            for p in _fetch_espn_players(season, None, "half-ppr")
            if p.position in POSITIONS
        }
    return _cache(f"espn_{season}_{_scoring_tag(scoring)}.json", build)


def espn_stats(season: int) -> Dict[str, list]:
    """{nkey: [pos, stat_dict]} — the stat-line form, for weight calibration."""
    def build():
        return {
            _nkey(p.name, p.position): [p.position, p.projections]
            for p in _fetch_espn_players(season, None, "half-ppr")
            if p.position in POSITIONS
        }
    return _cache(f"espnstats_{season}.json", build)


def sleeper_proj(season: int, scoring: dict, players_map: dict) -> Dict[str, float]:
    def build():
        rows = _fetch_sleeper_projection_rows(season)
        players = _players_from_sleeper_projection_rows(rows, players_map, "half-ppr")
        return {
            _nkey(p.name, p.position): round(fantasy_points(p.projections, scoring), 2)
            for p in players if p.position in POSITIONS
        }
    return _cache(f"sleeper_{season}_{_scoring_tag(scoring)}.json", build)


def _pts_only(actual_map: Dict[str, list]) -> Dict[str, float]:
    return {k: v[1] for k, v in actual_map.items()}


def trend_3yr(season: int, scoring: dict, decay: float = 0.6, n: int = 3) -> Dict[str, float]:
    """Recency-weighted average of the prior n seasons' actual points."""
    weighted: Dict[str, float] = {}
    weights: Dict[str, float] = {}
    for i, y in enumerate(range(season - 1, season - 1 - n, -1)):
        try:
            a = _pts_only(actuals(y, scoring))
        except Exception:
            continue
        w = decay ** i
        for k, pts in a.items():
            weighted[k] = weighted.get(k, 0.0) + pts * w
            weights[k] = weights.get(k, 0.0) + w
    return {k: round(weighted[k] / weights[k], 2) for k in weighted if weights[k] > 0}


# ── metrics ───────────────────────────────────────────────────────────────────

def _season_frame(season: int, scoring: dict, sources: Dict[str, Dict[str, float]]) -> pd.DataFrame:
    act = actuals(season, scoring)
    df = pd.DataFrame(
        [{"nkey": k, "pos": v[0], "actual": v[1]} for k, v in act.items()]
    ).set_index("nkey")
    for name, mapping in sources.items():
        df[name] = pd.Series(mapping)
    return df


def _preseason_relevant(
    sub: pd.DataFrame, sources: Dict[str, Dict[str, float]], position: str
) -> pd.DataFrame:
    """Select the evaluation population without looking at season outcomes.

    Average percentile rank across the clean preseason forecasts/baselines, then
    keep the configured depth. Selecting the top actual scorers used hindsight,
    excluded preseason misses, and made every source look better than it was.
    """
    clean_sources = [name for name in sources if not name.endswith("*")]
    rank_columns = [sub[name].rank(pct=True) for name in clean_sources if name in sub]
    if not rank_columns:
        return sub.iloc[0:0]
    composite = pd.concat(rank_columns, axis=1).mean(axis=1, skipna=True)
    keys = composite.nlargest(RELEVANT_TOP[position]).index
    return sub.loc[keys]


def archived_proj(season: int, scoring: dict) -> Dict[str, Dict[str, float]]:
    """Every source this app banked before ``season`` kicked off.

    These are the only clean preseason numbers we will ever have for Sleeper and
    ESPN, whose own archives are either revised in-season or absent entirely.
    Empty until a pull has run during a preseason — see projection_archive.py.
    Named ``<source>@archive`` so they never collide with a live-fetched source.
    """
    return {
        f"{source}@archive": archived_projection_points(season, source, scoring)
        for source in archived_sources(season)
    }


def evaluate(seasons: List[int], scoring: dict, include_sleeper: bool = True) -> pd.DataFrame:
    players_map = _fetch_sleeper_players() if include_sleeper else {}
    rows: List[dict] = []
    for season in seasons:
        srcs: Dict[str, Dict[str, float]] = {
            "fftoday": fftoday_proj(season, scoring),
            "prior_year": _pts_only(actuals(season - 1, scoring)),
            "trend_3yr": trend_3yr(season, scoring),
        }
        if season not in ESPN_SPARSE_SEASONS:
            try:
                srcs["espn"] = espn_proj(season, scoring)
            except Exception as exc:  # pragma: no cover - network
                print(f"  espn {season}: unavailable ({exc})")
        srcs.update({k: v for k, v in archived_proj(season, scoring).items() if v})
        if include_sleeper:
            srcs["sleeper*"] = sleeper_proj(season, scoring, players_map)
        df = _season_frame(season, scoring, srcs)
        for pos in POSITIONS:
            sub = df[df["pos"] == pos]
            relevant = _preseason_relevant(sub, srcs, pos)
            if len(relevant) < 5:
                continue
            for src in srcs:
                pair = relevant[[src, "actual"]].dropna()
                cov = len(pair) / len(relevant)
                # Spearman = Pearson on ranks (avoids the scipy dependency that
                # pandas' method="spearman" requires).
                spearman = (
                    pair[src].rank().corr(pair["actual"].rank())
                    if len(pair) >= 5 else np.nan
                )
                mae = (pair[src] - pair["actual"]).abs().mean() if len(pair) else np.nan
                rows.append({
                    "season": season, "pos": pos, "source": src,
                    "spearman": spearman, "mae": mae, "coverage": cov,
                })
    return pd.DataFrame(rows)


# ── stat-level data (for blend calibration + grading the engine's adjustments) ─
# These operate on STAT lines, not points, so calibration is scoring-agnostic
# (the owner runs two leagues with different rules).

SCORINGS = {
    "standard": {**DEFAULT_SCORING, "rec": 0.0},
    "half": {**DEFAULT_SCORING, "rec": 0.5},
    "ppr": {**DEFAULT_SCORING, "rec": 1.0},
}


def actual_stats(season: int) -> Dict[str, list]:
    """{nkey: [pos, stat_dict]} of a completed season's actual stat lines."""
    def build():
        out: Dict[str, list] = {}
        for row in _fetch_nflverse_stats_rows(season):
            pos = _normalize_position(row.get("position") or "")
            if pos not in POSITIONS:
                continue
            name = row.get("player_display_name") or row.get("player_name")
            if not name:
                continue
            out[_nkey(name, pos)] = [pos, _app_stats_from_nflverse(row, pos)]
        return out
    return _cache(f"actualstats_{season}.json", build)


def fftoday_stats(season: int) -> Dict[str, list]:
    def build():
        return {
            _nkey(p.name, p.position): [p.position, p.projections]
            for p in fetch_all_fftoday(season)
        }
    return _cache(f"fftodaystats_{season}.json", build)


def age_map(season: int) -> Dict[str, int]:
    """{nkey: age at `season`} derived from nflverse birth dates."""
    def build():
        out: Dict[str, int] = {}
        for row in _fetch_nflverse_players().values():
            name = row.get("display_name") or row.get("player_name")
            pos = _normalize_position(row.get("position") or "")
            bd = row.get("birth_date")
            if not name or pos not in POSITIONS or not bd:
                continue
            try:
                out[_nkey(name, pos)] = season - int(str(bd)[:4])
            except ValueError:
                continue
        return out
    return _cache(f"agemap_{season}.json", build)


def trend_stats(season: int, decay: float = 0.6, n: int = 3) -> Dict[str, Dict[str, float]]:
    """Per-stat recency-weighted trend from the prior n seasons' actual stats."""
    acc: Dict[str, Dict[str, list]] = {}
    for i, y in enumerate(range(season - 1, season - 1 - n, -1)):
        try:
            a = actual_stats(y)
        except Exception:
            continue
        w = decay ** i
        for k, (_pos, stats) in a.items():
            d = acc.setdefault(k, {})
            for stat, val in stats.items():
                pair = d.setdefault(stat, [0.0, 0.0])
                pair[0] += val * w
                pair[1] += w
    return {k: {s: ws / wt for s, (ws, wt) in d.items() if wt > 0} for k, d in acc.items()}


def _spearman(a: List[float], b: List[float]) -> float:
    return float(pd.Series(a).rank().corr(pd.Series(b).rank()))


def calibrate_blend(seasons: List[int]) -> Dict[str, float]:
    """Sweep the projection/history blend weight per position.

    blended_stat = w*FFToday + (1-w)*trend  (w=1 → all projection, 0 → all history).
    Accuracy = mean Spearman across seasons AND scorings (standard/half/ppr), so
    the chosen weights are league-rule-agnostic. Returns {pos: best_w}.
    """
    grid = [i / 10 for i in range(11)]
    rows: List[dict] = []
    for season in seasons:
        ff, tr, act = fftoday_stats(season), trend_stats(season), actual_stats(season)
        for pos in POSITIONS:
            keys = [k for k, (p, _s) in ff.items() if p == pos and k in tr and k in act]
            if len(keys) < 8:
                continue
            for w in grid:
                for sc_name, sc in SCORINGS.items():
                    proj_pts, act_pts = [], []
                    for k in keys:
                        ffs, trs = ff[k][1], tr[k]
                        stats = set(ffs) | set(trs)
                        blended = {s: w * ffs.get(s, 0.0) + (1 - w) * trs.get(s, 0.0) for s in stats}
                        proj_pts.append(fantasy_points(blended, sc))
                        act_pts.append(fantasy_points(act[k][1], sc))
                    rows.append({
                        "season": season, "pos": pos, "scoring": sc_name,
                        "w": w, "spearman": _spearman(proj_pts, act_pts),
                    })
    df = pd.DataFrame(rows)
    if df.empty:
        return {}
    table = df.groupby(["pos", "w"])["spearman"].mean().unstack("w")
    print("=== blend calibration: mean Spearman by projection-weight w (per position) ===")
    print(table.to_string())
    best = {pos: float(table.loc[pos].idxmax()) for pos in table.index}
    print(f"\nOptimal projection weight w per position (rest = recent-production trend):\n  {best}\n")

    # Leave one season out: select w on every other season, then score only the
    # held-out season. This is a validation diagnostic, not another opportunity
    # to tune against the same outcomes.
    validation: List[dict] = []
    unique_seasons = sorted(df["season"].unique())
    if len(unique_seasons) >= 2:
        for held_out in unique_seasons:
            training = df[df["season"] != held_out]
            held = df[df["season"] == held_out]
            for pos in sorted(df["pos"].unique()):
                train_pos = training[training["pos"] == pos]
                if train_pos.empty:
                    continue
                chosen = float(train_pos.groupby("w")["spearman"].mean().idxmax())
                score = held[(held["pos"] == pos) & (held["w"] == chosen)]["spearman"].mean()
                validation.append({
                    "season": held_out, "pos": pos,
                    "chosen_w": chosen, "spearman": score,
                })
    if validation:
        validation_df = pd.DataFrame(validation)
        print("=== leave-one-season-out validation ===")
        print(validation_df.groupby("pos")[["chosen_w", "spearman"]].mean().to_string())
        print()
    return best


def calibrate_source_weights(seasons: List[int]) -> Dict[str, float]:
    """Sweep ESPN's share of the projection consensus, per position.

    consensus_stat = w*ESPN + (1-w)*FFToday  (w=1 -> all ESPN, 0 -> all FFToday).
    Blends STAT LINES and scores across all three scorings, exactly like
    :func:`calibrate_blend`, so the weights stay league-rule-agnostic. Only
    players both sources projected are used: this measures whose number to trust
    when they disagree, not who covers more players.

    Returns {pos: best_w}. Read it beside the leave-one-season-out table -- a
    position where the two sources are tied should be left at 0.5 rather than
    handed whichever way the mean happened to fall.
    """
    grid = [i / 10 for i in range(11)]
    usable = [s for s in seasons if s not in ESPN_SPARSE_SEASONS]
    rows: List[dict] = []
    for season in usable:
        es, ff, act = espn_stats(season), fftoday_stats(season), actual_stats(season)
        for pos in POSITIONS:
            keys = [k for k, (p, _s) in ff.items()
                    if p == pos and k in es and k in act]
            if len(keys) < 8:
                continue
            for w in grid:
                for sc_name, sc in SCORINGS.items():
                    proj_pts, act_pts = [], []
                    for k in keys:
                        e, f = es[k][1], ff[k][1]
                        stats = set(e) | set(f)
                        blended = {s: w * e.get(s, 0.0) + (1 - w) * f.get(s, 0.0)
                                   for s in stats}
                        proj_pts.append(fantasy_points(blended, sc))
                        act_pts.append(fantasy_points(act[k][1], sc))
                    rows.append({
                        "season": season, "pos": pos, "scoring": sc_name,
                        "w": w, "spearman": _spearman(proj_pts, act_pts),
                    })
    df = pd.DataFrame(rows)
    if df.empty:
        return {}
    table = df.groupby(["pos", "w"])["spearman"].mean().unstack("w")
    print("=== source calibration: mean Spearman by ESPN weight w (per position) ===")
    print(f"seasons: {', '.join(str(s) for s in usable)}")
    print(table.to_string())
    best = {pos: float(table.loc[pos].idxmax()) for pos in table.index}
    print(f"\nOptimal ESPN weight w per position (rest = FFToday):\n  {best}\n")

    # Same discipline as calibrate_blend: choose w on every other season, then
    # score only the held-out one. A weight that only wins in-sample is noise.
    validation: List[dict] = []
    unique_seasons = sorted(df["season"].unique())
    if len(unique_seasons) >= 2:
        for held_out in unique_seasons:
            training = df[df["season"] != held_out]
            held = df[df["season"] == held_out]
            for pos in sorted(df["pos"].unique()):
                train_pos = training[training["pos"] == pos]
                if train_pos.empty:
                    continue
                chosen = float(train_pos.groupby("w")["spearman"].mean().idxmax())
                picked = held[(held["pos"] == pos) & (held["w"] == chosen)]["spearman"].mean()
                even = held[(held["pos"] == pos) & (held["w"] == 0.5)]["spearman"].mean()
                validation.append({
                    "season": held_out, "pos": pos, "chosen_w": chosen,
                    "spearman": picked, "vs_even": picked - even,
                })
    if validation:
        vdf = pd.DataFrame(validation)
        print("=== leave-one-season-out validation (vs_even > 0 means weighting beat 50/50) ===")
        print(vdf.groupby("pos")[["chosen_w", "spearman", "vs_even"]].mean().to_string())
        print("\nper-season held-out gain over 50/50:")
        print(vdf.pivot_table(index="season", columns="pos", values="vs_even").to_string())
        print()
    return best


def grade_adjusted(seasons: List[int]) -> None:
    """Does the engine's adjust_projections (history blend + age + team) beat raw?

    Uses FFToday (clean) as the base projection, real prior-season actuals as
    history, and nflverse ages. Reports raw vs adjusted rank accuracy.
    """
    from .historical import adjust_projections
    from .models import Player
    rows: List[dict] = []
    for season in seasons:
        ff, act, ages = fftoday_stats(season), actual_stats(season), age_map(season)
        h1, h2 = actual_stats(season - 1), actual_stats(season - 2)
        for pos in POSITIONS:
            keys = [k for k, (p, _s) in ff.items() if p == pos and k in act]
            if len(keys) < 8:
                continue
            raw_pts, adj_pts, act_pts = [], [], []
            for k in keys:
                hist = {}
                if k in h1:
                    hist[season - 1] = h1[k][1]
                if k in h2:
                    hist[season - 2] = h2[k][1]
                player = Player(id=k, name=k.rsplit("|", 1)[0], position=pos,
                                projections=dict(ff[k][1]), historical_stats=hist, age=ages.get(k))
                adj = adjust_projections(player, SCORINGS["half"])
                raw_pts.append(fantasy_points(ff[k][1], SCORINGS["half"]))
                adj_pts.append(fantasy_points(adj, SCORINGS["half"]))
                act_pts.append(fantasy_points(act[k][1], SCORINGS["half"]))
            rows.append({"pos": pos, "raw": _spearman(raw_pts, act_pts),
                         "adjusted": _spearman(adj_pts, act_pts)})
    df = pd.DataFrame(rows).groupby("pos")[["raw", "adjusted"]].mean()
    df["delta"] = df["adjusted"] - df["raw"]
    print("=== engine adjustment grade: raw FFToday vs adjust_projections (half-PPR) ===")
    print(df.to_string())
    print(f"\nOverall: raw={df['raw'].mean():.3f}  adjusted={df['adjusted'].mean():.3f}  "
          f"delta={df['delta'].mean():+.3f}  (positive = the adjustments help)\n")


def report_archive(seasons: List[int]) -> None:
    """What clean preseason data we have banked, and what is still missing.

    Sleeper supplies most of the board and cannot be graded from its own
    history, so until these snapshots accumulate there is no honest way to show
    that a change to the projection blend helped. Printing the gap keeps that
    visible instead of letting an unmeasurable pipeline look measured.
    """
    from datetime import date

    from .projection_archive import is_preseason

    banked = {s: archived_sources(s) for s in seasons}
    banked = {s: v for s, v in banked.items() if v}
    print("=== archived preseason snapshots (clean, gradeable) ===")
    if not banked:
        print("  none yet — no pull has run during a preseason window.")
    for season, sources in sorted(banked.items()):
        detail = ", ".join(f"{src} ({n})" for src, n in sorted(sources.items()))
        print(f"  {season}: {detail}")

    current = date.today().year
    if not archived_sources(current) and is_preseason(current):
        print(f"\n  ** {current} is still preseason and nothing is banked yet. **")
        print("     Run a data pull before September 1 to capture it; after that")
        print("     this season's clean preseason record is gone for good.")
    print()


def main(seasons: List[int] = None, include_sleeper: bool = True) -> None:
    scoring = DEFAULT_SCORING
    seasons = seasons or list(range(2019, 2026))
    print(f"Backtesting seasons {seasons[0]}-{seasons[-1]} in half-PPR scoring...\n")
    report_archive(seasons + [seasons[-1] + 1])
    res = evaluate(seasons, scoring, include_sleeper=include_sleeper)

    pd.set_option("display.float_format", lambda x: f"{x:.3f}")
    overall = (
        res.groupby("source")[["spearman", "mae", "coverage"]]
        .mean()
        .sort_values("spearman", ascending=False)
    )
    print("=== OVERALL (mean across seasons x positions; higher spearman / lower mae = better) ===")
    print(overall.to_string())
    print("\nNote: sources marked * use contaminated historical data — see module docstring.\n")

    print("=== rank accuracy (spearman) by position, per source ===")
    piv = res.pivot_table(index="source", columns="pos", values="spearman", aggfunc="mean")
    print(piv.to_string())

    print("\n=== by season (overall spearman, relevant players only) ===")
    bys = res.pivot_table(index="season", columns="source", values="spearman", aggfunc="mean")
    print(bys.to_string())


if __name__ == "__main__":
    main()
