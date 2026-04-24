from __future__ import annotations
import json
import os
from typing import List

from .models import DraftState, Player


def save_state(state: DraftState, path: str = "draft_state.json") -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump({
            "my_team_name": state.my_team_name,
            "league_teams": state.league_teams,
            "picks": state.picks,
            "my_picks": state.my_picks,
        }, f, indent=2)


def load_state(path: str = "draft_state.json") -> DraftState:
    if not os.path.exists(path):
        return DraftState(my_team_name="My Team", league_teams=[f"Team {i+1}" for i in range(12)])
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return DraftState(
        my_team_name=data.get("my_team_name", "My Team"),
        league_teams=data.get("league_teams", [f"Team {i+1}" for i in range(12)]),
        picks=data.get("picks", []),
        my_picks=data.get("my_picks", []),
    )


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
    with open(path, "w", encoding="utf-8") as f:
        json.dump(
            {"players": [_player_to_dict(p) for p in players]},
            f,
            indent=2,
        )


def load_players(path: str = "data/projections.json") -> List[Player]:
    """Load players directly from JSON (bypasses provider)."""
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return [_player_from_dict(p) for p in data.get("players", [])]
