from __future__ import annotations
import re
import json
import time
from html.parser import HTMLParser
from typing import Dict, List, Optional, Tuple
from urllib.request import urlopen, Request

from ..models import Player


class _TableFrame:
    """In-progress rows for one open <table> (one frame per nesting level)."""
    __slots__ = ("rows", "row", "cell")

    def __init__(self) -> None:
        self.rows: List[List[str]] = []
        self.row: Optional[List[str]] = None
        self.cell: Optional[str] = None


class _TableParser(HTMLParser):
    """Collect every <table> as rows of cell text.

    FFToday uses old-school *nested* layout tables, so a single in-progress
    buffer gets scrambled (an inner <table> resets it and its </table> closes
    the outer one). We keep a stack of frames — one per open table — so each
    table's rows are captured independently regardless of nesting.
    """

    def __init__(self) -> None:
        super().__init__()
        self.tables: List[List[List[str]]] = []
        self._stack: List[_TableFrame] = []

    def _top(self) -> Optional[_TableFrame]:
        return self._stack[-1] if self._stack else None

    def handle_starttag(self, tag: str, attrs):
        frame = self._top()
        if tag == "table":
            self._stack.append(_TableFrame())
        elif tag == "tr" and frame is not None:
            frame.row = []
        elif tag in ("td", "th") and frame is not None and frame.row is not None:
            frame.cell = ""

    def handle_endtag(self, tag: str):
        frame = self._top()
        if frame is None:
            return
        if tag in ("td", "th") and frame.cell is not None:
            frame.row.append(self._clean(frame.cell))
            frame.cell = None
        elif tag == "tr" and frame.row is not None:
            frame.rows.append(frame.row)
            frame.row = None
        elif tag == "table":
            done = self._stack.pop()
            if done.rows:
                self.tables.append(done.rows)

    def handle_data(self, data: str):
        frame = self._top()
        if frame is not None and frame.cell is not None:
            frame.cell += data

    def _clean(self, s: str) -> str:
        return re.sub(r"\s+", " ", s).strip()


def _fetch(url: str, attempts: int = 3) -> str:
    # FFToday is the one source pulled by scraping web pages, and its server
    # drops connections transiently; a single hiccup used to silently cost the
    # whole source (and with it consensus projections), so retry with a short
    # backoff before giving up.
    last_exc: Optional[Exception] = None
    for attempt in range(attempts):
        if attempt:
            time.sleep(2 * attempt)
        try:
            return _fetch_once(url)
        except Exception as exc:
            last_exc = exc
    raise last_exc


def _fetch_once(url: str) -> str:
    req = Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "Cache-Control": "no-cache",
    })
    with urlopen(req, timeout=20) as resp:
        data = resp.read()
        try:
            return data.decode("utf-8")
        except Exception:
            try:
                return data.decode("latin-1")
            except Exception:
                return data.decode("utf-8", errors="ignore")


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")


def _to_float(s: str) -> float:
    try:
        s = s.replace(",", "").strip()
        if s in ("", "-"):
            return 0.0
        return float(s)
    except Exception:
        return 0.0


def _select_projection_table(html: str) -> Optional[List[List[str]]]:
    p = _TableParser()
    p.feed(html)
    # The projection table's first row is a colspan title ("Quarterback
    # Projections: 2026"), so the real column header ("Player", "Team", ...) is
    # a later row. Scan EVERY row of EVERY table for the header, then return the
    # table sliced from that row so callers can treat row 0 as the header. Pick
    # the largest such table (the real board has the most rows).
    best: Optional[List[List[str]]] = None
    for t in p.tables:
        for i, row in enumerate(t):
            if any("player" in _norm(c) for c in row):
                candidate = t[i:]
                if len(candidate) >= 3 and (best is None or len(candidate) > len(best)):
                    best = candidate
                break
    return best


