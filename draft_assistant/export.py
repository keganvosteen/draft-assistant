from __future__ import annotations
import csv
from typing import Iterable, List

from .models import Player


CSV_HEADERS = [
    "id", "name", "position", "team", "bye_week", "adp",
    # Passing
    "pass_yd", "pass_td", "pass_int", "pass_2pt",
    # Rushing
    "rush_yd", "rush_td", "rush_2pt",
    # Receiving
    "rec", "rec_yd", "rec_td", "rec_2pt",
    # Fumbles
    "fumbles",
    # Kicker
    "pat_made", "fg_miss", "fg_0_39", "fg_40_49", "fg_50_59", "fg_60_plus",
    # Defense/ST core stats
    "sack", "blk_kick", "def_int", "fumble_recovery", "safety",
    # Defense/ST TDs and returns
    "krt_td", "prt_td", "int_ret_td", "fum_ret_td", "blk_kick_ret_td", "two_pt_ret", "one_pt_safety",
]


def export_players_csv(players: Iterable[Player], path: str) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_HEADERS)
        w.writeheader()
        for p in players:
            row = {h: 0 for h in CSV_HEADERS}
            row["id"] = p.id
            row["name"] = p.name
            row["position"] = p.position
            row["team"] = p.team or ""
            row["bye_week"] = p.bye_week or ""
            row["adp"] = p.adp or ""
            for k, v in p.projections.items():
                if k in row:
                    row[k] = v
            w.writerow(row)

