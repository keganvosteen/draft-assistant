from __future__ import annotations

import csv
import io
import json
import re
import statistics
from dataclasses import dataclass
from datetime import date
from typing import Dict, Iterable, List, Optional, Tuple
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from ..models import LeagueConfig, Player
from ..scoring import fantasy_points
from .fftoday import fetch_all_fftoday


SLEEPER_BASE = "https://api.sleeper.app/v1"
FFC_ADP_BASE = "https://fantasyfootballcalculator.com/api/v1/adp"
NFLVERSE_RELEASE_API = "https://api.github.com/repos/nflverse/nflverse-data/releases/tags/{tag}"

POSITIONS = {"QB", "RB", "WR", "TE", "K", "DST", "DEF"}
APP_STAT_KEYS = {
    "pass_yd", "pass_td", "pass_int", "pass_2pt",
    "rush_yd", "rush_td", "rush_2pt",
    "rec", "rec_yd", "rec_td", "rec_2pt",
    "fumbles", "fumbles_total", "sack_taken",
    "pat_made", "fg_miss", "fg_0_39", "fg_40_49", "fg_50_59", "fg_60_plus",
    "krt_td", "prt_td", "int_ret_td", "fum_ret_td", "blk_kick_ret_td",
    "two_pt_ret", "one_pt_safety", "sack", "blk_kick", "def_int",
    "fumble_recovery", "safety",
}
NFL_TEAM_NAMES = {
    "ARI": "Arizona Cardinals",
    "ATL": "Atlanta Falcons",
    "BAL": "Baltimore Ravens",
    "BUF": "Buffalo Bills",
    "CAR": "Carolina Panthers",
    "CHI": "Chicago Bears",
    "CIN": "Cincinnati Bengals",
    "CLE": "Cleveland Browns",
    "DAL": "Dallas Cowboys",
    "DEN": "Denver Broncos",
    "DET": "Detroit Lions",
    "GB": "Green Bay Packers",
    "HOU": "Houston Texans",
    "IND": "Indianapolis Colts",
    "JAX": "Jacksonville Jaguars",
    "KC": "Kansas City Chiefs",
    "LAC": "Los Angeles Chargers",
    "LAR": "Los Angeles Rams",
    "LV": "Las Vegas Raiders",
    "MIA": "Miami Dolphins",
    "MIN": "Minnesota Vikings",
    "NE": "New England Patriots",
    "NO": "New Orleans Saints",
    "NYG": "New York Giants",
    "NYJ": "New York Jets",
    "PHI": "Philadelphia Eagles",
    "PIT": "Pittsburgh Steelers",
    "SEA": "Seattle Seahawks",
    "SF": "San Francisco 49ers",
    "TB": "Tampa Bay Buccaneers",
    "TEN": "Tennessee Titans",
    "WAS": "Washington Commanders",
}


@dataclass
class SourceReport:
    source: str
    records: int = 0
    ok: bool = True
    detail: str = ""


@dataclass
class FreeDataResult:
    players: List[Player]
    reports: List[SourceReport]


def default_projection_season(today: Optional[date] = None) -> int:
    today = today or date.today()
    return today.year


def default_stats_season(today: Optional[date] = None) -> int:
    today = today or date.today()
    return today.year - 1


def scoring_format(config: LeagueConfig) -> str:
    rec_points = float((config.scoring or {}).get("rec", 0.0))
    if rec_points >= 0.75:
        return "ppr"
    if rec_points >= 0.25:
        return "half-ppr"
    return "standard"


