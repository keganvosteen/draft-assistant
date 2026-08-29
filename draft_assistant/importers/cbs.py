"""CBS Sports season projections, scraped from their public stats pages.

Why CBS and not the more obvious names: FantasyPros server-renders only the
first ten players per position and serves the rest from ``/api/``, ``/ajax/``
and ``/json/``, all three of which its robots.txt disallows -- so there is no
permitted way to get a full table. NFL.com's projections page is a client-side
app with no ``<tr>`` in the HTML at all. CBS ships the whole table server-side:
79 quarterbacks and ~100 at the other positions, on a path its robots.txt
allows. (It disallows ``sortcol``/``sortdir`` query parameters, which is why the
URLs here carry none.)

Unlike FFToday, whose columns have to be located by fixed offsets because it
labels passing and rushing yards identically, CBS spells its headers out in
full -- "yds Passing Yards" against "yds Rushing Yards" -- so columns are
matched by their description and a reordered table cannot silently scramble the
stat mapping.
"""
from __future__ import annotations

from typing import Dict, List, Optional

from ..models import Player
from ._scrape import fetch_html, largest_table, norm, to_float

CBS_URL = ("https://www.cbssports.com/fantasy/football/stats/"
           "{position}/{season}/season/projections/ppr/")

POSITIONS = ("QB", "RB", "WR", "TE")

#: Normalised CBS header text -> our stat key. Anything unlisted (games played,
#: per-game rates, attempts, passer rating, fantasy points) is derived or
#: irrelevant, and is ignored rather than guessed at.
_HEADER_STATS: Dict[str, str] = {
    "yds_passing_yards": "pass_yd",
    "td_touchdowns_passes": "pass_td",
    "int_interceptions_thrown": "pass_int",
    "yds_rushing_yards": "rush_yd",
    "td_rushing_touchdowns": "rush_td",
    "rec_receptions": "rec",
    "yds_receiving_yards": "rec_yd",
    "td_receiving_touchdowns": "rec_td",
    "fl_fumbles_lost": "fumbles",
}


def _player_identity(cell: str, position: str) -> Optional[tuple]:
    """Pull (name, team) out of CBS's doubled player cell.

    The cell reads "J. Gibbs RB DET Jahmyr Gibbs RB DET" — an abbreviated name
    for narrow screens followed by the full one, each with position and team.
    The full name is what the rest of the pipeline matches on.
    """
    parts = cell.split()
    if len(parts) < 4:
        return None
    # The trailing "POS TEAM" closes the cell; the same pair appears after the
    # abbreviated name. Everything between them is the full name.
    if parts[-2].upper() != position.upper():
        return None
    team = parts[-1].upper()
    marker = [i for i, tok in enumerate(parts[:-2])
              if tok.upper() == position.upper() and i + 1 < len(parts)
              and parts[i + 1].upper() == team]
    if not marker:
        return None
    name = " ".join(parts[marker[0] + 2:-2]).strip()
    if not name:
        return None
    return name, team


def parse_cbs_table(table: List[List[str]], position: str) -> List[Player]:
    """Turn one parsed CBS stats table into players.

    ``table`` is the raw row list: a group-label row, then the real header, then
    the data. Columns are located by header text, so a site reordering them
    remaps correctly instead of silently shifting every stat by one.
    """
    header_row = None
    for index, row in enumerate(table[:4]):
        if row and norm(row[0]) == "player":
            header_row = index
            break
    if header_row is None:
        return []
    headers = [norm(cell) for cell in table[header_row]]
    columns = {stat: headers.index(key)
               for key, stat in _HEADER_STATS.items() if key in headers}
    if not columns:
        return []

    players: List[Player] = []
    for row in table[header_row + 1:]:
        if len(row) < len(headers) or not row[0]:
            continue
        identity = _player_identity(row[0], position)
        if identity is None:
            continue
        name, team = identity
        stats = {stat: to_float(row[i]) for stat, i in columns.items()}
        stats = {k: v for k, v in stats.items() if v}
        if not stats:
            continue
        players.append(Player(
            id=f"cbs:{norm(name)}:{position}",
            name=name,
            position=position,
            team=team,
            projections=stats,
            metadata={"projection_source": "CBS", "sources": ["cbs"]},
        ))
    return players


def fetch_cbs(season: int, position: str) -> List[Player]:
    html = fetch_html(CBS_URL.format(position=position, season=int(season)))
    table = largest_table(html)
    if table is None:
        raise RuntimeError(f"no projection table found for {position}")
    return parse_cbs_table(table, position)


def fetch_all_cbs(season: int) -> List[Player]:
    """Every position CBS projects, tolerating a single position's failure.

    One position's page breaking must not cost the whole source — that is how
    FFToday used to lose a consensus to a transient 500 on the QB page. Raises
    only if every position failed, which means the site changed shape.
    """
    players: List[Player] = []
    failures: List[str] = []
    for position in POSITIONS:
        try:
            found = fetch_cbs(season, position)
        except Exception as exc:
            failures.append(f"{position}: {exc}")
            continue
        if not found:
            failures.append(f"{position}: no rows parsed")
            continue
        players.extend(found)
    if not players:
        raise RuntimeError("CBS returned no players (" + "; ".join(failures) + ")")
    return players
