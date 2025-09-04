from __future__ import annotations
from typing import Dict


def fantasy_points(proj: Dict[str, float], scoring: Dict[str, float]) -> float:
    s = 0.0
    for stat, pts in scoring.items():
        s += float(proj.get(stat, 0.0)) * float(pts)
    return round(s, 2)

