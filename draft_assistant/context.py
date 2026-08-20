"""Dynamic, attributable player context for draft and waiver decisions.

The projection board is the immutable baseline.  This module keeps injuries,
roster status, depth chart, trends, weekly projections, and current-season
actuals in a separate cache and derives point views at read time.  That makes
refreshes idempotent: no news multiplier is ever written back into a player's
season projection.
"""
from __future__ import annotations

import csv
import io
import json
import math
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from typing import Dict, Iterable, List, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .fuzzy import normalize_player_name
from .models import Player, PlayerContext, PlayerSignal
from .paths import resolve
from .storage import atomic_write_json


SLEEPER_BASE = "https://api.sleeper.app/v1"
NFLVERSE_ASSET = (
    "https://github.com/nflverse/nflverse-data/releases/download/{tag}/{asset}"
)
CONTEXT_RELATIVE_PATH = "data/player_context.json"

SOURCE_TTLS = {
    "sleeper_players": timedelta(hours=24),
    "sleeper_trending": timedelta(minutes=15),
    "sleeper_weekly": timedelta(hours=1),
    "sleeper_actuals": timedelta(hours=6),
    "nflverse_injuries": timedelta(hours=24),
    "nflverse_depth": timedelta(hours=24),
    "nflverse_stats": timedelta(hours=24),
    "nflverse_snaps": timedelta(hours=24),
}

STAT_ALIASES = {
    "pass_yd": "pass_yd", "passing_yards": "pass_yd",
    "pass_td": "pass_td", "passing_tds": "pass_td",
    "pass_int": "pass_int", "passing_interceptions": "pass_int",
    "pass_2pt": "pass_2pt", "passing_2pt_conversions": "pass_2pt",
    "rush_yd": "rush_yd", "rushing_yards": "rush_yd",
    "rush_td": "rush_td", "rushing_tds": "rush_td",
    "rush_2pt": "rush_2pt", "rushing_2pt_conversions": "rush_2pt",
    "rec": "rec", "receptions": "rec",
    "rec_yd": "rec_yd", "receiving_yards": "rec_yd",
    "rec_td": "rec_td", "receiving_tds": "rec_td",
    "rec_2pt": "rec_2pt", "receiving_2pt_conversions": "rec_2pt",
    "fum_lost": "fumbles", "fumbles_lost_total": "fumbles",
    "fumbles_total": "fumbles_total",
    "sacks_suffered": "sack_taken",
    "pat_made": "pat_made", "fg_missed": "fg_miss",
    "fg_made_0_19": "fg_0_19", "fg_made_20_29": "fg_20_29",
    "fg_made_30_39": "fg_30_39", "fg_made_40_49": "fg_40_49",
    "fg_made_50_59": "fg_50_59", "fg_made_60_": "fg_60_plus",
}