def pull_free_data(
    config: LeagueConfig,
    season: Optional[int] = None,
    stats_season: Optional[int] = None,
    teams: Optional[int] = None,
    adp_format: Optional[str] = None,
    include_fftoday: bool = True,
    espn_league_id: Optional[str] = None,
    history_seasons: Optional[int] = 1,
) -> FreeDataResult:
    season = season or default_projection_season()
    stats_season = stats_season or default_stats_season()
    history_seasons = max(1, int(history_seasons or 1))
    teams = int(teams or config.teams)
    adp_format = adp_format or scoring_format(config)

    reports: List[SourceReport] = []
    merged: Dict[str, Player] = {}
    proj_samples: Dict[str, List[Dict[str, float]]] = {}
    sleeper_players: Dict[str, dict] = {}
    nflverse_players: Dict[str, dict] = {}

    try:
        sleeper_players = _fetch_sleeper_players()
        reports.append(SourceReport("Sleeper players", len(sleeper_players)))
    except Exception as exc:
        reports.append(SourceReport("Sleeper players", ok=False, detail=str(exc)))

    try:
        sleeper_projection_rows = _fetch_sleeper_projection_rows(season)
        sleeper_projection_players = _players_from_sleeper_projection_rows(
            sleeper_projection_rows,
            sleeper_players,
            adp_format,
        )
        _merge_many(merged, sleeper_projection_players, "sleeper_projections", proj_samples)
        reports.append(SourceReport("Sleeper projections", len(sleeper_projection_players), detail=str(season)))
    except Exception as exc:
        reports.append(SourceReport("Sleeper projections", ok=False, detail=str(exc)))

    try:
        ffc_players, ffc_year = _fetch_ffc_adp_players(adp_format, teams, season)
        _merge_many(merged, ffc_players, "fantasy_football_calculator")
        reports.append(SourceReport("Fantasy Football Calculator ADP", len(ffc_players), detail=f"{ffc_year} {adp_format}"))
    except Exception as exc:
        reports.append(SourceReport("Fantasy Football Calculator ADP", ok=False, detail=str(exc)))

    try:
        nflverse_players = _fetch_nflverse_players()
        _enrich_from_nflverse_players(merged, nflverse_players)
        reports.append(SourceReport("nflverse players", len(nflverse_players)))
    except Exception as exc:
        reports.append(SourceReport("nflverse players", ok=False, detail=str(exc)))

    # Pull each requested stats season; _merge_player unions historical_stats
    # per player, so one pull can carry a multi-year corpus.
    for s in range(stats_season - history_seasons + 1, stats_season + 1):
        try:
            nflverse_stats_rows = _fetch_nflverse_stats_rows(s)
            nflverse_stat_players = _players_from_nflverse_stats(nflverse_stats_rows, nflverse_players, s)
            _merge_many(merged, nflverse_stat_players, f"nflverse_stats_{s}")
            reports.append(SourceReport("nflverse season stats", len(nflverse_stat_players), detail=str(s)))
        except Exception as exc:
            reports.append(SourceReport("nflverse season stats", ok=False, detail=f"{s}: {exc}"))

    if include_fftoday:
        try:
            fftoday_players = fetch_all_fftoday(season)
            _merge_many(merged, fftoday_players, "fftoday", proj_samples)
            reports.append(SourceReport("FFToday projections", len(fftoday_players), detail=str(season)))
        except Exception as exc:
            reports.append(SourceReport("FFToday projections", ok=False, detail=str(exc)))

    if espn_league_id:
        try:
            espn_players = _fetch_espn_players(season, espn_league_id, adp_format)
            _merge_many(merged, espn_players, "espn", proj_samples)
            reports.append(SourceReport("ESPN Fantasy API", len(espn_players), detail=str(espn_league_id)))
        except Exception as exc:
            reports.append(SourceReport("ESPN Fantasy API", ok=False, detail=str(exc)))
    else:
        reports.append(SourceReport("ESPN Fantasy API", 0, ok=False, detail="skipped; pass --espn-league-id for a public league"))

    # Combine projection sources by per-stat median (scoring-agnostic). For a
    # player only one source projected, that source stands; where two or more
    # overlap (e.g. Sleeper + FFToday), each stat becomes their consensus.
    for key, player in merged.items():
        samples = proj_samples.get(key)
        if samples and len(samples) > 1:
            player.projections = _consensus_projection(samples)
            player.metadata["projection_source"] = "consensus"
            player.metadata["projection_sources_n"] = len(samples)

    _fill_missing_byes(merged.values())

    players = sorted(
        merged.values(),
        key=lambda p: (
            p.adp if p.adp is not None else 9999.0,
            -fantasy_points(p.projections, config.scoring),
            p.position,
            p.name,
        ),
    )
    return FreeDataResult(players=players, reports=reports)


