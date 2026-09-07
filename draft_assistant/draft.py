from __future__ import annotations
from typing import Dict, List, Optional, Set, Tuple

from .models import DraftState, LeagueConfig, Player
from .fuzzy import fuzzy_match


class DraftTracker:
    def __init__(self, config: LeagueConfig, state: DraftState, players: List[Player]):
        self.config = config
        self.state = state
        self.players = {p.key(): p for p in players}
        self.aliases = {p.legacy_key(): p.key() for p in players}

    def _canonical_key(self, key: str) -> str:
        return self.aliases.get(key, key)

    def available_players(self) -> List[Player]:
        picked = {self._canonical_key(key) for key in self.state.picked_set()}
        return [p for k, p in self.players.items() if k not in picked]

    def drafted_players(self) -> List[Player]:
        """Return resolvable drafted players once each, in pick order."""
        drafted: List[Player] = []
        seen: Set[str] = set()
        for key in self.state.picks:
            canonical = self._canonical_key(key)
            player = self.players.get(canonical)
            if player is not None and canonical not in seen:
                drafted.append(player)
                seen.add(canonical)
        return drafted

    def record_pick(self, player_name: str, position: Optional[str] = None, my_pick: bool = False) -> Optional[Player]:
        query = player_name.strip()
        if not query:
            return None
        name_lower = query.lower()
        position = position.strip().upper() if position else None
        candidates = [p for p in self.players.values() if position is None or p.position.upper() == position]
        picked = {self._canonical_key(key) for key in self.state.picks}

        # An exact name remains authoritative even after it has been drafted:
        # retrying a pick must not silently fuzzy-match somebody else.
        exact = [p for p in candidates if p.name.lower() == name_lower]
        matches = [p for p in exact if p.key() not in picked]
        if exact and not matches:
            return None
        avail = [p for p in candidates if p.key() not in picked]

        # 2) Substring match
        if not matches:
            matches = [p for p in avail if name_lower in p.name.lower()]

        # 3) Fuzzy match — allow fewer edits for short queries so e.g. "Hall"
        #    can't silently become "Hill".
        if not matches:
            max_distance = 1 if len(query) <= 5 else 2 if len(query) <= 10 else 3
            fuzzy_results = fuzzy_match(query, [p.name for p in avail], max_distance=max_distance)
            if fuzzy_results:
                # ADP only breaks ties between equally close names; it must
                # never override a better spelling match.
                closest = fuzzy_results[0][1]
                names = {name for name, distance in fuzzy_results if distance == closest}
                matches = [p for p in avail if p.name in names]

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
            if self.state.my_picks and self._canonical_key(self.state.my_picks[-1]) == self._canonical_key(last):
                self.state.my_picks.pop()
            undone.append(last)
        return undone

    def my_roster(self) -> Dict[str, List[Player]]:
        roster: Dict[str, List[Player]] = {}
        for key in self.state.my_picks:
            p = self.players.get(self._canonical_key(key))
            if not p:
                continue
            roster.setdefault(p.position, []).append(p)
        return roster

    def draft_log(self) -> List[Tuple[int, str, bool]]:
        """Return full draft log as list of (pick_number, player_key, is_mine)."""
        my_set = {self._canonical_key(key) for key in self.state.my_picks}
        log: List[Tuple[int, str, bool]] = []
        for i, key in enumerate(self.state.picks, 1):
            log.append((i, key, self._canonical_key(key) in my_set))
        return log

