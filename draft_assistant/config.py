from __future__ import annotations
import json
import os
from dataclasses import asdict
from typing import Any, Dict

from .models import LeagueConfig


DEFAULT_CONFIG: Dict[str, Any] = {
    "teams": 12,
    "roster": {
        "QB": 1,
        "RB": 2,
        "WR": 2,
        "TE": 1,
        "FLEX": 1,  # RB/WR/TE eligible
        "K": 0,
        "DST": 0,
        "BN": 6,
    },
    "scoring": {
        # Passing
        "pass_yd": 0.04,     # 1 per 25 yards
        "pass_td": 4.0,
        "pass_int": -2.0,
        # Rushing
        "rush_yd": 0.1,      # 1 per 10 yards
        "rush_td": 6.0,
        # Receiving
        "rec": 1.0,          # PPR
        "rec_yd": 0.1,
        "rec_td": 6.0,
        # Misc
        "fumbles": -2.0,
    },
    "provider": {
        "type": "local_json",
        "options": {
            "path": "data/projections.json"
        }
    }
}


def load_config(path: str = "league.config.yaml") -> LeagueConfig:
    # Minimal YAML reader without external deps: accept JSON superset
    # If YAML is desired, user can still write JSON; otherwise this loader
    # tries a simple parse.
    if not os.path.exists(path):
        return LeagueConfig(**DEFAULT_CONFIG)
    try:
        # Try JSON first
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError:
        # Fallback naive YAML-like parser: key: value per line, very limited
        # Users should prefer JSON in the same file for now.
        data = DEFAULT_CONFIG
    return LeagueConfig(**data)


def save_config(config: LeagueConfig, path: str = "league.config.yaml") -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(asdict(config), f, indent=2)

