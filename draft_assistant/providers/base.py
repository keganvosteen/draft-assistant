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
        self._path = path

    def fetch_players(self) -> List[Player]:
        from ..storage import load_players
        return load_players(self._path)


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

