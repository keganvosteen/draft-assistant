from __future__ import annotations
import csv
import os
from typing import Dict, List, Optional

from ..models import Player


def _norm(s: str) -> str:
    return "".join(ch.lower() if ch.isalnum() else "_" for ch in s).strip("_")


def _get(row: Dict[str, str], names: List[str], default: float = 0.0) -> float:
    for n in names:
        key = n
        if key in row:
            try:
                return float(row[key]) if row[key] != "" else default
            except ValueError:
                continue
    # try normalized keys
    norm_row = { _norm(k): v for k, v in row.items() }
    for n in names:
        key = _norm(n)
        if key in norm_row:
            try:
                return float(norm_row[key]) if norm_row[key] != "" else default
            except ValueError:
                continue
    return default


def _get_str(row: Dict[str, str], names: List[str], default: str = "") -> str:
    for n in names:
        if n in row and row[n] != "":
            return str(row[n])
    norm_row = { _norm(k): v for k, v in row.items() }
    for n in names:
        key = _norm(n)
        if key in norm_row and norm_row[key] != "":
            return str(norm_row[key])
    return default


def load_offense_csv(path: str) -> List[Player]:
    players: List[Player] = []
    if not path or not os.path.exists(path):
        return players
    with open(path, newline='', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = _get_str(row, ["Player", "Name", "PLAYER"], "").strip()
            if not name:
                continue
            pos = _get_str(row, ["POS", "Position"], "").strip().upper()
            if pos not in {"QB", "RB", "WR", "TE"}:
                continue
            team = _get_str(row, ["Team", "Tm"], None)

            projections: Dict[str, float] = {}
            # Passing
            projections["pass_yd"] = _get(row, ["PASS YDS", "Pass Yds", "PY"], 0.0)
            projections["pass_td"] = _get(row, ["PASS TDS", "Pass TD", "PTD"], 0.0)
            projections["pass_int"] = _get(row, ["INT", "Ints"], 0.0)
            projections["pass_2pt"] = _get(row, ["2PC", "2PT Pass", "2PT Passing"], 0.0)
            # Rushing
            projections["rush_yd"] = _get(row, ["RUSH YDS", "Rush Yds", "RY"], 0.0)
            projections["rush_td"] = _get(row, ["RUSH TDS", "Rush TD", "RTD"], 0.0)
            projections["rush_2pt"] = _get(row, ["2PR", "2PT Rush", "2PT Rushing"], 0.0)
            # Receiving
            projections["rec"] = _get(row, ["REC", "Receptions"], 0.0)
            projections["rec_yd"] = _get(row, ["REC YDS", "Rec Yds", "REY"], 0.0)
            projections["rec_td"] = _get(row, ["REC TDS", "Rec TD", "RETD"], 0.0)
            projections["rec_2pt"] = _get(row, ["2PRE", "2PT Rec", "2PT Receiving"], 0.0)
            # Fumbles
            projections["fumbles"] = _get(row, ["FUMBLES", "Fumbles", "Fumbles Lost", "FL"], 0.0)

            players.append(Player(
                id=f"{name}|{pos}",
                name=name,
                position=pos,
                team=team if team else None,
                projections=projections,
            ))
    return players


def load_k_csv(path: str) -> List[Player]:
    players: List[Player] = []
    if not path or not os.path.exists(path):
        return players
    with open(path, newline='', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = _get_str(row, ["Player", "Name", "PLAYER"], "").strip()
            if not name:
                continue
            pos = "K"
            team = _get_str(row, ["Team", "Tm"], None)
            projections: Dict[str, float] = {}

            # PAT made
            projections["pat_made"] = _get(row, ["PAT", "XPM"], 0.0)

            # Field goals by range. FantasyPros sometimes splits 0-19, 20-29, 30-39.
            fg_0_19 = _get(row, ["FG 0-19", "0-19"], 0.0)
            fg_20_29 = _get(row, ["FG 20-29", "20-29"], 0.0)
            fg_30_39 = _get(row, ["FG 30-39", "30-39"], 0.0)
            projections["fg_0_39"] = fg_0_19 + fg_20_29 + fg_30_39

            projections["fg_40_49"] = _get(row, ["FG 40-49", "40-49"], 0.0)

            # 50+ may be split; map to 50-59 and 60+
            fg_50_plus = _get(row, ["FG 50+", "50+"], 0.0)
            fg_50_59 = _get(row, ["FG 50-59", "50-59"], 0.0)
            fg_60_plus = _get(row, ["FG 60+", "60+"], 0.0)
            if fg_50_59 or fg_60_plus:
                projections["fg_50_59"] = fg_50_59
                projections["fg_60_plus"] = fg_60_plus
            else:
                projections["fg_50_59"] = fg_50_plus
                projections["fg_60_plus"] = 0.0

            # Misses (optional): if attempts minus made available; else 0
            fga = _get(row, ["FGA", "FG Att"], 0.0)
            fgm_total = projections["fg_0_39"] + projections["fg_40_49"] + projections["fg_50_59"] + projections["fg_60_plus"]
            if fga > 0 and fga >= fgm_total:
                projections["fg_miss"] = fga - fgm_total
            else:
                projections["fg_miss"] = 0.0

            players.append(Player(
                id=f"{name}|{pos}",
                name=name,
                position=pos,
                team=team if team else None,
                projections=projections,
            ))
    return players


def load_dst_csv(path: str) -> List[Player]:
    players: List[Player] = []
    if not path or not os.path.exists(path):
        return players
    with open(path, newline='', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = _get_str(row, ["Team", "Name", "DEF"], "").strip()
            if not name:
                continue
            pos = "DST"
            team = name  # DST uses team name as player name
            projections: Dict[str, float] = {}

            projections["sack"] = _get(row, ["SACK", "Sacks", "Sk"], 0.0)
            projections["def_int"] = _get(row, ["INT", "Ints"], 0.0)
            projections["fumble_recovery"] = _get(row, ["FR", "Fumbles Recovered"], 0.0)
            projections["safety"] = _get(row, ["SAFETY", "Safeties"], 0.0)

            # TDs: if only total provided, put into INT return TD as a proxy
            tds_total = _get(row, ["TD", "TDs", "DEF TD"], 0.0)
            projections["int_ret_td"] = tds_total
            projections["fum_ret_td"] = 0.0
            projections["blk_kick_ret_td"] = 0.0
            projections["krt_td"] = 0.0
            projections["prt_td"] = 0.0

            players.append(Player(
                id=f"{team}|{pos}",
                name=team,
                position=pos,
                team=team,
                projections=projections,
            ))
    return players


def merge_players(*groups: List[Player]) -> List[Player]:
    merged: Dict[str, Player] = {}
    for group in groups:
        for p in group:
            key = p.key()
            if key in merged:
                # Merge projections, prefer non-zero values
                base = merged[key]
                base.projections.update({k: v for k, v in p.projections.items() if v})
            else:
                merged[key] = p
    return list(merged.values())

