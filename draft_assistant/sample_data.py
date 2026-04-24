"""Sample player data for demo and testing.

NOTE: This is a synthetic demo dataset. For a real draft, use:
  - `python -m draft_assistant.cli collect` (Sleeper API, requires network)
  - `python -m draft_assistant.cli import-fpros` (FantasyPros CSV)
  - `python -m draft_assistant.cli pull-fftoday` (FFToday scraper)

The dataset below is designed to exercise every new feature:
  - Multi-year historical stats (2022–2024 seasons)
  - Player age for age-curve adjustments
  - Team changes (previous_team set) to trigger transition penalty
  - Bye weeks for bye-stacking penalty
  - Injury history flags
"""
from __future__ import annotations
from typing import List

from .models import Player


def sample_players() -> List[Player]:
    return [
        # ---- QBs ----
        Player(
            id="allen_qb", name="Josh Allen", position="QB", team="BUF",
            bye_week=12, adp=22.1, age=30,
            projections={"pass_yd": 4200, "pass_td": 30, "pass_int": 10, "rush_yd": 550, "rush_td": 8, "fumbles": 4},
            historical_stats={
                2022: {"pass_yd": 4283, "pass_td": 35, "pass_int": 14, "rush_yd": 762, "rush_td": 7, "fumbles": 6},
                2023: {"pass_yd": 4306, "pass_td": 29, "pass_int": 18, "rush_yd": 524, "rush_td": 15, "fumbles": 9},
                2024: {"pass_yd": 3731, "pass_td": 28, "pass_int": 6, "rush_yd": 531, "rush_td": 12, "fumbles": 3},
            },
            experience=8,
        ),
        Player(
            id="hurts_qb", name="Jalen Hurts", position="QB", team="PHI",
            bye_week=7, adp=28.0, age=27,
            projections={"pass_yd": 3900, "pass_td": 26, "pass_int": 9, "rush_yd": 650, "rush_td": 12, "fumbles": 5},
            historical_stats={
                2022: {"pass_yd": 3701, "pass_td": 22, "pass_int": 6, "rush_yd": 760, "rush_td": 13, "fumbles": 9},
                2023: {"pass_yd": 3858, "pass_td": 23, "pass_int": 15, "rush_yd": 605, "rush_td": 15, "fumbles": 13},
                2024: {"pass_yd": 2903, "pass_td": 18, "pass_int": 5, "rush_yd": 630, "rush_td": 14, "fumbles": 4},
            },
            experience=6,
        ),
        Player(
            id="mahomes_qb", name="Patrick Mahomes", position="QB", team="KC",
            bye_week=10, adp=35.0, age=30,
            projections={"pass_yd": 4400, "pass_td": 30, "pass_int": 11, "rush_yd": 350, "rush_td": 3, "fumbles": 4},
            historical_stats={
                2022: {"pass_yd": 5250, "pass_td": 41, "pass_int": 12, "rush_yd": 358, "rush_td": 4, "fumbles": 4},
                2023: {"pass_yd": 4183, "pass_td": 27, "pass_int": 14, "rush_yd": 389, "rush_td": 0, "fumbles": 5},
                2024: {"pass_yd": 3928, "pass_td": 26, "pass_int": 11, "rush_yd": 307, "rush_td": 2, "fumbles": 4},
            },
            experience=9,
        ),
        Player(
            id="daniels_qb", name="Jayden Daniels", position="QB", team="WAS",
            bye_week=14, adp=30.0, age=25,
            projections={"pass_yd": 3800, "pass_td": 24, "pass_int": 10, "rush_yd": 700, "rush_td": 8, "fumbles": 5},
            historical_stats={
                2024: {"pass_yd": 3568, "pass_td": 25, "pass_int": 9, "rush_yd": 891, "rush_td": 6, "fumbles": 5},
            },
            experience=2,
        ),
        Player(
            id="burrow_qb", name="Joe Burrow", position="QB", team="CIN",
            bye_week=10, adp=40.0, age=29,
            projections={"pass_yd": 4500, "pass_td": 35, "pass_int": 12, "rush_yd": 200, "rush_td": 2, "fumbles": 4},
            historical_stats={
                2022: {"pass_yd": 4475, "pass_td": 35, "pass_int": 12, "rush_yd": 257, "rush_td": 5, "fumbles": 9},
                2023: {"pass_yd": 2309, "pass_td": 15, "pass_int": 6, "rush_yd": 106, "rush_td": 0, "fumbles": 2},
                2024: {"pass_yd": 4918, "pass_td": 43, "pass_int": 9, "rush_yd": 201, "rush_td": 2, "fumbles": 5},
            },
            experience=6,
            injury_history=["wrist (2023)"],
        ),

        # ---- RBs ----
        Player(
            id="cmc_rb", name="Christian McCaffrey", position="RB", team="SF",
            bye_week=14, adp=18.0, age=30,
            projections={"rush_yd": 1050, "rush_td": 9, "rec": 65, "rec_yd": 520, "rec_td": 4, "fumbles": 2},
            historical_stats={
                2022: {"rush_yd": 1139, "rush_td": 8, "rec": 85, "rec_yd": 741, "rec_td": 5, "fumbles": 1},
                2023: {"rush_yd": 1459, "rush_td": 14, "rec": 67, "rec_yd": 564, "rec_td": 7, "fumbles": 2},
                2024: {"rush_yd": 202, "rush_td": 0, "rec": 15, "rec_yd": 146, "rec_td": 1, "fumbles": 0},
            },
            experience=9,
            injury_history=["calf (2024)", "achilles (2024)"],
        ),
        Player(
            id="bijan_rb", name="Bijan Robinson", position="RB", team="ATL",
            bye_week=5, adp=2.5, age=24,
            projections={"rush_yd": 1400, "rush_td": 12, "rec": 60, "rec_yd": 520, "rec_td": 3, "fumbles": 2},
            historical_stats={
                2023: {"rush_yd": 976, "rush_td": 4, "rec": 58, "rec_yd": 487, "rec_td": 4, "fumbles": 2},
                2024: {"rush_yd": 1456, "rush_td": 14, "rec": 61, "rec_yd": 431, "rec_td": 1, "fumbles": 3},
            },
            experience=3,
        ),
        Player(
            id="hall_rb", name="Breece Hall", position="RB", team="NYJ",
            bye_week=12, adp=14.0, age=25,
            projections={"rush_yd": 1100, "rush_td": 8, "rec": 55, "rec_yd": 450, "rec_td": 3, "fumbles": 2},
            historical_stats={
                2022: {"rush_yd": 463, "rush_td": 4, "rec": 19, "rec_yd": 218, "rec_td": 1, "fumbles": 0},
                2023: {"rush_yd": 994, "rush_td": 5, "rec": 76, "rec_yd": 591, "rec_td": 4, "fumbles": 1},
                2024: {"rush_yd": 876, "rush_td": 5, "rec": 57, "rec_yd": 483, "rec_td": 3, "fumbles": 2},
            },
            experience=4,
            injury_history=["ACL (2022)"],
        ),
        Player(
            id="henry_rb", name="Derrick Henry", position="RB", team="BAL",
            bye_week=7, adp=12.0, age=32,
            previous_team="TEN",
            projections={"rush_yd": 1250, "rush_td": 13, "rec": 20, "rec_yd": 160, "rec_td": 1, "fumbles": 2},
            historical_stats={
                2022: {"rush_yd": 1538, "rush_td": 13, "rec": 33, "rec_yd": 398, "rec_td": 0, "fumbles": 5},
                2023: {"rush_yd": 1167, "rush_td": 12, "rec": 28, "rec_yd": 214, "rec_td": 0, "fumbles": 2},
                2024: {"rush_yd": 1921, "rush_td": 16, "rec": 19, "rec_yd": 193, "rec_td": 2, "fumbles": 3},
            },
            experience=10,
        ),
        Player(
            id="saquon_rb", name="Saquon Barkley", position="RB", team="PHI",
            bye_week=7, adp=3.0, age=29,
            projections={"rush_yd": 1500, "rush_td": 12, "rec": 35, "rec_yd": 290, "rec_td": 2, "fumbles": 2},
            historical_stats={
                2022: {"rush_yd": 1312, "rush_td": 10, "rec": 57, "rec_yd": 338, "rec_td": 0, "fumbles": 2},
                2023: {"rush_yd": 962, "rush_td": 6, "rec": 41, "rec_yd": 280, "rec_td": 4, "fumbles": 2},
                2024: {"rush_yd": 2005, "rush_td": 13, "rec": 33, "rec_yd": 278, "rec_td": 2, "fumbles": 2},
            },
            experience=8,
        ),
        Player(
            id="jacobs_rb", name="Josh Jacobs", position="RB", team="GB",
            bye_week=5, adp=20.0, age=28,
            projections={"rush_yd": 1200, "rush_td": 10, "rec": 40, "rec_yd": 320, "rec_td": 2, "fumbles": 2},
            historical_stats={
                2022: {"rush_yd": 1653, "rush_td": 12, "rec": 53, "rec_yd": 400, "rec_td": 0, "fumbles": 2},
                2023: {"rush_yd": 805, "rush_td": 6, "rec": 37, "rec_yd": 296, "rec_td": 0, "fumbles": 2},
                2024: {"rush_yd": 1329, "rush_td": 15, "rec": 36, "rec_yd": 342, "rec_td": 1, "fumbles": 3},
            },
            experience=7,
        ),
        Player(
            id="pacheco_rb", name="Isiah Pacheco", position="RB", team="KC",
            bye_week=10, adp=48.0, age=27,
            projections={"rush_yd": 900, "rush_td": 7, "rec": 30, "rec_yd": 220, "rec_td": 1, "fumbles": 2},
            historical_stats={
                2022: {"rush_yd": 830, "rush_td": 5, "rec": 13, "rec_yd": 130, "rec_td": 1, "fumbles": 3},
                2023: {"rush_yd": 935, "rush_td": 7, "rec": 44, "rec_yd": 244, "rec_td": 2, "fumbles": 2},
                2024: {"rush_yd": 310, "rush_td": 1, "rec": 20, "rec_yd": 153, "rec_td": 1, "fumbles": 0},
            },
            experience=4,
            injury_history=["fibula (2024)"],
        ),
        Player(
            id="achane_rb", name="De'Von Achane", position="RB", team="MIA",
            bye_week=6, adp=16.0, age=24,
            projections={"rush_yd": 1000, "rush_td": 7, "rec": 70, "rec_yd": 550, "rec_td": 3, "fumbles": 2},
            historical_stats={
                2023: {"rush_yd": 800, "rush_td": 8, "rec": 27, "rec_yd": 197, "rec_td": 3, "fumbles": 1},
                2024: {"rush_yd": 907, "rush_td": 6, "rec": 78, "rec_yd": 592, "rec_td": 1, "fumbles": 2},
            },
            experience=3,
        ),

        # ---- WRs ----
        Player(
            id="lamb_wr", name="CeeDee Lamb", position="WR", team="DAL",
            bye_week=7, adp=4.0, age=27,
            projections={"rec": 110, "rec_yd": 1450, "rec_td": 9, "rush_yd": 65, "rush_td": 1, "fumbles": 1},
            historical_stats={
                2022: {"rec": 107, "rec_yd": 1359, "rec_td": 9, "rush_yd": 82, "rush_td": 1, "fumbles": 1},
                2023: {"rec": 135, "rec_yd": 1749, "rec_td": 12, "rush_yd": 113, "rush_td": 2, "fumbles": 2},
                2024: {"rec": 101, "rec_yd": 1194, "rec_td": 6, "rush_yd": 44, "rush_td": 0, "fumbles": 1},
            },
            experience=6,
        ),
        Player(
            id="chase_wr", name="Ja'Marr Chase", position="WR", team="CIN",
            bye_week=10, adp=1.5, age=26,
            projections={"rec": 115, "rec_yd": 1500, "rec_td": 12, "rush_yd": 40, "rush_td": 0, "fumbles": 1},
            historical_stats={
                2022: {"rec": 87, "rec_yd": 1046, "rec_td": 9, "rush_yd": 28, "rush_td": 0, "fumbles": 1},
                2023: {"rec": 100, "rec_yd": 1216, "rec_td": 7, "rush_yd": 50, "rush_td": 0, "fumbles": 1},
                2024: {"rec": 127, "rec_yd": 1708, "rec_td": 17, "rush_yd": 32, "rush_td": 0, "fumbles": 1},
            },
            experience=5,
        ),
        Player(
            id="ars_wr", name="Amon-Ra St. Brown", position="WR", team="DET",
            bye_week=8, adp=9.0, age=26,
            projections={"rec": 110, "rec_yd": 1300, "rec_td": 10, "rush_yd": 30, "rush_td": 0, "fumbles": 1},
            historical_stats={
                2022: {"rec": 106, "rec_yd": 1161, "rec_td": 6, "rush_yd": 31, "rush_td": 0, "fumbles": 2},
                2023: {"rec": 119, "rec_yd": 1515, "rec_td": 10, "rush_yd": 30, "rush_td": 1, "fumbles": 1},
                2024: {"rec": 115, "rec_yd": 1263, "rec_td": 12, "rush_yd": 37, "rush_td": 0, "fumbles": 0},
            },
            experience=5,
        ),
        Player(
            id="jefferson_wr", name="Justin Jefferson", position="WR", team="MIN",
            bye_week=6, adp=5.0, age=27,
            projections={"rec": 115, "rec_yd": 1550, "rec_td": 9, "rush_yd": 20, "rush_td": 0, "fumbles": 1},
            historical_stats={
                2022: {"rec": 128, "rec_yd": 1809, "rec_td": 8, "rush_yd": 0, "rush_td": 0, "fumbles": 1},
                2023: {"rec": 68, "rec_yd": 1074, "rec_td": 5, "rush_yd": 0, "rush_td": 0, "fumbles": 1},
                2024: {"rec": 103, "rec_yd": 1533, "rec_td": 10, "rush_yd": 0, "rush_td": 0, "fumbles": 0},
            },
            experience=6,
            injury_history=["hamstring (2023)"],
        ),
        Player(
            id="nabers_wr", name="Malik Nabers", position="WR", team="NYG",
            bye_week=11, adp=15.0, age=22,
            projections={"rec": 100, "rec_yd": 1150, "rec_td": 7, "rush_yd": 15, "rush_td": 0, "fumbles": 1},
            historical_stats={
                2024: {"rec": 109, "rec_yd": 1204, "rec_td": 7, "rush_yd": 0, "rush_td": 0, "fumbles": 1},
            },
            experience=2,
        ),
        Player(
            id="adams_wr", name="Davante Adams", position="WR", team="LAR",
            bye_week=6, adp=42.0, age=33,
            previous_team="NYJ",
            projections={"rec": 85, "rec_yd": 1050, "rec_td": 8, "rush_yd": 0, "rush_td": 0, "fumbles": 1},
            historical_stats={
                2022: {"rec": 100, "rec_yd": 1516, "rec_td": 14, "rush_yd": 0, "rush_td": 0, "fumbles": 1},
                2023: {"rec": 103, "rec_yd": 1144, "rec_td": 8, "rush_yd": 0, "rush_td": 0, "fumbles": 1},
                2024: {"rec": 85, "rec_yd": 1063, "rec_td": 8, "rush_yd": 0, "rush_td": 0, "fumbles": 1},
            },
            experience=12,
        ),
        Player(
            id="hill_wr", name="Tyreek Hill", position="WR", team="MIA",
            bye_week=6, adp=24.0, age=32,
            projections={"rec": 95, "rec_yd": 1300, "rec_td": 8, "rush_yd": 40, "rush_td": 0, "fumbles": 1},
            historical_stats={
                2022: {"rec": 119, "rec_yd": 1710, "rec_td": 7, "rush_yd": 32, "rush_td": 1, "fumbles": 0},
                2023: {"rec": 119, "rec_yd": 1799, "rec_td": 13, "rush_yd": 51, "rush_td": 0, "fumbles": 1},
                2024: {"rec": 81, "rec_yd": 959, "rec_td": 6, "rush_yd": 22, "rush_td": 0, "fumbles": 1},
            },
            experience=10,
        ),
        Player(
            id="wilson_wr", name="Garrett Wilson", position="WR", team="NYJ",
            bye_week=12, adp=18.0, age=25,
            projections={"rec": 100, "rec_yd": 1150, "rec_td": 7, "rush_yd": 0, "rush_td": 0, "fumbles": 1},
            historical_stats={
                2022: {"rec": 83, "rec_yd": 1103, "rec_td": 4, "rush_yd": 0, "rush_td": 0, "fumbles": 1},
                2023: {"rec": 95, "rec_yd": 1042, "rec_td": 3, "rush_yd": 0, "rush_td": 0, "fumbles": 1},
                2024: {"rec": 101, "rec_yd": 1104, "rec_td": 7, "rush_yd": 0, "rush_td": 0, "fumbles": 0},
            },
            experience=4,
        ),
        Player(
            id="brown_wr", name="A.J. Brown", position="WR", team="PHI",
            bye_week=7, adp=13.0, age=28,
            projections={"rec": 90, "rec_yd": 1300, "rec_td": 9, "rush_yd": 0, "rush_td": 0, "fumbles": 1},
            historical_stats={
                2022: {"rec": 88, "rec_yd": 1496, "rec_td": 11, "rush_yd": 0, "rush_td": 0, "fumbles": 1},
                2023: {"rec": 106, "rec_yd": 1456, "rec_td": 7, "rush_yd": 0, "rush_td": 0, "fumbles": 1},
                2024: {"rec": 67, "rec_yd": 1079, "rec_td": 7, "rush_yd": 0, "rush_td": 0, "fumbles": 1},
            },
            experience=7,
        ),

        # ---- TEs ----
        Player(
            id="kelce_te", name="Travis Kelce", position="TE", team="KC",
            bye_week=10, adp=55.0, age=36,
            projections={"rec": 75, "rec_yd": 800, "rec_td": 5, "rush_yd": 0, "rush_td": 0, "fumbles": 1},
            historical_stats={
                2022: {"rec": 110, "rec_yd": 1338, "rec_td": 12, "rush_yd": 0, "rush_td": 0, "fumbles": 2},
                2023: {"rec": 93, "rec_yd": 984, "rec_td": 5, "rush_yd": 0, "rush_td": 0, "fumbles": 1},
                2024: {"rec": 97, "rec_yd": 823, "rec_td": 3, "rush_yd": 0, "rush_td": 0, "fumbles": 1},
            },
            experience=13,
        ),
        Player(
            id="laporta_te", name="Sam LaPorta", position="TE", team="DET",
            bye_week=8, adp=48.0, age=24,
            projections={"rec": 80, "rec_yd": 900, "rec_td": 8, "rush_yd": 0, "rush_td": 0, "fumbles": 1},
            historical_stats={
                2023: {"rec": 86, "rec_yd": 889, "rec_td": 10, "rush_yd": 0, "rush_td": 0, "fumbles": 1},
                2024: {"rec": 60, "rec_yd": 726, "rec_td": 7, "rush_yd": 0, "rush_td": 0, "fumbles": 0},
            },
            experience=3,
        ),
        Player(
            id="bowers_te", name="Brock Bowers", position="TE", team="LV",
            bye_week=8, adp=25.0, age=23,
            projections={"rec": 100, "rec_yd": 1100, "rec_td": 7, "rush_yd": 0, "rush_td": 0, "fumbles": 1},
            historical_stats={
                2024: {"rec": 112, "rec_yd": 1194, "rec_td": 5, "rush_yd": 0, "rush_td": 0, "fumbles": 1},
            },
            experience=2,
        ),
        Player(
            id="mcbride_te", name="Trey McBride", position="TE", team="ARI",
            bye_week=11, adp=45.0, age=26,
            projections={"rec": 90, "rec_yd": 900, "rec_td": 5, "rush_yd": 0, "rush_td": 0, "fumbles": 1},
            historical_stats={
                2023: {"rec": 81, "rec_yd": 825, "rec_td": 3, "rush_yd": 0, "rush_td": 0, "fumbles": 1},
                2024: {"rec": 111, "rec_yd": 1146, "rec_td": 2, "rush_yd": 0, "rush_td": 0, "fumbles": 1},
            },
            experience=4,
        ),
        Player(
            id="andrews_te", name="Mark Andrews", position="TE", team="BAL",
            bye_week=7, adp=78.0, age=30,
            projections={"rec": 65, "rec_yd": 750, "rec_td": 7, "rush_yd": 0, "rush_td": 0, "fumbles": 1},
            historical_stats={
                2022: {"rec": 73, "rec_yd": 847, "rec_td": 5, "rush_yd": 0, "rush_td": 0, "fumbles": 1},
                2023: {"rec": 45, "rec_yd": 544, "rec_td": 6, "rush_yd": 0, "rush_td": 0, "fumbles": 0},
                2024: {"rec": 55, "rec_yd": 673, "rec_td": 11, "rush_yd": 0, "rush_td": 0, "fumbles": 0},
            },
            experience=8,
            injury_history=["ankle (2023)"],
        ),

        # ---- Kickers ----
        Player(
            id="tucker_k", name="Justin Tucker", position="K", team="BAL",
            bye_week=7, adp=150.0, age=36,
            projections={"pat_made": 38, "fg_0_39": 15, "fg_40_49": 10, "fg_50_59": 5, "fg_60_plus": 0, "fg_miss": 3},
        ),
        Player(
            id="mcmanus_k", name="Brandon McManus", position="K", team="GB",
            bye_week=5, adp=155.0, age=34,
            projections={"pat_made": 40, "fg_0_39": 14, "fg_40_49": 9, "fg_50_59": 4, "fg_60_plus": 0, "fg_miss": 3},
        ),

        # ---- Defenses ----
        Player(
            id="dst_bal", name="Baltimore Ravens", position="DST", team="BAL",
            bye_week=7, adp=135.0,
            projections={"sack": 45, "def_int": 16, "fumble_recovery": 10, "safety": 1, "int_ret_td": 3, "fum_ret_td": 1},
        ),
        Player(
            id="dst_phi", name="Philadelphia Eagles", position="DST", team="PHI",
            bye_week=7, adp=140.0,
            projections={"sack": 42, "def_int": 14, "fumble_recovery": 9, "safety": 1, "int_ret_td": 2, "fum_ret_td": 1},
        ),
        Player(
            id="dst_den", name="Denver Broncos", position="DST", team="DEN",
            bye_week=14, adp=138.0,
            projections={"sack": 46, "def_int": 12, "fumble_recovery": 8, "safety": 1, "int_ret_td": 2, "fum_ret_td": 1},
        ),
    ]
