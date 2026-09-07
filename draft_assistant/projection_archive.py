"""Preseason snapshots of every projection source, kept for later grading.

Why this exists: the board's dominant projection source cannot be graded from
its own history.  Sleeper's archived projections endpoint returns numbers that
were revised *during* the season it describes -- ``backtest.py`` flags it
CONTAMINATED, and it "projected" rookie Puka Nacua at 87 catches in 2023.  So
the source that supplies most of the board is the one we can least honestly
measure, and no change to how projections are combined can be shown to help.

There is no way to reconstruct a clean preseason number after the fact.  The
only fix is to start writing them down now: each pull records what every source
said, before a single game was played, keyed by season.  A season later those
snapshots are exactly the clean preseason record ``backtest.py`` needs.

The first snapshot of a season wins.  A pull in August is a preseason opinion; a
pull in November is a source silently marking its own homework, and overwriting
with it would recreate the contamination this module exists to avoid.
"""
from __future__ import annotations

import json
import os
from datetime import date, datetime, timezone
from typing import Dict, List, Optional, Tuple

from .models import Player
from .paths import resolve
from .storage import atomic_write_json

ARCHIVE_RELATIVE_DIR = "data/projection_archive"

#: A season's projections stop being preseason once games are played. The NFL
#: opens in the first week of September, so anything recorded from September 1
#: onward has had a chance to see results and is not a clean preseason record.
PRESEASON_LAST_MONTH = 8


def archive_path(season: int) -> str:
    return resolve(f"{ARCHIVE_RELATIVE_DIR}/{int(season)}.json")


def is_preseason(season: int, today: Optional[date] = None) -> bool:
    """True while ``season``'s projections are still untainted by results."""
    today = today or date.today()
    if today.year < int(season):
        return True
    if today.year > int(season):
        return False
    return today.month <= PRESEASON_LAST_MONTH


def load_archive(season: int) -> dict:
    path = archive_path(season)
    if not os.path.exists(path):
        return {"season": int(season), "sources": {}}
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return {"season": int(season), "sources": {}}
    if not isinstance(data, dict) or not isinstance(data.get("sources"), dict):
        return {"season": int(season), "sources": {}}
    return data


def record_snapshot(
    season: int,
    samples: Dict[str, List[Tuple[str, Dict[str, float]]]],
    players: Dict[str, Player],
    *,
    today: Optional[date] = None,
    force: bool = False,
) -> List[str]:
    """Persist each source's preseason stat lines for ``season``.

    ``samples`` maps a merge key to ``(source, stats)`` pairs, exactly as
    ``free_sources.pull_free_data`` collects them. ``players`` supplies the name
    and position for each key so a snapshot can be read back without the board.

    Returns the sources newly written. Existing sources are left alone unless
    ``force`` is set -- re-recording a source mid-season would replace a genuine
    preseason opinion with a revised one.
    """
    if not samples:
        return []
    if not (force or is_preseason(season, today)):
        return []

    archive = load_archive(season)
    sources = archive.setdefault("sources", {})
    by_source: Dict[str, Dict[str, dict]] = {}
    for key, entries in samples.items():
        player = players.get(key)
        for source, stats in entries:
            if not stats:
                continue
            by_source.setdefault(source, {})[key] = {
                "name": player.name if player else key,
                "pos": player.position if player else "",
                "stats": {str(k): float(v) for k, v in stats.items()},
            }

    written: List[str] = []
    for source, entries in sorted(by_source.items()):
        if source in sources and not force:
            continue
        sources[source] = {
            "taken_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "players": entries,
        }
        written.append(source)

    if not written:
        return []
    archive["season"] = int(season)
    atomic_write_json(archive_path(season), archive)
    return written


def archived_sources(season: int) -> Dict[str, int]:
    """{source: player count} already banked for ``season``."""
    archive = load_archive(season)
    return {
        source: len((entry or {}).get("players") or {})
        for source, entry in sorted(archive.get("sources", {}).items())
    }


def archived_projection_points(season: int, source: str, scoring: Dict[str, float]) -> Dict[str, float]:
    """{"name|POS": points} for one archived source, in ``scoring``.

    The shape ``backtest.py`` grades sources in, so an archived snapshot can be
    dropped straight into the same comparison as FFToday's clean archive.
    """
    from .scoring import fantasy_points

    entry = load_archive(season).get("sources", {}).get(source) or {}
    out: Dict[str, float] = {}
    for record in (entry.get("players") or {}).values():
        name = str(record.get("name") or "").strip().lower()
        pos = str(record.get("pos") or "").upper()
        if not name or not pos:
            continue
        out[f"{name}|{pos}"] = fantasy_points(record.get("stats") or {}, scoring)
    return out