def merge_historical_into(new_players: List[Player], existing_players: Iterable[Player]) -> List[Player]:
    """Carry forward prior pulls' historical seasons onto a fresh pull.

    The new pull defines the current player pool, projections, and ADP; only
    each player's ``historical_stats`` are unioned from what was saved before,
    so repeated single-season pulls accumulate a multi-year corpus instead of
    overwriting it. Players no longer in the latest pull are dropped (they're
    not draftable), and the new pull's value for a season always wins.
    """
    existing_by_key: Dict[str, Player] = {}
    for player in existing_players:
        existing_by_key.setdefault(_merge_key(player), player)
    for player in new_players:
        prior = existing_by_key.get(_merge_key(player))
        if not prior:
            continue
        for season, season_stats in prior.historical_stats.items():
            player.historical_stats.setdefault(season, season_stats)
    return new_players


def _fill_missing_byes(players: Iterable[Player]) -> None:
    """Spread known bye weeks across teammates.

    Only some sources carry byes per player; every teammate shares the same
    one, so derive a team->bye map and fill the gaps. Without this the
    engine's bye-week penalties only see the handful of players whose source
    happened to include a bye.
    """
    players = list(players)
    team_byes: Dict[str, int] = {}
    for player in players:
        if player.team and player.bye_week and player.team not in team_byes:
            team_byes[player.team] = player.bye_week
    for player in players:
        if player.team and not player.bye_week:
            bye = team_byes.get(player.team)
            if bye:
                player.bye_week = bye


def _fetch_json(url: str, timeout: int = 30) -> object:
    req = Request(url, headers={
        "User-Agent": "draft-assistant/1.0 (+https://github.com/)",
        "Accept": "application/json,text/plain,*/*",
    })
    with urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _fetch_text(url: str, timeout: int = 45) -> str:
    req = Request(url, headers={
        "User-Agent": "draft-assistant/1.0 (+https://github.com/)",
        "Accept": "text/csv,text/plain,*/*",
    })
    with urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
    return raw.decode("utf-8-sig", errors="replace")


def _fetch_sleeper_players() -> Dict[str, dict]:
    data = _fetch_json(f"{SLEEPER_BASE}/players/nfl", timeout=45)
    if not isinstance(data, dict):
        return {}
    return {str(k): v for k, v in data.items() if isinstance(v, dict)}


def _fetch_sleeper_projection_rows(season: int) -> Dict[str, dict]:
    data = _fetch_json(f"{SLEEPER_BASE}/projections/nfl/regular/{season}", timeout=45)
    if not isinstance(data, dict):
        return {}
    return {str(k): v for k, v in data.items() if isinstance(v, dict)}


def _players_from_sleeper_projection_rows(
    rows: Dict[str, dict],
    sleeper_players: Dict[str, dict],
    adp_format: str,
) -> List[Player]:
    players: List[Player] = []
    for player_id, row in rows.items():
        meta = sleeper_players.get(player_id, {})
        position = _normalize_position(meta.get("position") or row.get("position") or "")
        if position not in {"QB", "RB", "WR", "TE", "K", "DST"}:
            continue
        projections = _app_stats_from_sleeper(row, position)
        adp = _best_sleeper_adp(row, adp_format)
        if not _has_projection_value(projections) and adp is None:
            continue
        team = meta.get("team") or (player_id if position == "DST" else None)
        name = _player_name(meta, player_id, position, team)
        players.append(Player(
            id=f"sleeper:{player_id}",
            name=name,
            position=position,
            team=team,
            bye_week=_to_int(meta.get("bye_week")),
            adp=adp,
            projections=projections,
            age=_to_int(meta.get("age")),
            experience=_to_int(meta.get("years_exp")),
            metadata=_clean_metadata({
                "sleeper_id": player_id,
                "gsis_id": meta.get("gsis_id"),
                "espn_id": meta.get("espn_id"),
                "age": meta.get("age"),
                "injury_status": meta.get("injury_status"),
                "status": meta.get("status"),
                "years_exp": meta.get("years_exp"),
                "projection_source": "Sleeper",
                "sources": ["sleeper_players", "sleeper_projections"],
            }),
        ))
    return players


