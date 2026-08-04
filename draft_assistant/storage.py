from __future__ import annotations
import json
import os
import tempfile
import threading
import warnings
from typing import Callable, List

from .models import DraftState, Player


_locks_guard = threading.Lock()
_path_locks: dict[str, threading.RLock] = {}


def _lock_for(path: str) -> threading.RLock:
    normalized = os.path.normcase(os.path.abspath(os.fspath(path)))
    with _locks_guard:
        return _path_locks.setdefault(normalized, threading.RLock())


def atomic_write_json(path: str, payload: object) -> None:
    """Write JSON via a temp file + rename so a crash mid-write can't leave a
    corrupt file behind (draft state is saved after every live pick)."""
    path = os.fspath(path)
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    with _lock_for(path):
        fd, tmp_path = tempfile.mkstemp(dir=directory, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, path)
        except BaseException:
            try:
                os.remove(tmp_path)
            except OSError:
                pass
            raise


def save_state(state: DraftState, path: str = "draft_state.json") -> None:
    atomic_write_json(path, {
        "my_team_name": state.my_team_name,
        "league_teams": state.league_teams,
        "picks": state.picks,
        "my_picks": state.my_picks,
    })


def load_state(path: str = "draft_state.json") -> DraftState:
    path = os.fspath(path)
    with _lock_for(path):
        if not os.path.exists(path):
            return _default_state()
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return _state_from_dict(data)
        except (json.JSONDecodeError, UnicodeError, ValueError, TypeError) as exc:
            backup = _corrupt_backup_path(path)
            os.replace(path, backup)
            warnings.warn(
                f"Invalid draft state moved to {backup}: {exc}", RuntimeWarning,
                stacklevel=2,
            )
            return _default_state()


def update_state(
    path: str, mutator: Callable[[DraftState], None]
) -> DraftState:
    """Atomically apply a read-modify-write state update for one profile."""
    with _lock_for(path):
        state = load_state(path)
        mutator(state)
        # Validate before replacing the last known-good state.
        _state_from_dict({
            "my_team_name": state.my_team_name,
            "league_teams": state.league_teams,
            "picks": state.picks,
            "my_picks": state.my_picks,
        })
        save_state(state, path)
        return state


def _default_state() -> DraftState:
    return DraftState(
        my_team_name="My Team",
        league_teams=[f"Team {i + 1}" for i in range(12)],
    )


def _state_from_dict(data: object) -> DraftState:
    if not isinstance(data, dict):
        raise ValueError("draft state must be a JSON object")

    def string_list(key: str, default: List[str], maximum: int) -> List[str]:
        value = data.get(key, default)
        if (not isinstance(value, list) or len(value) > maximum
                or not all(isinstance(item, str) and len(item) <= 256 for item in value)):
            raise ValueError(f"{key} must be a list of at most {maximum} short strings")
        return list(value)

    name = data.get("my_team_name", "My Team")
    if not isinstance(name, str) or len(name) > 200:
        raise ValueError("my_team_name must be a short string")
    teams = string_list(
        "league_teams", [f"Team {i + 1}" for i in range(12)], 32)
    picks = string_list("picks", [], 1024)
    my_picks = string_list("my_picks", [], 1024)
    return DraftState(name, teams, picks, my_picks)


def _corrupt_backup_path(path: str) -> str:
    candidate = f"{path}.corrupt"
    index = 1
    while os.path.exists(candidate):
        candidate = f"{path}.corrupt.{index}"
        index += 1
    return candidate


def _player_to_dict(p: Player) -> dict:
    d = {
        "id": p.id,
        "name": p.name,
        "position": p.position,
        "team": p.team,
        "bye_week": p.bye_week,
        "adp": p.adp,
        "projections": p.projections,
    }
    if p.age is not None:
        d["age"] = p.age
    if p.experience is not None:
        d["experience"] = p.experience
    if p.historical_stats:
        d["historical_stats"] = {str(k): v for k, v in p.historical_stats.items()}
    if p.previous_team:
        d["previous_team"] = p.previous_team
    if p.draft_capital:
        d["draft_capital"] = p.draft_capital
    if p.injury_history:
        d["injury_history"] = p.injury_history
    if p.metadata:
        d["metadata"] = p.metadata
    return d


def _player_from_dict(raw: dict) -> Player:
    hist_raw = raw.get("historical_stats", {})
    historical: dict = {}
    if isinstance(hist_raw, dict):
        for k, v in hist_raw.items():
            try:
                historical[int(k)] = v
            except (ValueError, TypeError):
                pass
    return Player(
        id=str(raw.get("id", raw.get("name"))),
        name=raw.get("name", ""),
        position=raw.get("position", ""),
        team=raw.get("team"),
        bye_week=raw.get("bye_week"),
        adp=raw.get("adp"),
        projections=raw.get("projections", {}),
        age=raw.get("age"),
        experience=raw.get("experience"),
        historical_stats=historical,
        previous_team=raw.get("previous_team"),
        draft_capital=raw.get("draft_capital"),
        injury_history=raw.get("injury_history", []),
        metadata=raw.get("metadata", {}),
    )


def save_players(players: List[Player], path: str = "data/projections.json") -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    atomic_write_json(path, {"players": [_player_to_dict(p) for p in players]})


def update_players(
    path: str, updater: Callable[[List[Player]], List[Player]]
) -> List[Player]:
    """Atomically merge a newly collected board with the latest on-disk board."""
    with _lock_for(path):
        players = updater(load_players(path))
        save_players(players, path)
        return players


def load_players(path: str = "data/projections.json") -> List[Player]:
    """Load players directly from JSON (bypasses provider)."""
    with _lock_for(path):
        if not os.path.exists(path):
            return []
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict) or not isinstance(data.get("players", []), list):
            raise ValueError("projection file must contain a players list")
        return [_player_from_dict(p) for p in data.get("players", [])]
