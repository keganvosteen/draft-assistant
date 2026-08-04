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


@dataclass(frozen=True)
class SyncedDraftPick:
    """One real pick from a provider's draft: its number, seat, and player."""
    pick_no: int
    team_num: int
    player: SyncedRosterPlayer


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
                    "id": roster_player.provider_id,
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
            {
                "name": team.name,
                "players": len(team.players),
                "teamNum": team_nums.get(_norm(team.name), i + 1),
            }
            for i, team in enumerate(synced_teams)
        ],
    }


def synced_draft_to_picks(
    draft_picks: Sequence[SyncedDraftPick],
    players: Sequence[Player],
    league: dict,
) -> dict:
    """Convert a provider's real draft picks into the web UI's pick objects.

    Unlike :func:`synced_rosters_to_picks`, the pick number and team seat are
    the provider's own, so the board reflects the actual draft rather than a
    reconstruction — which is what lets it be polled live.

    A pick whose player isn't on our board (a deep rookie, an IDP) is kept as a
    placeholder rather than dropped: the count of picks made is what tells the
    app whose turn it is, so silently skipping one would put the whole draft on
    the wrong clock.
    """
    matcher = _PlayerMatcher(players)
    num_teams = int(league.get("numTeams") or 0)
    picks: List[dict] = []
    unmatched: List[dict] = []
    seen_player_ids = set()

    for draft_pick in sorted(draft_picks, key=lambda p: p.pick_no):
        source = draft_pick.player
        matched = matcher.match(source)
        team_num = draft_pick.team_num
        if not team_num and num_teams:
            team_num = _snake_team(draft_pick.pick_no, num_teams)
        pick = {
            "pickNum": draft_pick.pick_no,
            "teamNum": team_num or 1,
            "synced": True,
            "sourceName": source.name,
        }
        player_id = matched.key() if matched else None
        if player_id is not None and player_id not in seen_player_ids:
            seen_player_ids.add(player_id)
            pick["playerId"] = player_id
        else:
            # Two cases land here: the player isn't on our board at all, or a
            # later pick resolved to a board player an earlier pick already
            # claimed (two provider players can fuzzy-match one of ours). Both
            # keep their slot as a placeholder rather than being dropped — the
            # number of picks made is what tells the app whose turn it is, so
            # skipping one puts the whole draft on the wrong clock from there on.
            pick["playerId"] = f"{source.name or source.provider_id or 'Unknown'}|{_position(source.position)}"
            pick["unmatched"] = True
            unmatched.append({
                "pickNum": draft_pick.pick_no,
                "name": source.name,
                "pos": source.position,
                "nflTeam": source.team,
                "id": source.provider_id,
            })
        picks.append(pick)

    return {
        "picks": picks,
        "matched": len(picks) - len(unmatched),
        "unmatched": unmatched,
        "totalPicks": len(picks),
        "nextPickNum": (picks[-1]["pickNum"] + 1) if picks else 1,
    }


def _snake_team(pick_no: int, num_teams: int) -> int:
    """Seat that owns ``pick_no`` in a snake draft (1-indexed)."""
    rnd, idx = divmod(pick_no - 1, num_teams)
    return (num_teams - idx) if rnd % 2 else (idx + 1)


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
        self.by_provider_id: Dict[tuple, Player] = {}
        self.by_exact: Dict[tuple, Player] = {}
        # Candidate names are stored already normalized: matching normalizes on
        # both sides, so re-deriving these per lookup was both wasted work and a
        # source of threshold/comparison mismatches.
        self.norm_names_by_pos: Dict[str, List[str]] = {}
        self.by_norm_name_pos: Dict[tuple, Player] = {}
        for player in self.players:
            norm = _norm(player.name)
            pos = _position(player.position)
            self.by_exact[(norm, pos)] = player
            self.by_norm_name_pos[(norm, pos)] = player
            self.norm_names_by_pos.setdefault(pos, []).append(norm)
            for provider, key in (("espn", "espn_id"), ("sleeper", "sleeper_id")):
                value = (player.metadata or {}).get(key)
                if value is not None:
                    self.by_provider[(provider, str(value), pos)] = player
                    self.by_provider_id.setdefault((provider, str(value)), player)

    def match(self, synced: SyncedRosterPlayer) -> Optional[Player]:
        pos = _position(synced.position)

        # Provider ids are exact, so they're tried first and are enough on
        # their own — a Sleeper roster carries ids and nothing else.
        provider = _provider_prefix(synced.provider_id)
        provider_value = _provider_value(synced.provider_id)
        if provider and provider_value:
            direct = (self.by_provider.get((provider, provider_value, pos))
                      or self.by_provider_id.get((provider, provider_value)))
            if direct:
                return direct

        if not synced.name or not pos:
            return None

        if pos == "DST":
            dst = self._match_dst(synced)
            if dst:
                return dst

        norm = _norm(synced.name)
        direct = self.by_exact.get((norm, pos))
        if direct:
            return direct

        names = self.norm_names_by_pos.get(pos, [])

        # Containment catches "Marvin Harrison" vs "Marvin Harrison Jr.". Take
        # the closest length rather than the first hit: returning whichever
        # candidate happened to come first made the result depend on the order
        # of the player file, so the same sync could bind differently after a
        # data pull reshuffled it.
        contained = [n for n in names if norm and (norm in n or n in norm)]
        if contained:
            best = min(contained, key=lambda n: (abs(len(n) - len(norm)), n))
            return self.by_norm_name_pos.get((best, pos))

        # Both sides are compact-normalized here, so the edit budget is measured
        # against the same string shape it is applied to.
        max_distance = 2 if len(norm) <= 12 else 3
        fuzzy = best_match(norm, names, max_distance=max_distance)
        if fuzzy:
            return self.by_norm_name_pos.get((fuzzy, pos))
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