def _fetch_ffc_adp_players(adp_format: str, teams: int, season: int) -> Tuple[List[Player], int]:
    errors: List[str] = []
    # Fantasy Football Calculator only publishes ADP for up to 14-team leagues,
    # so cap the request for larger leagues (16/18/20) to still get a board.
    ffc_teams = min(14, int(teams or 12))
    for year in _adp_year_candidates(season):
        query = urlencode({"teams": ffc_teams, "year": year})
        url = f"{FFC_ADP_BASE}/{adp_format}?{query}"
        data = _fetch_json(url, timeout=30)
        if not isinstance(data, dict):
            errors.append(f"{year}: unexpected response")
            continue
        rows = data.get("players") or []
        if rows:
            return [_player_from_ffc_row(row, adp_format, year) for row in rows if isinstance(row, dict)], year
        errors.append(f"{year}: {data.get('errors') or data.get('status') or 'no players'}")
    raise RuntimeError("; ".join(errors))


def _adp_year_candidates(season: int) -> Iterable[int]:
    seen = set()
    for year in [season, season - 1, season + 1, default_projection_season()]:
        if year not in seen:
            seen.add(year)
            yield year


def _player_from_ffc_row(row: dict, adp_format: str, year: int) -> Player:
    position = _normalize_position(row.get("position") or "")
    name = str(row.get("name") or "").strip()
    team = str(row.get("team") or "").strip() or None
    bye = _to_int(row.get("bye"))
    return Player(
        id=f"ffc:{row.get('player_id') or name}",
        name=name,
        position=position,
        team=team,
        bye_week=bye,
        adp=_valid_adp(row.get("adp")),
        projections={},
        metadata=_clean_metadata({
            "ffc_player_id": row.get("player_id"),
            "adp_format": adp_format,
            "adp_year": year,
            "times_drafted": row.get("times_drafted"),
            "adp_high": row.get("high"),
            "adp_low": row.get("low"),
            "adp_stdev": row.get("stdev"),
            "sources": ["fantasy_football_calculator"],
        }),
    )


def _fetch_nflverse_players() -> Dict[str, dict]:
    url = _github_release_asset_url("players", "players.csv")
    rows = _read_csv_url(url)
    out: Dict[str, dict] = {}
    for row in rows:
        gsis_id = (row.get("gsis_id") or "").strip()
        if gsis_id:
            out[gsis_id] = row
    return out


def _fetch_nflverse_stats_rows(season: int) -> List[dict]:
    url = _github_release_asset_url("stats_player", f"stats_player_reg_{season}.csv")
    return _read_csv_url(url)


def _players_from_nflverse_stats(rows: List[dict], player_meta: Dict[str, dict], season: int) -> List[Player]:
    """Build players carrying last season's actuals as historical_stats.

    Actuals are deliberately NOT used as projections — the engine's historical
    layer blends them with real projections (and ages the trend forward), and
    falls back to the trend alone for players with no published projection.
    """
    players: List[Player] = []
    for row in rows:
        position = _normalize_position(row.get("position") or "")
        if position not in {"QB", "RB", "WR", "TE", "K"}:
            continue
        season_stats = _app_stats_from_nflverse(row, position)
        if not _has_projection_value(season_stats):
            continue
        player_id = row.get("player_id") or row.get("gsis_id") or row.get("player_display_name")
        meta = player_meta.get(str(player_id), {})
        players.append(Player(
            id=f"nflverse:{player_id}",
            name=row.get("player_display_name") or meta.get("display_name") or row.get("player_name") or str(player_id),
            position=position,
            team=row.get("recent_team") or meta.get("latest_team") or None,
            projections={},
            age=_age_from_birth_date(meta.get("birth_date")),
            experience=_to_int(meta.get("years_of_experience")),
            historical_stats={season: season_stats},
            metadata=_clean_metadata({
                "gsis_id": player_id,
                "historical_stats_season": season,
                "birth_date": meta.get("birth_date"),
                "age": _age_from_birth_date(meta.get("birth_date")),
                "status": meta.get("status"),
                "years_of_experience": meta.get("years_of_experience"),
                "draft_year": meta.get("draft_year"),
                "draft_round": meta.get("draft_round"),
                "draft_pick": meta.get("draft_pick"),
                "sources": ["nflverse_stats"],
            }),
        ))
    return players