INELIGIBLE_ROSTER_STATUSES = {
    "inactive", "practice squad", "retired", "free agent",
}
ZERO_WEEK_STATUSES = {
    "out", "inactive", "injured reserve", "ir", "reserve/pup", "pup",
    "reserve/nfi", "nfi", "suspended",
}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def isoformat(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def default_season(today: Optional[date] = None) -> int:
    return (today or date.today()).year


def default_week(today: Optional[date] = None) -> int:
    """Return a practical regular-season default; the UI remains editable."""
    today = today or date.today()
    if today.month < 9:
        return 1
    if today.month > 12:
        return 18
    opener = date(today.year, 9, 1)
    return max(1, min(18, ((today - opener).days // 7) + 1))


def context_path() -> str:
    return resolve(CONTEXT_RELATIVE_PATH)


def empty_context(season: Optional[int] = None, week: Optional[int] = None) -> PlayerContext:
    return PlayerContext(
        season=season or default_season(),
        selected_week=max(1, min(18, week or default_week())),
    )


def _signal_to_dict(signal: PlayerSignal) -> dict:
    return {
        "player_id": signal.player_id,
        "kind": signal.kind,
        "value": signal.value,
        "source": signal.source,
        "observed_at": signal.observed_at,
        "effective_week": signal.effective_week,
        "expires_at": signal.expires_at,
        "attribution": signal.attribution,
        "details": signal.details,
    }


def _signal_from_dict(raw: object) -> Optional[PlayerSignal]:
    if not isinstance(raw, dict):
        return None
    required = ("player_id", "kind", "value", "source", "observed_at")
    if not all(isinstance(raw.get(key), str) and raw.get(key) for key in required):
        return None
    week = raw.get("effective_week")
    try:
        week = int(week) if week is not None else None
    except (TypeError, ValueError):
        week = None
    details = raw.get("details") if isinstance(raw.get("details"), dict) else {}
    return PlayerSignal(
        player_id=raw["player_id"], kind=raw["kind"], value=raw["value"],
        source=raw["source"], observed_at=raw["observed_at"],
        effective_week=week,
        expires_at=raw.get("expires_at") if isinstance(raw.get("expires_at"), str) else None,
        attribution=raw.get("attribution") if isinstance(raw.get("attribution"), str) else None,
        details=details,
    )


def context_to_dict(context: PlayerContext) -> dict:
    return {
        "schema_version": 1,
        "season": context.season,
        "selected_week": context.selected_week,
        "refreshed_at": context.refreshed_at,
        "signals": [_signal_to_dict(signal) for signal in context.signals],
        "weekly_projections": context.weekly_projections,
        "actual_stats": context.actual_stats,
        "source_health": context.source_health,
    }


def context_from_dict(raw: object) -> PlayerContext:
    if not isinstance(raw, dict):
        raise ValueError("player context must be an object")
    try:
        season = int(raw.get("season") or default_season())
        week = max(1, min(18, int(raw.get("selected_week") or default_week())))
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid player context season/week") from exc
    signals = [
        signal for signal in (_signal_from_dict(item) for item in raw.get("signals", []))
        if signal is not None
    ]
    projections = raw.get("weekly_projections")
    actuals = raw.get("actual_stats")
    health = raw.get("source_health")
    return PlayerContext(
        season=season,
        selected_week=week,
        refreshed_at=raw.get("refreshed_at") if isinstance(raw.get("refreshed_at"), str) else None,
        signals=signals,
        weekly_projections=projections if isinstance(projections, dict) else {},
        actual_stats=actuals if isinstance(actuals, dict) else {},
        source_health=health if isinstance(health, dict) else {},
    )


def load_context(path: Optional[str] = None, season: Optional[int] = None, week: Optional[int] = None) -> PlayerContext:
    path = path or context_path()
    try:
        with open(path, "r", encoding="utf-8") as handle:
            context = context_from_dict(json.load(handle))
    except (FileNotFoundError, OSError, UnicodeError, json.JSONDecodeError, ValueError):
        context = empty_context(season, week)
    if season is not None and context.season != season:
        return empty_context(season, week)
    if week is not None:
        context.selected_week = max(1, min(18, int(week)))
    return context


def save_context(context: PlayerContext, path: Optional[str] = None) -> None:
    atomic_write_json(path or context_path(), context_to_dict(context))


def _parse_time(value: object) -> Optional[datetime]:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _source_due(context: PlayerContext, source: str, now: datetime, force: bool, week: Optional[int] = None) -> bool:
    if force:
        return True
    health = context.source_health.get(source, {})
    if week is not None and health.get("week") != week:
        return True
    refreshed = _parse_time(health.get("refreshed_at"))
    return refreshed is None or now - refreshed >= SOURCE_TTLS[source]


def _health(context: PlayerContext, source: str, now: datetime, ok: bool, records: int, detail: str = "", **extra) -> None:
    previous = context.source_health.get(source, {})
    context.source_health[source] = {
        "ok": bool(ok), "records": int(records), "detail": str(detail),
        # A failed request must not make stale source data look freshly fetched.
        # Keep its last success timestamp so the next background refresh retries it.
        "refreshed_at": isoformat(now) if ok else previous.get("refreshed_at"),
        "attempted_at": isoformat(now),
        **extra,
    }


def _replace_signals(context: PlayerContext, source: str, signals: Iterable[PlayerSignal]) -> None:
    context.signals = [signal for signal in context.signals if signal.source != source]
    context.signals.extend(signals)


def _request(url: str, timeout: int = 30) -> bytes:
    req = Request(url, headers={
        "User-Agent": "DraftAssistant/0.3 (+https://github.com/keganvosteen/draft-assistant)",
        "Accept": "application/json,text/csv,text/plain,*/*",
    })
    with urlopen(req, timeout=timeout) as response:
        return response.read()


def _fetch_json(url: str, timeout: int = 30) -> object:
    return json.loads(_request(url, timeout).decode("utf-8"))


def _fetch_csv(url: str, timeout: int = 45) -> List[dict]:
    text = _request(url, timeout).decode("utf-8-sig", errors="replace")
    return list(csv.DictReader(io.StringIO(text)))


def _number(value: object) -> float:
    try:
        result = float(str(value).strip())
        return result if math.isfinite(result) else 0.0
    except (TypeError, ValueError):
        return 0.0


def _stats(raw: object) -> Dict[str, float]:
    if not isinstance(raw, dict):
        return {}
    out: Dict[str, float] = {}
    for source_key, app_key in STAT_ALIASES.items():
        if source_key not in raw:
            continue
        value = _number(raw.get(source_key))
        if value:
            out[app_key] = out.get(app_key, 0.0) + value
    # The app scores field goals in consolidated distance buckets.
    low = sum(out.pop(key, 0.0) for key in ("fg_0_19", "fg_20_29", "fg_30_39"))
    if low:
        out["fg_0_39"] = low
    return out


def _signal(player_id: str, kind: str, value: object, source: str, observed: datetime, *,
            week: Optional[int] = None, expires: Optional[datetime] = None,
            attribution: Optional[str] = None, details: Optional[dict] = None) -> PlayerSignal:
    return PlayerSignal(
        player_id=player_id, kind=kind, value=str(value), source=source,
        observed_at=isoformat(observed), effective_week=week,
        expires_at=isoformat(expires) if expires else None,
        attribution=attribution, details=details or {},
    )


def _refresh_sleeper_players(context: PlayerContext, now: datetime) -> int:
    raw = _fetch_json(f"{SLEEPER_BASE}/players/nfl", timeout=45)
    if not isinstance(raw, dict):
        raise ValueError("unexpected Sleeper players response")
    signals: List[PlayerSignal] = []
    expiry = now + timedelta(days=2)
    for player_id, meta in raw.items():
        if not isinstance(meta, dict):
            continue
        position = str(meta.get("position") or "").upper()
        if position not in {"QB", "RB", "FB", "WR", "TE", "K", "DEF", "DST"}:
            continue
        identity = f"sleeper:{player_id}"
        status = meta.get("status")
        if status and _normalized(str(status)) != "active":
            signals.append(_signal(identity, "roster_status", status, "sleeper_players", now,
                                   attribution="Sleeper"))
        injury = meta.get("injury_status")
        if injury:
            signals.append(_signal(identity, "injury", injury, "sleeper_players", now,
                                   week=context.selected_week, expires=expiry, attribution="Sleeper"))
        practice = meta.get("practice_participation")
        if practice:
            signals.append(_signal(identity, "practice", practice, "sleeper_players", now,
                                   week=context.selected_week, expires=expiry, attribution="Sleeper"))
        depth = meta.get("depth_chart_position")
        if depth not in (None, ""):
            signals.append(_signal(identity, "depth_chart", depth, "sleeper_players", now,
                                   attribution="Sleeper",
                                   details={"order": meta.get("depth_chart_order")}))
        updated = meta.get("news_updated")
        if updated:
            try:
                observed = datetime.fromtimestamp(float(updated) / 1000.0, tz=timezone.utc)
            except (TypeError, ValueError, OSError):
                observed = now
            # ``news_updated`` can exist for long-retired players. It is useful
            # as a freshness clue, not as a permanent signal worth caching.
            if now - timedelta(days=7) <= observed <= now + timedelta(minutes=5):
                signals.append(_signal(identity, "source_updated", "Player information updated",
                                       "sleeper_players", observed,
                                       expires=observed + timedelta(days=7),
                                       attribution="Sleeper"))
    _replace_signals(context, "sleeper_players", signals)
    return len(raw)


def _refresh_sleeper_trending(context: PlayerContext, now: datetime) -> int:
    signals: List[PlayerSignal] = []
    records = 0
    for trend_type in ("add", "drop"):
        raw = _fetch_json(
            f"{SLEEPER_BASE}/players/nfl/trending/{trend_type}?lookback_hours=24&limit=100"
        )
        if not isinstance(raw, list):
            raise ValueError(f"unexpected Sleeper trending {trend_type} response")
        records += len(raw)
        for item in raw:
            if not isinstance(item, dict) or not item.get("player_id"):
                continue
            signals.append(_signal(
                f"sleeper:{item['player_id']}", f"trend_{trend_type}",
                int(_number(item.get("count"))), "sleeper_trending", now,
                expires=now + timedelta(minutes=30), attribution="Sleeper",
                details={"lookback_hours": 24},
            ))
    _replace_signals(context, "sleeper_trending", signals)
    return records


def _refresh_sleeper_weekly(context: PlayerContext) -> int:
    raw = _fetch_json(
        f"{SLEEPER_BASE}/projections/nfl/regular/{context.season}/{context.selected_week}",
        timeout=45,
    )
    if not isinstance(raw, dict):
        raise ValueError("unexpected Sleeper weekly projection response")
    context.weekly_projections = {
        f"sleeper:{player_id}": stats
        for player_id, row in raw.items()
        if (stats := _stats(row))
    }
    return len(context.weekly_projections)


def _refresh_sleeper_actuals(context: PlayerContext) -> int:
    raw = _fetch_json(f"{SLEEPER_BASE}/stats/nfl/regular/{context.season}", timeout=45)
    if not isinstance(raw, dict):
        raise ValueError("unexpected Sleeper stats response")
    context.actual_stats = {
        key: value for key, value in context.actual_stats.items()
        if not key.startswith("sleeper:")
    }
    actuals = {
        f"sleeper:{player_id}": stats
        for player_id, row in raw.items()
        if (stats := _stats(row))
    }
    context.actual_stats.update(actuals)
    return len(actuals)


def _refresh_nflverse_injuries(context: PlayerContext, now: datetime) -> int:
    asset = f"injuries_{context.season}.csv"
    rows = _fetch_csv(NFLVERSE_ASSET.format(tag="injuries", asset=asset))
    latest_week = max((int(_number(row.get("week"))) for row in rows), default=context.selected_week)
    signals: List[PlayerSignal] = []
    for row in rows:
        if int(_number(row.get("week"))) != latest_week or not row.get("gsis_id"):
            continue
        identity = f"gsis:{row['gsis_id']}"
        status = row.get("report_status")
        practice = row.get("practice_status")
        if status:
            signals.append(_signal(identity, "injury", status, "nflverse_injuries", now,
                                   week=latest_week, expires=now + timedelta(days=7),
                                   attribution="nflverse",
                                   details={"injury": row.get("report_primary_injury")}))
        if practice:
            signals.append(_signal(identity, "practice", practice, "nflverse_injuries", now,
                                   week=latest_week, expires=now + timedelta(days=7),
                                   attribution="nflverse"))
    _replace_signals(context, "nflverse_injuries", signals)
    return len(signals)


def _refresh_nflverse_depth(context: PlayerContext, now: datetime) -> int:
    asset = f"depth_charts_{context.season}.csv"
    rows = _fetch_csv(NFLVERSE_ASSET.format(tag="depth_charts", asset=asset))
    chosen: Dict[str, Tuple[int, dict]] = {}
    for row in rows:
        pos = str(row.get("pos_abb") or "").upper()
        if pos not in {"QB", "RB", "FB", "WR", "TE", "K"}:
            continue
        identity = (
            f"gsis:{row['gsis_id']}" if row.get("gsis_id")
            else f"name:{normalize_player_name(row.get('player_name') or '', compact=True)}"
        )
        rank = max(1, int(_number(row.get("pos_rank"))) or 1)
        if identity not in chosen or rank < chosen[identity][0]:
            chosen[identity] = (rank, row)
    signals = [
        _signal(identity, "depth_chart", f"{row.get('pos_abb') or ''}{rank}",
                "nflverse_depth", now, attribution="nflverse",
                details={"team": row.get("team"), "position": row.get("pos_name")})
        for identity, (rank, row) in chosen.items()
    ]
    _replace_signals(context, "nflverse_depth", signals)
    return len(signals)


def _refresh_nflverse_stats(context: PlayerContext) -> int:
    asset = f"stats_player_week_{context.season}.csv"
    rows = _fetch_csv(NFLVERSE_ASSET.format(tag="stats_player", asset=asset), timeout=60)
    context.actual_stats = {
        key: value for key, value in context.actual_stats.items()
        if not key.startswith("gsis:")
    }
    totals: Dict[str, Dict[str, float]] = {}
    for row in rows:
        if str(row.get("season_type") or "REG").upper() != "REG" or not row.get("player_id"):
            continue
        identity = f"gsis:{row['player_id']}"
        bucket = totals.setdefault(identity, {})
        for key, value in _stats(row).items():
            bucket[key] = bucket.get(key, 0.0) + value
    context.actual_stats.update(totals)
    return len(totals)


def _refresh_nflverse_snaps(context: PlayerContext, now: datetime) -> int:
    asset = f"snap_counts_{context.season}.csv"
    rows = _fetch_csv(NFLVERSE_ASSET.format(tag="snap_counts", asset=asset), timeout=60)
    latest_week = max((int(_number(row.get("week"))) for row in rows), default=0)
    signals: List[PlayerSignal] = []
    for row in rows:
        if int(_number(row.get("week"))) != latest_week:
            continue
        position = str(row.get("position") or "").upper()
        if position not in {"QB", "RB", "FB", "WR", "TE", "K"}:
            continue
        name_key = normalize_player_name(row.get("player") or "", compact=True)
        pct = _number(row.get("offense_pct"))
        if not name_key or pct <= 0:
            continue
        signals.append(_signal(
            f"name:{name_key}", "snap_share", f"{pct * 100:.0f}%",
            "nflverse_snaps", now, week=latest_week, attribution="nflverse",
            details={"team": row.get("team"), "offense_pct": pct},
        ))
    _replace_signals(context, "nflverse_snaps", signals)
    return len(signals)


def refresh_context(context: Optional[PlayerContext] = None, *, season: Optional[int] = None,
                    week: Optional[int] = None, force: bool = False,
                    now: Optional[datetime] = None) -> PlayerContext:
    """Refresh due sources, retaining last-known-good data on any failure."""
    now = now or utc_now()
    season = season or (context.season if context else default_season())
    week = max(1, min(18, int(week or (context.selected_week if context else default_week()))))
    if context is None or context.season != season:
        context = empty_context(season, week)
    context.selected_week = week

    collectors = [
        ("sleeper_players", lambda: _refresh_sleeper_players(context, now), None),
        ("sleeper_trending", lambda: _refresh_sleeper_trending(context, now), None),
        ("sleeper_weekly", lambda: _refresh_sleeper_weekly(context), week),
        ("sleeper_actuals", lambda: _refresh_sleeper_actuals(context), None),
        ("nflverse_injuries", lambda: _refresh_nflverse_injuries(context, now), None),
        ("nflverse_depth", lambda: _refresh_nflverse_depth(context, now), None),
        ("nflverse_stats", lambda: _refresh_nflverse_stats(context), None),
        ("nflverse_snaps", lambda: _refresh_nflverse_snaps(context, now), None),
    ]
    for source, collector, source_week in collectors:
        if not _source_due(context, source, now, force, source_week):
            continue
        try:
            records = collector()
            _health(context, source, now, True, records, week=source_week) if source_week else _health(
                context, source, now, True, records)
        except HTTPError as exc:
            if exc.code == 404 and source.startswith("nflverse_"):
                _health(context, source, now, True, 0,
                        "Not published for this season yet",
                        **({"week": source_week} if source_week else {}))
                continue
            previous = context.source_health.get(source, {})
            _health(context, source, now, False, int(previous.get("records") or 0), str(exc),
                    **({"week": source_week} if source_week else {}))
        except (URLError, OSError, ValueError, json.JSONDecodeError) as exc:
            previous = context.source_health.get(source, {})
            _health(context, source, now, False, int(previous.get("records") or 0), str(exc),
                    **({"week": source_week} if source_week else {}))

    context.refreshed_at = isoformat(now)
    return context


def player_context_ids(player: Player) -> List[str]:
    ids = [player.key()]
    sleeper_id = player.metadata.get("sleeper_id")
    gsis_id = player.metadata.get("gsis_id")
    if str(player.id).startswith("sleeper:"):
        ids.append(str(player.id))
    if sleeper_id:
        ids.append(f"sleeper:{sleeper_id}")
    if str(player.id).startswith(("gsis:", "nflverse:")):
        ids.append(str(player.id).replace("nflverse:", "gsis:", 1))
    if gsis_id:
        ids.append(f"gsis:{gsis_id}")
    ids.append(f"name:{normalize_player_name(player.name, compact=True)}")
    return list(dict.fromkeys(item for item in ids if item))


def signals_for_player(context: Optional[PlayerContext], player: Player, *, now: Optional[datetime] = None) -> List[PlayerSignal]:
    if context is None:
        return []
    aliases = set(player_context_ids(player))
    now = now or utc_now()
    signals = []
    for signal in context.signals:
        if signal.player_id not in aliases:
            continue
        expires = _parse_time(signal.expires_at)
        if expires is not None and expires < now:
            continue
        if signal.effective_week is not None and signal.kind in {"injury", "practice"}:
            if signal.effective_week != context.selected_week:
                continue
        signals.append(signal)
    return signals


def _normalized(value: str) -> str:
    return " ".join(value.lower().replace("-", " ").replace("/", " ").split())


def weekly_availability_factor(context: Optional[PlayerContext], player: Player) -> float:
    factor = 1.0
    for signal in signals_for_player(context, player):
        value = _normalized(signal.value)
        if signal.kind in {"injury", "roster_status"}:
            if value in ZERO_WEEK_STATUSES or any(token in value for token in ("injured reserve", "suspended")):
                return 0.0
            if "doubtful" in value:
                factor = min(factor, 0.25)
    return factor


def season_ending(context: Optional[PlayerContext], player: Player) -> bool:
    for signal in signals_for_player(context, player):
        value = _normalized(signal.value)
        if signal.kind in {"injury", "roster_status"} and (
            "out for season" in value or "season ending" in value or value == "retired"
        ):
            return True
    return False


def is_candidate_eligible(context: Optional[PlayerContext], player: Player) -> bool:
    for signal in signals_for_player(context, player):
        if signal.kind == "roster_status" and _normalized(signal.value) in INELIGIBLE_ROSTER_STATUSES:
            return False
    return True


def _context_stats(context: Optional[PlayerContext], player: Player, bucket: str) -> Optional[Dict[str, float]]:
    if context is None:
        return None
    source = context.weekly_projections if bucket == "weekly" else context.actual_stats
    for identity in player_context_ids(player):
        stats = source.get(identity)
        if isinstance(stats, dict):
            return {key: _number(value) for key, value in stats.items() if _number(value)}
    return None


def weekly_projection_for(context: Optional[PlayerContext], player: Player) -> Optional[Dict[str, float]]:
    return _context_stats(context, player, "weekly")


def actual_stats_for(context: Optional[PlayerContext], player: Player) -> Optional[Dict[str, float]]:
    return _context_stats(context, player, "actual")


def urgency_for_player(context: Optional[PlayerContext], player: Player) -> int:
    adds = drops = 0
    for signal in signals_for_player(context, player):
        if signal.kind == "trend_add":
            adds += int(_number(signal.value))
        elif signal.kind == "trend_drop":
            drops += int(_number(signal.value))
    return adds - drops


def confidence_for_player(context: Optional[PlayerContext], player: Player) -> float:
    score = 1.0
    for signal in signals_for_player(context, player):
        value = _normalized(signal.value)
        if signal.kind == "injury":
            if "questionable" in value:
                score -= 0.15
            elif "doubtful" in value:
                score -= 0.35
            elif value in ZERO_WEEK_STATUSES:
                score -= 0.5
        elif signal.kind == "practice" and "limited" in value:
            score -= 0.08
    return round(max(0.0, min(1.0, score)), 2)


def signal_summary(context: Optional[PlayerContext], player: Player, limit: int = 4) -> List[dict]:
    priority = {
        "roster_status": 0, "injury": 1, "practice": 2, "depth_chart": 3,
        "trend_add": 4, "trend_drop": 4, "snap_share": 5, "source_updated": 6,
    }
    signals = sorted(
        signals_for_player(context, player),
        key=lambda signal: (priority.get(signal.kind, 99), signal.source, signal.value),
    )
    return [_signal_to_dict(signal) for signal in signals[:limit]]


def primary_availability(context: Optional[PlayerContext], player: Player) -> Optional[str]:
    for kind in ("injury", "roster_status", "practice"):
        for signal in signals_for_player(context, player):
            if signal.kind == kind:
                value = _normalized(signal.value)
                if kind != "roster_status" or value != "active":
                    return signal.value
    return None


def season_adjusted_players(players: Iterable[Player], context: Optional[PlayerContext]) -> List[Player]:
    """Return derived player views; only explicit season-ending news zeros stats."""
    return [replace(player, projections={}) if season_ending(context, player) else player for player in players]


def is_stale(context: PlayerContext, now: Optional[datetime] = None, max_age: timedelta = timedelta(minutes=15)) -> bool:
    refreshed = _parse_time(context.refreshed_at)
    return refreshed is None or (now or utc_now()) - refreshed >= max_age


def context_payload(context: PlayerContext, *, include_signals: bool = True) -> dict:
    failed_sources = [
        source for source, health in context.source_health.items()
        if isinstance(health, dict) and health.get("ok") is False
    ]
    payload = {
        "season": context.season,
        "week": context.selected_week,
        "refreshedAt": context.refreshed_at,
        "stale": is_stale(context) or bool(failed_sources),
        "signalCount": len(context.signals),
        "sources": context.source_health,
        "failedSources": failed_sources,
    }
    if include_signals:
        payload["signals"] = [_signal_to_dict(signal) for signal in context.signals]
    return payload
