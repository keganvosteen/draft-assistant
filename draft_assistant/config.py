from __future__ import annotations
import json
import os
import sys
from dataclasses import asdict
from typing import Any, Dict

from .models import LeagueConfig
from .storage import atomic_write_json


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
    },
    "draft": {
        "slot": 1,
        "snake": True,
        "monte_carlo_sims": 250,
        "adp_noise": 8.0,
        "candidate_pool": 120
    }
}


def load_config(path: str = "league.config.yaml") -> LeagueConfig:
    # The config file is JSON (despite the historical .yaml extension).
    if not os.path.exists(path):
        return LeagueConfig(**_defaults_copy())
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as exc:
        print(
            f"WARNING: could not parse {path} as JSON ({exc}). "
            "Falling back to DEFAULT league settings — your teams/scoring/roster "
            "are NOT being used. Fix the file (it must be valid JSON).",
            file=sys.stderr,
        )
        data = {}
    if not isinstance(data, dict):
        print(
            f"WARNING: {path} must contain a JSON object; using default league settings.",
            file=sys.stderr,
        )
        data = {}

    unknown = sorted(set(data) - set(DEFAULT_CONFIG))
    if unknown:
        print(
            f"WARNING: ignoring unknown keys in {path}: {', '.join(unknown)}",
            file=sys.stderr,
        )

    merged = _defaults_copy()
    for key in DEFAULT_CONFIG:
        if key in data:
            merged[key] = data[key]
    return LeagueConfig(**merged)


def _defaults_copy() -> Dict[str, Any]:
    return {
        key: dict(value) if isinstance(value, dict) else value
        for key, value in DEFAULT_CONFIG.items()
    }


def save_config(config: LeagueConfig, path: str = "league.config.yaml") -> None:
    atomic_write_json(path, asdict(config))