def _enrich_from_nflverse_players(players: Dict[str, Player], nflverse_players: Dict[str, dict]) -> None:
    by_gsis = {
        str(p.metadata.get("gsis_id")): p
        for p in players.values()
        if p.metadata.get("gsis_id")
    }
    for gsis_id, row in nflverse_players.items():
        player = by_gsis.get(gsis_id)
        if not player:
            continue
        if not player.team and row.get("latest_team"):
            player.team = row.get("latest_team")
        if player.age is None:
            player.age = _age_from_birth_date(row.get("birth_date"))
        if player.experience is None:
            player.experience = _to_int(row.get("years_of_experience"))
        player.metadata.update(_clean_metadata({
            "birth_date": row.get("birth_date"),
            "age": player.metadata.get("age") or _age_from_birth_date(row.get("birth_date")),
            "nflverse_position": row.get("position"),
            "status": player.metadata.get("status") or row.get("status"),
            "years_of_experience": row.get("years_of_experience"),
            "draft_year": row.get("draft_year"),
            "draft_round": row.get("draft_round"),
            "draft_pick": row.get("draft_pick"),
        }))
        _add_source(player, "nflverse_players")


def _fetch_espn_players(season: int, league_id: str, adp_format: str) -> List[Player]:
    query = urlencode({"view": ["kona_player_info", "mDraftDetail"]}, doseq=True)
    url = f"https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/{season}/segments/0/leagues/{league_id}?{query}"
    data = _fetch_json(url, timeout=45)
    players: List[Player] = []
    for row in _walk_espn_players(data):
        player = row.get("player", {}) if isinstance(row, dict) else {}
        position = _espn_position(player.get("defaultPositionId") or player.get("eligibleSlots"))
        if position not in {"QB", "RB", "WR", "TE", "K", "DST"}:
            continue
        stats = _espn_projection_stats(player)
        # Only overall draft rank is comparable to ADP; positionalRanking
        # (e.g. WR12) would poison the ADP merge, which keeps the minimum.
        adp = _valid_adp(_nested_get(row, ["draftRanksByRankType", "STANDARD", "rank"]))
        players.append(Player(
            id=f"espn:{player.get('id') or player.get('fullName')}",
            name=player.get("fullName") or player.get("name") or "",
            position=position,
            team=_espn_team(player.get("proTeamId")),
            adp=adp,
            projections=stats,
            metadata=_clean_metadata({
                "espn_id": player.get("id"),
                "injury_status": player.get("injuryStatus"),
                "sources": ["espn"],
            }),
        ))
    return [p for p in players if p.name and (_has_projection_value(p.projections) or p.adp is not None)]


def _walk_espn_players(data: object) -> Iterable[dict]:
    if isinstance(data, dict):
        if isinstance(data.get("players"), list):
            for row in data["players"]:
                if isinstance(row, dict):
                    yield row
        for value in data.values():
            yield from _walk_espn_players(value)
    elif isinstance(data, list):
        for item in data:
            yield from _walk_espn_players(item)


def _espn_projection_stats(player: dict) -> Dict[str, float]:
    out: Dict[str, float] = {}
    for stat_row in player.get("stats") or []:
        if not isinstance(stat_row, dict):
            continue
        if stat_row.get("statSourceId") != 1:
            continue
        applied = stat_row.get("appliedStats") or {}
        if isinstance(applied, dict):
            for key, value in applied.items():
                if key in APP_STAT_KEYS:
                    out[key] = _to_float(value)
    return out


