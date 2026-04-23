from __future__ import annotations
import json
import os
from dataclasses import asdict
from typing import List

from .models import DraftState, LeagueConfig, Player


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


def save_players(players: List[Player], path: str = "data/projections.json") -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({
            "players": [
                {
                    "id": p.id,
                    "name": p.name,
                    "position": p.position,
                    "team": p.team,
                    "bye_week": p.bye_week,
                    "adp": p.adp,
                    "projections": p.projections,
                    "metadata": p.metadata,
                } for p in players
            ]
        }, f, indent=2)

