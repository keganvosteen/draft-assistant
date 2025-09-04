from __future__ import annotations
import re
import json
from html.parser import HTMLParser
from typing import Dict, List, Optional, Tuple
from urllib.request import urlopen, Request

from ..models import Player


class _TableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tables: List[List[List[str]]] = []
        self._in_table = False
        self._in_tr = False
        self._in_td = False
        self._buf: List[List[str]] = []
        self._row: List[str] = []
        self._cell = ""

    def handle_starttag(self, tag: str, attrs):
        if tag == "table":
            self._in_table = True
            self._buf = []
        elif self._in_table and tag == "tr":
            self._in_tr = True
            self._row = []
        elif self._in_tr and tag in ("td", "th"):
            self._in_td = True
            self._cell = ""

    def handle_endtag(self, tag: str):
        if tag == "table" and self._in_table:
            if self._buf:
                self.tables.append(self._buf)
            self._in_table = False
        elif tag == "tr" and self._in_tr:
            # finalize row
            if self._row:
                self._buf.append(self._row)
            self._in_tr = False
        elif tag in ("td", "th") and self._in_td:
            # finalize cell
            self._row.append(self._clean(self._cell))
            self._in_td = False

    def handle_data(self, data: str):
        if self._in_td:
            self._cell += data

    def _clean(self, s: str) -> str:
        return re.sub(r"\s+", " ", s).strip()


def _fetch(url: str) -> str:
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
    # Choose the first table that has a header row containing 'Player'
    for t in p.tables:
        if not t:
            continue
        header = [c.strip() for c in t[0]]
        if any("player" in _norm(h) for h in header):
            return t
    return None


def _extract_players_from_table(table: List[List[str]], pos: str) -> List[Player]:
    header = table[0]
    idx: Dict[str, int] = { _norm(h): i for i, h in enumerate(header) }

    def col(*names: str) -> Optional[int]:
        for n in names:
            n2 = _norm(n)
            if n2 in idx:
                return idx[n2]
        # heuristic matches
        for k, i in idx.items():
            if any(all(sub in k for sub in _norm(n).split('_')) for n in names):
                return i
        return None

    i_player = col("Player")
    i_team = col("Team", "Tm")

    players: List[Player] = []
    for row in table[1:]:
        if i_player is None or i_player >= len(row):
            continue
        name = row[i_player].strip()
        if not name or name.lower() in ("player", "team"):
            continue
        team = row[i_team].strip() if (i_team is not None and i_team < len(row)) else None
        projections: Dict[str, float] = {}

        if pos == "QB":
            projections["pass_yd"] = _get_num(row, idx, ["pass_yd", "pass_yds", "yds", "py"])
            projections["pass_td"] = _get_num(row, idx, ["pass_td", "td", "ptd"])
            projections["pass_int"] = _get_num(row, idx, ["int", "interceptions"])
            projections["rush_yd"] = _get_num(row, idx, ["rush_yd", "rush_yds", "ry"])
            projections["rush_td"] = _get_num(row, idx, ["rush_td", "rtd"])
            projections["rec"] = 0.0
            projections["rec_yd"] = 0.0
            projections["rec_td"] = 0.0
        elif pos in ("RB", "WR", "TE"):
            projections["rush_yd"] = _get_num(row, idx, ["rush_yd", "rush_yds", "ry"])
            projections["rush_td"] = _get_num(row, idx, ["rush_td", "rtd"])
            projections["rec"] = _get_num(row, idx, ["rec", "receptions"])
            projections["rec_yd"] = _get_num(row, idx, ["rec_yd", "rec_yds", "rey"])
            projections["rec_td"] = _get_num(row, idx, ["rec_td", "retd"])
            # no passing stats
            projections["pass_yd"] = 0.0
            projections["pass_td"] = 0.0
            projections["pass_int"] = 0.0
        elif pos == "K":
            # PAT / XP
            projections["pat_made"] = _get_num(row, idx, ["pat", "xpm", "xp_made"])  
            # Ranges
            r0 = _get_num(row, idx, ["0_19", "fg_0_19"]) 
            r20 = _get_num(row, idx, ["20_29", "fg_20_29"]) 
            r30 = _get_num(row, idx, ["30_39", "fg_30_39"]) 
            projections["fg_0_39"] = r0 + r20 + r30
            projections["fg_40_49"] = _get_num(row, idx, ["40_49", "fg_40_49"]) 
            projections["fg_50_59"] = _get_num(row, idx, ["50_59", "fg_50_59"]) 
            projections["fg_60_plus"] = _get_num(row, idx, ["60_plus", "60_", "fg_60_plus"]) 
            fga = _get_num(row, idx, ["fga", "fg_att", "att"]) 
            fgm = projections["fg_0_39"] + projections["fg_40_49"] + projections["fg_50_59"] + projections["fg_60_plus"]
            projections["fg_miss"] = max(0.0, fga - fgm)
        elif pos == "DST":
            projections["sack"] = _get_num(row, idx, ["sack", "sacks", "sk"]) 
            projections["def_int"] = _get_num(row, idx, ["int", "interceptions"]) 
            projections["fumble_recovery"] = _get_num(row, idx, ["fr", "fumbles_recovered"]) 
            projections["safety"] = _get_num(row, idx, ["safety", "sf"]) 
            td = _get_num(row, idx, ["td", "def_td"]) 
            projections["int_ret_td"] = td
            projections["fum_ret_td"] = 0.0
            projections["blk_kick_ret_td"] = 0.0
            projections["krt_td"] = 0.0
            projections["prt_td"] = 0.0
        else:
            continue

        players.append(Player(
            id=f"{name}|{pos}",
            name=name,
            position=pos,
            team=team if team else None,
            projections=projections,
        ))
    return players


def _get_num(row: List[str], idx: Dict[str, int], keys: List[str]) -> float:
    for k, i in idx.items():
        for j in keys:
            jn = j
            if all(part in k for part in jn.split("_")):
                if i < len(row):
                    return _to_float(row[i])
    return 0.0


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
    for pos in ["QB", "RB", "WR", "TE", "K", "DST"]:
        try:
            ps = fetch_fftoday(season, pos)
        except Exception:
            ps = []
        all_players.extend(ps)
    return all_players