def _github_release_asset_url(tag: str, asset_name: str) -> str:
    release = _fetch_json(NFLVERSE_RELEASE_API.format(tag=tag), timeout=30)
    if not isinstance(release, dict):
        raise RuntimeError(f"no release metadata for {tag}")
    for asset in release.get("assets", []):
        if asset.get("name") == asset_name:
            return str(asset.get("browser_download_url"))
    raise RuntimeError(f"asset not found: {tag}/{asset_name}")


def _read_csv_url(url: str) -> List[dict]:
    text = _fetch_text(url)
    return list(csv.DictReader(io.StringIO(text)))


def _app_stats_from_sleeper(row: dict, position: str) -> Dict[str, float]:
    stats = _copy_stats(row, APP_STAT_KEYS)
    # Yahoo scores "Fumbles" (any fumble) and "Fumbles Lost" separately, so keep
    # both: `fumbles` = lost (what most formats penalize), `fumbles_total` = all.
    stats["fumbles"] = _first_float(row, ["fum_lost", "fumbles_lost"])
    stats["fumbles_total"] = _first_float(row, ["fum", "fumbles"])
    stats["pat_made"] = _first_float(row, ["pat_made", "xpm"])
    stats["fg_0_39"] = _first_float(row, ["fg_0_39", "fgm_0_19"]) + _first_float(row, ["fgm_20_29"]) + _first_float(row, ["fgm_30_39"])
    stats["fg_40_49"] = _first_float(row, ["fg_40_49", "fgm_40_49"])
    stats["fg_50_59"] = _first_float(row, ["fg_50_59", "fgm_50_59", "fgm_50p"])
    stats["fg_60_plus"] = _first_float(row, ["fg_60_plus", "fgm_60p"])
    stats["fg_miss"] = _first_float(row, ["fg_miss", "fgmiss", "fgmiss_0_19"]) + _first_float(row, ["fgmiss_20_29"]) + _first_float(row, ["fgmiss_30_39"]) + _first_float(row, ["fgmiss_40_49"]) + _first_float(row, ["fgmiss_50_59", "fgmiss_50p"]) + _first_float(row, ["fgmiss_60p"])
    # "sack" is overloaded: for a defense it's sacks recorded (a positive), for
    # an offensive player it's times the QB was sacked (a negative). Route to
    # distinct keys so the two never share a scoring weight.
    sack_val = _first_float(row, ["sack", "sacks"])
    stats.pop("sack", None)
    if position == "DST":
        stats["sack"] = sack_val
    else:
        stats["sack_taken"] = sack_val
    stats["def_int"] = _first_float(row, ["def_int", "int"])
    stats["fumble_recovery"] = _first_float(row, ["fumble_recovery", "fum_rec"])
    stats["safety"] = _first_float(row, ["safety"])
    stats["prt_td"] = _first_float(row, ["prt_td", "pr_td"])
    stats["krt_td"] = _first_float(row, ["krt_td", "kr_td"])
    if position == "DST":
        stats["int_ret_td"] = _first_float(row, ["int_ret_td", "def_td"])
    return {k: v for k, v in stats.items() if v}


def _app_stats_from_nflverse(row: dict, position: str) -> Dict[str, float]:
    stats = {
        "pass_yd": _to_float(row.get("passing_yards")),
        "pass_td": _to_float(row.get("passing_tds")),
        "pass_int": _to_float(row.get("passing_interceptions")),
        "pass_2pt": _to_float(row.get("passing_2pt_conversions")),
        "rush_yd": _to_float(row.get("rushing_yards")),
        "rush_td": _to_float(row.get("rushing_tds")),
        "rush_2pt": _to_float(row.get("rushing_2pt_conversions")),
        "rec": _to_float(row.get("receptions")),
        "rec_yd": _to_float(row.get("receiving_yards")),
        "rec_td": _to_float(row.get("receiving_tds")),
        "rec_2pt": _to_float(row.get("receiving_2pt_conversions")),
        "fumbles": _to_float(row.get("rushing_fumbles_lost")) + _to_float(row.get("receiving_fumbles_lost")) + _to_float(row.get("sack_fumbles_lost")),
        "fumbles_total": _to_float(row.get("rushing_fumbles")) + _to_float(row.get("receiving_fumbles")) + _to_float(row.get("sack_fumbles")),
        "sack_taken": _to_float(row.get("sacks")),
        "pat_made": _to_float(row.get("pat_made")),
        "fg_miss": _to_float(row.get("fg_missed")),
        "fg_0_39": _to_float(row.get("fg_made_0_19")) + _to_float(row.get("fg_made_20_29")) + _to_float(row.get("fg_made_30_39")),
        "fg_40_49": _to_float(row.get("fg_made_40_49")),
        "fg_50_59": _to_float(row.get("fg_made_50_59")),
        "fg_60_plus": _to_float(row.get("fg_made_60_")),
    }
    if position != "K":
        for key in ["pat_made", "fg_miss", "fg_0_39", "fg_40_49", "fg_50_59", "fg_60_plus"]:
            stats.pop(key, None)
    return {k: v for k, v in stats.items() if v}


