from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence

from .fuzzy import best_match, normalize_player_name
from .models import Player


@dataclass(frozen=True)
class SyncedRosterPlayer:
    name: str
    position: str
    team: Optional[str] = None
    provider_id: Optional[str] = None


@dataclass(frozen=True)
class SyncedRosterTeam:
    name: str
    players: List[SyncedRosterPlayer]
    provider_id: Optional[str] = None


def synced_rosters_to_picks(
    synced_teams: Sequence[SyncedRosterTeam],
    players: Sequence[Player],
    league: dict,
) -> dict:
    """Convert provider rosters into the web UI's local pick objects.

    Provider roster order is rarely draft order, so team ownership is mapped by
    name against the saved league's draft-order teamNames when possible. The
    resulting picks are synthetic roster entries: enough for availability, my
    team, and free-agent scanning even when original draft order is unknown.
    """
    matcher = _PlayerMatcher(players)
    team_nums = _team_number_map(league, synced_teams)
    picks: List[dict] = []
    unmatched: List[dict] = []
    seen_player_ids = set()

    for fallback_idx, team in enumerate(synced_teams, 1):
        team_num = team_nums.get(_norm(team.name), fallback_idx)
        for roster_player in team.players:
            matched = matcher.match(roster_player)
            if not matched:
                unmatched.append({
                    "team": team.name,
                    "name": roster_player.name,
                    "pos": roster_player.position,
                    "nflTeam": roster_player.team,
                })
                continue
            player_id = matched.key()
            if player_id in seen_player_ids:
                continue
            seen_player_ids.add(player_id)
            picks.append({
                "pickNum": len(picks) + 1,
                "teamNum": team_num,
                "playerId": player_id,
                "synced": True,
                "sourceName": roster_player.name,
            })

    return {
        "picks": picks,
        "matched": len(picks),
        "unmatched": unmatched,
        "teams": [
            {"name": team.name, "players": len(team.players),
             "teamNum": team_nums.get(_norm(team.name), i + 1)}
            for i, team in enumerate(synced_teams)
        ],
    }


def _team_number_map(league: dict, synced_teams: Sequence[SyncedRosterTeam]) -> Dict[str, int]:
    saved = league.get("teamNames") or []
    out: Dict[str, int] = {}
    for idx, name in enumerate(saved, 1):
        if isinstance(name, str) and name.strip():
            out[_norm(name)] = idx
    for idx, team in enumerate(synced_teams, 1):
        out.setdefault(_norm(team.name), idx)
    return out


class _PlayerMatcher:
    def __init__(self, players: Sequence[Player]):
        self.players = list(players)
        self.by_provider: Dict[tuple, Player] = {}
        self.by_exact: Dict[tuple, Player] = {}
        self.names_by_pos: Dict[str, List[str]] = {}
        self.by_norm_name_pos: Dict[tuple, Player] = {}
        for player in self.players:
            norm = _norm(player.name)
            pos = _position(player.position)
            self.by_exact[(norm, pos)] = player
            self.by_norm_name_pos[(norm, pos)] = player
            self.names_by_pos.setdefault(pos, []).append(player.name)
            espn_id = (player.metadata or {}).get("espn_id")
            if espn_id is not None:
                self.by_provider[("espn", str(espn_id), pos)] = player

    def match(self, synced: SyncedRosterPlayer) -> Optional[Player]:
        pos = _position(synced.position)
        if not synced.name or not pos:
            return None

        provider = _provider_prefix(synced.provider_id)
        provider_value = _provider_value(synced.provider_id)
        if provider and provider_value:
            direct = self.by_provider.get((provider, provider_value, pos))
            if direct:
                return direct

        if pos == "DST":
            dst = self._match_dst(synced)
            if dst:
                return dst

        norm = _norm(synced.name)
        direct = self.by_exact.get((norm, pos))
        if direct:
            return direct

        names = self.names_by_pos.get(pos, [])
        for name in names:
            n = _norm(name)
            if norm and (norm in n or n in norm):
                return self.by_norm_name_pos.get((n, pos))

        max_distance = 2 if len(norm) <= 12 else 3
        fuzzy = best_match(synced.name, names, max_distance=max_distance)
        if fuzzy:
            return self.by_norm_name_pos.get((_norm(fuzzy), pos))
        return None

    def _match_dst(self, synced: SyncedRosterPlayer) -> Optional[Player]:
        team = (synced.team or "").upper()
        candidates = [p for p in self.players if _position(p.position) == "DST"]
        if team:
            for player in candidates:
                if (player.team or "").upper() == team:
                    return player
        norm = _norm(synced.name)
        for player in candidates:
            if norm and (norm in _norm(player.name) or _norm(player.name) in norm):
                return player
        return None


def _position(value: object) -> str:
    pos = str(value or "").upper().strip()
    if pos in {"DEF", "D/ST", "D"}:
        return "DST"
    return pos


def _provider_prefix(provider_id: Optional[str]) -> Optional[str]:
    if not provider_id or ":" not in provider_id:
        return None
    return provider_id.split(":", 1)[0]


def _provider_value(provider_id: Optional[str]) -> Optional[str]:
    if not provider_id or ":" not in provider_id:
        return None
    return provider_id.split(":", 1)[1]


def _norm(value: str) -> str:
    return normalize_player_name(value, compact=True)
