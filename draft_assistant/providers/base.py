from __future__ import annotations
from typing import Dict, List

from ..models import Player


class Provider:
    def fetch_players(self) -> List[Player]:
        raise NotImplementedError

    def name(self) -> str:
        return self.__class__.__name__


class LocalJsonProvider(Provider):
    def __init__(self, path: str) -> None:
        import json
        self._path = path
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except FileNotFoundError:
            data = {"players": []}
        self._raw = data

    def fetch_players(self) -> List[Player]:
        players: List[Player] = []
        for p in self._raw.get("players", []):
            players.append(Player(
                id=str(p.get("id", p.get("name"))),
                name=p.get("name", ""),
                position=p.get("position", ""),
                team=p.get("team"),
                bye_week=p.get("bye_week"),
                adp=p.get("adp"),
                projections=p.get("projections", {}),
            ))
        return players


def build_provider(spec: Dict) -> Provider:
    ptype = (spec or {}).get("type", "local_json")
    opts = (spec or {}).get("options", {})
    if ptype == "local_json":
        return LocalJsonProvider(path=opts.get("path", "data/projections.json"))
    if ptype == "sleeper":
        from .sleeper import SleeperProvider
        return SleeperProvider(opts)
    # Default back to local
    return LocalJsonProvider(path=opts.get("path", "data/projections.json"))