def _consensus_projection(samples: List[Dict[str, float]]) -> Dict[str, float]:
    """Per-stat median across projection sources (Sleeper / FFToday / ESPN).

    Operates on STAT lines, not points, so it's scoring-agnostic — the owner runs
    two leagues with different rules, so the right product is a consensus stat
    line that each league's scoring is then applied to. With two sources the
    median equals their average; with three or more it's robust to one outlier.
    """
    by_stat: Dict[str, List[float]] = {}
    for proj in samples:
        for stat, val in proj.items():
            by_stat.setdefault(stat, []).append(val)
    return {stat: round(statistics.median(vals), 2) for stat, vals in by_stat.items() if vals}


def _merge_many(
    merged: Dict[str, Player],
    players: Iterable[Player],
    source: str,
    proj_samples: Optional[Dict[str, List[Dict[str, float]]]] = None,
) -> None:
    for player in players:
        if not player.name or player.position not in {"QB", "RB", "WR", "TE", "K", "DST"}:
            continue
        key = _merge_key(player)
        # Collect each source's raw projection so projections can be combined by
        # per-stat median at the end, instead of first-source-wins gap-fill.
        if proj_samples is not None and _has_projection_value(player.projections):
            proj_samples.setdefault(key, []).append(dict(player.projections))
        existing = merged.get(key)
        if existing is None:
            _add_source(player, source)
            merged[key] = player
            continue
        _merge_player(existing, player, source)


def _merge_player(base: Player, incoming: Player, source: str) -> None:
    if not base.team and incoming.team:
        base.team = incoming.team
    if not base.bye_week and incoming.bye_week:
        base.bye_week = incoming.bye_week
    if incoming.adp is not None and (base.adp is None or incoming.adp < base.adp):
        base.adp = incoming.adp
    if base.age is None and incoming.age is not None:
        base.age = incoming.age
    if base.experience is None and incoming.experience is not None:
        base.experience = incoming.experience
    for season, season_stats in incoming.historical_stats.items():
        base.historical_stats.setdefault(season, season_stats)
    if not _has_projection_value(base.projections) and _has_projection_value(incoming.projections):
        base.projections.update(incoming.projections)
        if incoming.metadata.get("projection_source"):
            base.metadata["projection_source"] = incoming.metadata["projection_source"]
    else:
        for key, value in incoming.projections.items():
            if key not in base.projections or not base.projections[key]:
                base.projections[key] = value
    for key, value in incoming.metadata.items():
        if key == "sources":
            continue
        if key not in base.metadata or base.metadata[key] in (None, "", []):
            base.metadata[key] = value
    _add_source(base, source)
    for source_name in incoming.metadata.get("sources", []):
        _add_source(base, str(source_name))


def _merge_key(player: Player) -> str:
    if player.position == "DST":
        return f"{_team_code_or_name(player)}|DST"
    return f"{_norm_name(player.name)}|{player.position}"


def _team_code_or_name(player: Player) -> str:
    team = (player.team or "").strip().upper()
    if team:
        return team
    for code, name in NFL_TEAM_NAMES.items():
        if _norm_name(player.name) == _norm_name(name):
            return code
    return _norm_name(player.name).upper()