# FFToday's projection tables label stats positionally with DUPLICATE names
# (e.g. Passing "Att/Yds/TD" then Rushing "Att/Yds/TD"), so column-name matching
# can't tell the blocks apart. Instead we map by fixed offset from the Bye
# column. Each position orders its stat blocks differently — values below are the
# 0-based stat-column index AFTER Bye, verified against the live tables:
#   QB: Cmp, PassAtt, PassYds, PassTD, PassINT, RushAtt, RushYds, RushTD, FPts
#   RB: RushAtt, RushYds, RushTD, Rec, RecYds, RecTD, FPts        (rushing first)
#   WR: Rec, RecYds, RecTD, RushAtt, RushYds, RushTD, FPts        (receiving first)
#   TE: Rec, RecYds, RecTD, FPts                                  (receiving only)
# K and DST are intentionally not scraped here — FFToday's kicker table has no
# FG-by-distance breakdown and its defense format differs; Sleeper carries both.
_STAT_OFFSETS: Dict[str, Dict[str, int]] = {
    "QB": {"pass_yd": 2, "pass_td": 3, "pass_int": 4, "rush_yd": 6, "rush_td": 7},
    "RB": {"rush_yd": 1, "rush_td": 2, "rec": 3, "rec_yd": 4, "rec_td": 5},
    "WR": {"rec": 0, "rec_yd": 1, "rec_td": 2, "rush_yd": 4, "rush_td": 5},
    "TE": {"rec": 0, "rec_yd": 1, "rec_td": 2},
}


def _extract_players_from_table(table: List[List[str]], pos: str) -> List[Player]:
    offsets = _STAT_OFFSETS.get(pos)
    if not offsets:
        return []
    header = [_norm(h) for h in table[0]]
    i_player = next((i for i, h in enumerate(header) if "player" in h), None)
    i_team = next((i for i, h in enumerate(header) if h in ("tm", "team")), None)
    i_bye = next((i for i, h in enumerate(header) if h == "bye" or h.startswith("bye")), None)
    if i_player is None or i_bye is None:
        return []
    base = i_bye + 1  # first stat column

    players: List[Player] = []
    for row in table[1:]:
        if i_player >= len(row):
            continue
        name = row[i_player].strip()
        # Skip blank rows and FFToday's repeated header rows.
        if not name or "player" in _norm(name):
            continue
        team = row[i_team].strip() if (i_team is not None and i_team < len(row)) else None
        projections: Dict[str, float] = {}
        for stat, off in offsets.items():
            j = base + off
            if j < len(row):
                val = _to_float(row[j])
                if val:
                    projections[stat] = val
        if not projections:
            continue
        players.append(Player(
            id=f"{name}|{pos}",
            name=name,
            position=pos,
            team=team or None,
            projections=projections,
        ))
    return players


def fetch_fftoday(season: int, pos: str) -> List[Player]:
    pos = pos.upper()
    pos_ids = {"QB": 10, "RB": 20, "WR": 30, "TE": 40, "K": 80, "DST": 99}
    if pos not in pos_ids:
        return []
    url = f"https://www.fftoday.com/rankings/playerproj.php?Season={season}&PosID={pos_ids[pos]}&LeagueID=1"
    html = _fetch(url)
    table = _select_projection_table(html)
    if not table:
        return []
    return _extract_players_from_table(table, pos)


def fetch_all_fftoday(season: int) -> List[Player]:
    all_players: List[Player] = []
    errors: List[str] = []
    # Offensive skill positions only — K/DST come from Sleeper (see _STAT_OFFSETS).
    for pos in ["QB", "RB", "WR", "TE"]:
        try:
            all_players.extend(fetch_fftoday(season, pos))
        except Exception as exc:
            errors.append(f"{pos}: {exc}")
    # A total wipeout must surface as a failed source report, not an empty
    # success — otherwise the pull looks fine while consensus quietly vanishes.
    if errors and not all_players:
        raise RuntimeError("; ".join(errors))
    return all_players
