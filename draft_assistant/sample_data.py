from __future__ import annotations
from typing import List

from .models import Player


def sample_players() -> List[Player]:
    return [
        Player(id="qb1", name="Josh Allen", position="QB", team="BUF", adp=10.5, projections={
            "pass_yd": 4400, "pass_td": 32, "pass_int": 12, "rush_yd": 600, "rush_td": 7, "rec": 0, "rec_yd": 0, "rec_td": 0, "fumbles": 5
        }),
        Player(id="qb2", name="Jalen Hurts", position="QB", team="PHI", adp=12.3, projections={
            "pass_yd": 4000, "pass_td": 26, "pass_int": 9, "rush_yd": 800, "rush_td": 10, "rec": 0, "rec_yd": 0, "rec_td": 0, "fumbles": 4
        }),
        Player(id="rb1", name="Christian McCaffrey", position="RB", team="SF", adp=1.2, projections={
            "rush_yd": 1300, "rush_td": 13, "rec": 75, "rec_yd": 650, "rec_td": 5, "pass_yd": 0, "pass_td": 0, "pass_int": 0, "fumbles": 2
        }),
        Player(id="rb2", name="Bijan Robinson", position="RB", team="ATL", adp=6.8, projections={
            "rush_yd": 1150, "rush_td": 10, "rec": 60, "rec_yd": 550, "rec_td": 4, "pass_yd": 0, "pass_td": 0, "pass_int": 0, "fumbles": 2
        }),
        Player(id="rb3", name="Breece Hall", position="RB", team="NYJ", adp=10.0, projections={
            "rush_yd": 1050, "rush_td": 8, "rec": 56, "rec_yd": 480, "rec_td": 3, "pass_yd": 0, "pass_td": 0, "pass_int": 0, "fumbles": 2
        }),
        Player(id="wr1", name="CeeDee Lamb", position="WR", team="DAL", adp=2.0, projections={
            "rec": 115, "rec_yd": 1500, "rec_td": 10, "rush_yd": 75, "rush_td": 1, "pass_yd": 0, "pass_td": 0, "pass_int": 0, "fumbles": 2
        }),
        Player(id="wr2", name="Ja'Marr Chase", position="WR", team="CIN", adp=3.0, projections={
            "rec": 105, "rec_yd": 1450, "rec_td": 12, "rush_yd": 50, "rush_td": 0, "pass_yd": 0, "pass_td": 0, "pass_int": 0, "fumbles": 1
        }),
        Player(id="wr3", name="Amon-Ra St. Brown", position="WR", team="DET", adp=5.0, projections={
            "rec": 110, "rec_yd": 1350, "rec_td": 8, "rush_yd": 40, "rush_td": 0, "pass_yd": 0, "pass_td": 0, "pass_int": 0, "fumbles": 1
        }),
        Player(id="te1", name="Travis Kelce", position="TE", team="KC", adp=18.0, projections={
            "rec": 95, "rec_yd": 1100, "rec_td": 9, "rush_yd": 0, "rush_td": 0, "pass_yd": 0, "pass_td": 0, "pass_int": 0, "fumbles": 1
        }),
        Player(id="te2", name="Sam LaPorta", position="TE", team="DET", adp=24.0, projections={
            "rec": 85, "rec_yd": 950, "rec_td": 8, "rush_yd": 0, "rush_td": 0, "pass_yd": 0, "pass_td": 0, "pass_int": 0, "fumbles": 1
        }),
    ]

