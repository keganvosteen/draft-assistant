from __future__ import annotations
from typing import Dict, List
import json

from ..models import Player
from .base import Provider


SLEEPER_PLAYERS_URL = "https://api.sleeper.app/v1/players/nfl"
SLEEPER_ADP_URL = "https://api.sleeper.app/v1/players/nfl/adp"


class SleeperProvider(Provider):
    def __init__(self, options: Dict) -> None:
        self.options = options or {}

    def fetch_players(self) -> List[Player]:
        # Network access may be restricted; try/catch and fall back to empty.
        try:
            import urllib.request
            with urllib.request.urlopen(SLEEPER_PLAYERS_URL, timeout=10) as resp:
                players_raw = json.loads(resp.read().decode("utf-8"))
        except Exception:
            players_raw = {}

        try:
            import urllib.request
            with urllib.request.urlopen(SLEEPER_ADP_URL, timeout=10) as resp:
                adp_raw = json.loads(resp.read().decode("utf-8"))
        except Exception:
            adp_raw = {}

        adp_map: Dict[str, float] = {}
        if isinstance(adp_raw, list):
            for row in adp_raw:
                pid = str(row.get("player_id", ""))
                val = row.get("adp")
                if pid and isinstance(val, (int, float)):
                    adp_map[pid] = float(val)

        players: List[Player] = []
        if isinstance(players_raw, dict):
            for pid, p in players_raw.items():
                pos = (p or {}).get("position") or ""
                if pos in {"QB", "RB", "WR", "TE", "K", "DEF", "DST"}:
                    players.append(Player(
                        id=str(pid),
                        name=(p or {}).get("full_name") or (p or {}).get("last_name") or str(pid),
                        position=pos if pos != "DEF" else "DST",
                        team=(p or {}).get("team"),
                        bye_week=(p or {}).get("bye_week"),
                        adp=adp_map.get(str(pid)),
                        projections={},  # Sleeper doesn't provide projections here
                    ))
        return players

