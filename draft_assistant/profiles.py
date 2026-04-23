from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List

from .config import DEFAULT_CONFIG, load_config, save_config
from .models import DraftState, LeagueConfig
from .storage import save_players, save_state

DEFAULT_PROFILE = "default"
PROFILE_ROOT = Path(".draft_assistant_profiles")


@dataclass(frozen=True)
class ProfilePaths:
    profile: str
    base_dir: str
    config_path: str
    state_path: str
    projections_path: str


def normalize_profile_name(name: str) -> str:
    raw = (name or DEFAULT_PROFILE).strip()
    if not raw:
        return DEFAULT_PROFILE
    if raw.lower() == DEFAULT_PROFILE:
        return DEFAULT_PROFILE
    safe = re.sub(r"[^a-zA-Z0-9_-]+", "-", raw).strip("-_").lower()
    if not safe:
        raise ValueError("Profile name must contain letters or numbers.")
    return safe


def get_profile_paths(name: str) -> ProfilePaths:
    profile = normalize_profile_name(name)
    if profile == DEFAULT_PROFILE:
        return ProfilePaths(
            profile=DEFAULT_PROFILE,
            base_dir=".",
            config_path="league.config.yaml",
            state_path="draft_state.json",
            projections_path="data/projections.json",
        )
    base = PROFILE_ROOT / profile
    data_dir = base / "data"
    return ProfilePaths(
        profile=profile,
        base_dir=os.fspath(base),
        config_path=os.fspath(base / "league.config.yaml"),
        state_path=os.fspath(base / "draft_state.json"),
        projections_path=os.fspath(data_dir / "projections.json"),
    )


def list_profiles() -> List[str]:
    profiles = [DEFAULT_PROFILE]
    if PROFILE_ROOT.exists():
        for child in PROFILE_ROOT.iterdir():
            if child.is_dir():
                profiles.append(child.name)
    seen = set()
    ordered: List[str] = []
    for p in profiles:
        if p in seen:
            continue
        seen.add(p)
        ordered.append(p)
    return ordered


def _default_state(teams: int) -> DraftState:
    return DraftState(
        my_team_name="My Team",
        league_teams=[f"Team {i+1}" for i in range(max(1, teams))],
        picks=[],
        my_picks=[],
    )


def ensure_profile(name: str) -> ProfilePaths:
    paths = get_profile_paths(name)
    if paths.profile != DEFAULT_PROFILE:
        os.makedirs(paths.base_dir, exist_ok=True)
        os.makedirs(os.path.dirname(paths.projections_path), exist_ok=True)

    config_exists = os.path.exists(paths.config_path)
    if config_exists:
        cfg = load_config(paths.config_path)
    else:
        cfg = LeagueConfig(**DEFAULT_CONFIG)
        cfg.provider = {"type": "local_json", "options": {"path": paths.projections_path}}
        save_config(cfg, paths.config_path)

    if not os.path.exists(paths.state_path):
        save_state(_default_state(cfg.teams), paths.state_path)

    if not os.path.exists(paths.projections_path):
        save_players([], paths.projections_path)

    # Keep local_json profiles isolated by default.
    provider = cfg.provider or {}
    if provider.get("type", "local_json") == "local_json":
        opts = dict(provider.get("options", {}) or {})
        if opts.get("path") != paths.projections_path:
            opts["path"] = paths.projections_path
            cfg.provider = {"type": "local_json", "options": opts}
            save_config(cfg, paths.config_path)

    return paths


def load_profile_config(paths: ProfilePaths) -> LeagueConfig:
    cfg = load_config(paths.config_path)
    provider = cfg.provider or {}
    ptype = provider.get("type", "local_json")
    if ptype == "local_json":
        opts = dict(provider.get("options", {}) or {})
        opts.setdefault("path", paths.projections_path)
        cfg.provider = {"type": "local_json", "options": opts}
    return cfg


def save_profile_config(config: LeagueConfig, paths: ProfilePaths) -> None:
    provider = config.provider or {}
    if provider.get("type", "local_json") == "local_json":
        opts = dict(provider.get("options", {}) or {})
        opts.setdefault("path", paths.projections_path)
        config.provider = {"type": "local_json", "options": opts}
    save_config(config, paths.config_path)
