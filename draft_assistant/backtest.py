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
  * ESPN      — needs a league id; not included here.
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
import os
from typing import Callable, Dict, List

import numpy as np
import pandas as pd

from .importers.free_sources import (
    _app_stats_from_nflverse,
    _fetch_nflverse_players,
    _fetch_nflverse_stats_rows,
    _fetch_sleeper_players,
    _fetch_sleeper_projection_rows,
    _norm_name,
    _normalize_position,
    _players_from_sleeper_projection_rows,
)
from .importers.fftoday import fetch_all_fftoday
from .scoring import fantasy_points

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
        with open(path) as fh:
            return json.load(fh)
    data = build()
    with open(path, "w") as fh:
        json.dump(data, fh)
    return data


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
    return _cache(f"actuals_{season}.json", build)


def fftoday_proj(season: int, scoring: dict) -> Dict[str, float]:
    def build():
        return {
            _nkey(p.name, p.position): round(fantasy_points(p.projections, scoring), 2)
            for p in fetch_all_fftoday(season)
        }
    return _cache(f"fftoday_{season}.json", build)


def sleeper_proj(season: int, scoring: dict, players_map: dict) -> Dict[str, float]:
    def build():
        rows = _fetch_sleeper_projection_rows(season)
        players = _players_from_sleeper_projection_rows(rows, players_map, "half-ppr")
        return {
            _nkey(p.name, p.position): round(fantasy_points(p.projections, scoring), 2)
            for p in players if p.position in POSITIONS
        }
    return _cache(f"sleeper_{season}.json", build)


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


def evaluate(seasons: List[int], scoring: dict, include_sleeper: bool = True) -> pd.DataFrame:
    players_map = _fetch_sleeper_players() if include_sleeper else {}
    rows: List[dict] = []
    for season in seasons:
        srcs: Dict[str, Dict[str, float]] = {
            "fftoday": fftoday_proj(season, scoring),
            "prior_year": _pts_only(actuals(season - 1, scoring)),
            "trend_3yr": trend_3yr(season, scoring),
        }
        if include_sleeper:
            srcs["sleeper*"] = sleeper_proj(season, scoring, players_map)
        df = _season_frame(season, scoring, srcs)
        for pos in POSITIONS:
            sub = df[df["pos"] == pos]
            relevant = sub.nlargest(RELEVANT_TOP[pos], "actual")
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
    grid = [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]
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
                    rows.append({"pos": pos, "w": w, "spearman": _spearman(proj_pts, act_pts)})
    df = pd.DataFrame(rows)
    table = df.groupby(["pos", "w"])["spearman"].mean().unstack("w")
    print("=== blend calibration: mean Spearman by projection-weight w (per position) ===")
    print(table.to_string())
    best = {pos: float(table.loc[pos].idxmax()) for pos in table.index}
    print(f"\nOptimal projection weight w per position (rest = recent-production trend):\n  {best}\n")
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


def main(seasons: List[int] = None, include_sleeper: bool = True) -> None:
    scoring = DEFAULT_SCORING
    seasons = seasons or list(range(2019, 2026))
    print(f"Backtesting seasons {seasons[0]}-{seasons[-1]} in half-PPR scoring...\n")
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
