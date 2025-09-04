from __future__ import annotations
from typing import Dict, List, Optional, Set, Tuple

from .models import DraftState, LeagueConfig, Player


class DraftTracker:
    def __init__(self, config: LeagueConfig, state: DraftState, players: List[Player]):
        self.config = config
        self.state = state
        self.players = {p.key(): p for p in players}

    def available_players(self) -> List[Player]:
        picked = self.state.picked_set()
        return [p for k, p in self.players.items() if k not in picked]

    def record_pick(self, player_name: str, position: Optional[str] = None, my_pick: bool = False) -> Optional[Player]:
        # Resolve by exact name+position match first, then name-only if unique.
        matches = []
        name_lower = player_name.strip().lower()
        for p in self.available_players():
            if p.name.lower() == name_lower:
                if position is None or p.position.upper() == position.upper():
                    matches.append(p)
        if not matches:
            # try substring contains
            for p in self.available_players():
                if name_lower in p.name.lower():
                    if position is None or p.position.upper() == position.upper():
                        matches.append(p)

        if len(matches) == 1:
            p = matches[0]
        elif len(matches) > 1:
            # Prefer skill positions
            pref = [m for m in matches if m.position in {"RB", "WR", "QB", "TE"}]
            p = pref[0] if pref else matches[0]
        else:
            return None

        key = p.key()
        self.state.picks.append(key)
        if my_pick:
            self.state.my_picks.append(key)
        return p

    def undo(self) -> Optional[str]:
        if not self.state.picks:
            return None
        last = self.state.picks.pop()
        if self.state.my_picks and self.state.my_picks[-1] == last:
            self.state.my_picks.pop()
        return last

    def my_roster(self) -> Dict[str, List[Player]]:
        roster: Dict[str, List[Player]] = {}
        for key in self.state.my_picks:
            p = self.players.get(key)
            if not p:
                continue
            roster.setdefault(p.position, []).append(p)
        return roster

