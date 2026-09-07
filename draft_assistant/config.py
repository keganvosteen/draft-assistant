from __future__ import annotations
import json
import os
import sys
from copy import deepcopy
from dataclasses import asdict
from typing import Any, Dict

from .models import LeagueConfig
from .storage import atomic_write_json


#: The league file has always held JSON.  It used to be named ``.yaml``, which
#: invited people to edit it as YAML — silently getting the defaults instead of
#: their league.  The extension now matches the format; the old name is still
#: read, and :func:`migrate_legacy_config` renames it in place.
CONFIG_FILENAME = "league.config.json"
LEGACY_CONFIG_FILENAME = "league.config.yaml"


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
        "rollout_sims": 48,
        "adp_noise": 8.0,
        "rollout_candidates": 16,
    }
}


def legacy_path_for(path: str) -> str:
    """The pre-rename ``.yaml`` sibling of a config path."""
    directory, name = os.path.split(os.fspath(path))
    if name != CONFIG_FILENAME:
        return ""
    return os.path.join(directory, LEGACY_CONFIG_FILENAME)


def migrate_legacy_config(path: str) -> bool:
    """Rename a leftover ``league.config.yaml`` onto ``path``.

    Returns True when a file was moved.  Keeping both names around would
    recreate the original trap in a new form — edits to the stale one would be
    ignored — so this moves rather than copies.
    """
    legacy = legacy_path_for(path)
    if not legacy or os.path.exists(path) or not os.path.exists(legacy):
        return False
    os.replace(legacy, path)
    print(f"Renamed {legacy} to {path} (it has always been JSON).", file=sys.stderr)
    return True


def load_config(path: str = CONFIG_FILENAME) -> LeagueConfig:
    # The league file is JSON. `.yaml` was the historical name; still read it so
    # an existing checkout or profile keeps working.
    if not os.path.exists(path):
        legacy = legacy_path_for(path)
        if legacy and os.path.exists(legacy):
            path = legacy
        else:
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
            if isinstance(merged[key], dict) and isinstance(data[key], dict):
                merged[key].update(data[key])
            else:
                merged[key] = data[key]

    # Backward-compatible migration from the pre-rollout option names. Keep
    # this at the config boundary so the engine has one unambiguous schema.
    draft = merged["draft"]
    raw_draft = data.get("draft") if isinstance(data.get("draft"), dict) else {}
    if "rollout_sims" not in raw_draft and "monte_carlo_sims" in raw_draft:
        draft["rollout_sims"] = raw_draft["monte_carlo_sims"]
    if "rollout_candidates" not in raw_draft and "candidate_pool" in raw_draft:
        draft["rollout_candidates"] = min(int(raw_draft["candidate_pool"]), 64)
    for obsolete in ("monte_carlo_sims", "candidate_pool", "snake"):
        draft.pop(obsolete, None)
    return LeagueConfig(**merged)


def _defaults_copy() -> Dict[str, Any]:
    return deepcopy(DEFAULT_CONFIG)


def save_config(config: LeagueConfig, path: str = CONFIG_FILENAME) -> None:
    atomic_write_json(path, asdict(config))