def _player_name(meta: dict, player_id: str, position: str, team: Optional[str]) -> str:
    if position == "DST":
        return NFL_TEAM_NAMES.get(str(team or player_id).upper(), str(team or player_id).upper())
    return str(meta.get("full_name") or meta.get("search_full_name") or meta.get("last_name") or player_id)


def _normalize_position(position: object) -> str:
    pos = str(position or "").upper()
    if pos in {"DEF", "D/ST"}:
        return "DST"
    return pos


def _copy_stats(row: dict, keys: Iterable[str]) -> Dict[str, float]:
    return {key: _to_float(row.get(key)) for key in keys if _to_float(row.get(key))}


def _best_sleeper_adp(row: dict, adp_format: str) -> Optional[float]:
    format_key = adp_format.replace("-", "_")
    candidates = [f"adp_{format_key}", "adp_half_ppr", "adp_ppr", "adp_std"]
    for key in candidates:
        value = _valid_adp(row.get(key))
        if value is not None:
            return value
    return None


def _valid_adp(value: object) -> Optional[float]:
    val = _to_float(value)
    if val <= 0 or val >= 998:
        return None
    return val


def _has_projection_value(projections: Dict[str, float]) -> bool:
    return any(abs(float(v)) > 0 for v in projections.values())


def _first_float(row: dict, keys: Iterable[str]) -> float:
    for key in keys:
        val = _to_float(row.get(key))
        if val:
            return val
    return 0.0


def _to_float(value: object) -> float:
    if value is None:
        return 0.0
    try:
        text = str(value).strip().replace(",", "")
        if text in {"", "-", "NA", "N/A", "nan"}:
            return 0.0
        return float(text)
    except (TypeError, ValueError):
        return 0.0


def _to_int(value: object) -> Optional[int]:
    try:
        if value in (None, ""):
            return None
        return int(float(str(value)))
    except (TypeError, ValueError):
        return None


def _norm_name(name: str) -> str:
    text = name.lower().replace(".", "")
    text = re.sub(r"\b(jr|sr|ii|iii|iv|v)\b", "", text)
    return re.sub(r"[^a-z0-9]+", "", text)


def _clean_metadata(metadata: Dict[str, object]) -> Dict[str, object]:
    return {k: v for k, v in metadata.items() if v not in (None, "", [])}


def _add_source(player: Player, source: str) -> None:
    sources = list(player.metadata.get("sources", []))
    if source not in sources:
        sources.append(source)
    player.metadata["sources"] = sources


def _age_from_birth_date(birth_date: object) -> Optional[int]:
    if not birth_date:
        return None
    try:
        born = date.fromisoformat(str(birth_date)[:10])
    except ValueError:
        return None
    today = date.today()
    return today.year - born.year - ((today.month, today.day) < (born.month, born.day))


def _espn_position(value: object) -> str:
    position_ids = {1: "QB", 2: "RB", 3: "WR", 4: "TE", 5: "K", 16: "DST"}
    if isinstance(value, list):
        for item in value:
            pos = position_ids.get(_to_int(item) or -1)
            if pos:
                return pos
        return ""
    return position_ids.get(_to_int(value) or -1, "")


def _espn_team(value: object) -> Optional[str]:
    teams = {
        1: "ATL", 2: "BUF", 3: "CHI", 4: "CIN", 5: "CLE", 6: "DAL", 7: "DEN", 8: "DET",
        9: "GB", 10: "TEN", 11: "IND", 12: "KC", 13: "LV", 14: "LAR", 15: "MIA", 16: "MIN",
        17: "NE", 18: "NO", 19: "NYG", 20: "NYJ", 21: "PHI", 22: "ARI", 23: "PIT", 24: "LAC",
        25: "SF", 26: "SEA", 27: "TB", 28: "WAS", 29: "CAR", 30: "JAX", 33: "BAL", 34: "HOU",
    }
    return teams.get(_to_int(value) or -1)


def _nested_get(data: object, keys: List[object]) -> object:
    cur = data
    for key in keys:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur
