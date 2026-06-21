from __future__ import annotations
from typing import Dict, List, Optional, Set, Tuple

from .models import DraftState, LeagueConfig, Player
from .fuzzy import fuzzy_match


class DraftTracker:
    def __init__(self, config: LeagueConfig, state: DraftState, players: List[Player]):
        self.config = config
        self.state = state
        self.players = {p.key(): p for p in players}

    def available_players(self) -> List[Player]:
        picked = self.state.picked_set()
        return [p for k, p in self.players.items() if k not in picked]

    def record_pick(self, player_name: str, position: Optional[str] = None, my_pick: bool = False) -> Optional[Player]:
        avail = self.available_players()
        name_lower = player_name.strip().lower()

        # 1) Exact name match
        matches = []
        for p in avail:
            if p.name.lower() == name_lower:
                if position is None or p.position.upper() == position.upper():
                    matches.append(p)

        # 2) Substring match
        if not matches:
            for p in avail:
                if name_lower in p.name.lower():
                    if position is None or p.position.upper() == position.upper():
                        matches.append(p)

        # 3) Fuzzy match — allow fewer edits for short queries so e.g. "Hall"
        #    can't silently become "Hill".
        if not matches:
            query = player_name.strip()
            max_distance = 1 if len(query) <= 5 else 2 if len(query) <= 10 else 3
            candidate_names = [p.name for p in avail]
            fuzzy_results = fuzzy_match(query, candidate_names, max_distance=max_distance)
            seen_keys = set()
            for matched_name, _dist in fuzzy_results:
                for p in avail:
                    if p.name == matched_name and p.key() not in seen_keys:
                        if position is None or p.position.upper() == position.upper():
                            matches.append(p)
                            seen_keys.add(p.key())

        if len(matches) == 1:
            p = matches[0]
        elif len(matches) > 1:
            # Ambiguous: prefer the player most likely to actually be drafted
            # (lowest ADP), then skill positions, then name for determinism.
            skill = {"RB", "WR", "QB", "TE"}
            matches.sort(key=lambda m: (
                m.adp if m.adp is not None else float("inf"),
                0 if m.position in skill else 1,
                m.name,
            ))
            p = matches[0]
        else:
            return None

        key = p.key()
        self.state.picks.append(key)
        if my_pick:
            self.state.my_picks.append(key)
        return p

    def undo(self, steps: int = 1) -> List[str]:
        """Undo the last `steps` picks. Returns list of undone keys."""
        undone: List[str] = []
        for _ in range(steps):
            if not self.state.picks:
                break
            last = self.state.picks.pop()
            if self.state.my_picks and self.state.my_picks[-1] == last:
                self.state.my_picks.pop()
            undone.append(last)
        return undone

    def my_roster(self) -> Dict[str, List[Player]]:
        roster: Dict[str, List[Player]] = {}
        for key in self.state.my_picks:
            p = self.players.get(key)
            if not p:
                continue
            roster.setdefault(p.position, []).append(p)
        return roster

    def draft_log(self) -> List[Tuple[int, str, bool]]:
        """Return full draft log as list of (pick_number, player_key, is_mine)."""
        my_set = set(self.state.my_picks)
        log: List[Tuple[int, str, bool]] = []
        for i, key in enumerate(self.state.picks, 1):
            log.append((i, key, key in my_set))
        return log

