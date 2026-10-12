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
    provider_team_id: Optional[str] = None


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
    seen_sources = set()

    for fallback_idx, team in enumerate(synced_teams, 1):
        team_num = team_nums[fallback_idx - 1]
        for roster_player in team.players:
            source_id = roster_player.provider_id or (
                roster_player.name, _position(roster_player.position), roster_player.team)
            if source_id in seen_sources:
                continue
            seen_sources.add(source_id)
            matched = matcher.match(roster_player)
            player_id = matched.key() if matched else None
            pick = {
                "pickNum": len(picks) + 1,
                "teamNum": team_num,
                "synced": True,
                "sourceName": roster_player.name,
                "sourcePosition": roster_player.position,
                "sourceTeam": roster_player.team,
                "providerPlayerId": roster_player.provider_id,
                "providerTeamId": team.provider_id,
            }
            if player_id is None or player_id in seen_player_ids:
                # Ownership survives missing projections and ambiguous name
                # matches. Keep provider identity so a later data refresh can
                # resolve the player without treating them as a free agent.
                player_id = roster_player.provider_id or (
                    f"{roster_player.name or 'Unknown'}|{_position(roster_player.position)}")
                if player_id in seen_player_ids:
                    player_id = f"{player_id}|roster:{team_num}:{len(picks) + 1}"
                pick["unmatched"] = True
                unmatched.append({
                    "team": team.name,
                    "name": roster_player.name,
                    "pos": roster_player.position,
                    "nflTeam": roster_player.team,
                    "id": roster_player.provider_id,
                })
            seen_player_ids.add(player_id)
            pick["playerId"] = player_id
            picks.append(pick)

    return {
        "picks": picks,
        "matched": len(picks) - len(unmatched),
        "unmatched": unmatched,
        "teams": [
            {
                "name": team.name,
                "players": len(team.players),
                "teamNum": team_nums[i],
            }
            for i, team in enumerate(synced_teams)
        ],
    }


def roster_player_keys(entries: Sequence[dict], players: Sequence[Player]) -> List[str]:
    """Resolve saved ownership against the current projections, in row order.

    Provider/source fields survive a projection refresh, including players who
    had no projection when synced. Older snapshots can still use their saved
    canonical or display-derived player key.
    """
    matcher = _PlayerMatcher(players)
    keys = []
    for entry in entries:
        entry = entry if isinstance(entry, dict) else {"playerId": entry}
        saved_id = str(entry.get("playerId") or "")
        matched = matcher.match(SyncedRosterPlayer(
            name=str(entry.get("sourceName") or ""),
            position=str(entry.get("sourcePosition") or ""),
            team=entry.get("sourceTeam"),
            provider_id=entry.get("providerPlayerId") or saved_id,
        ))
        keys.append(matched.key() if matched else matcher.aliases.get(saved_id, saved_id))
    return keys


def resolve_roster_entries(entries: Sequence, players: Sequence[Player]) -> List[dict]:
    """Return snapshot copies whose player IDs resolve to today's player pool."""
    rows = [dict(entry) if isinstance(entry, dict) else {"playerId": entry}
            for entry in entries]
    keys = roster_player_keys(rows, players)
    known = {player.key() for player in players}
    for row, key in zip(rows, keys):
        row["playerId"] = key
        if key in known:
            row.pop("unmatched", None)
    return rows


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
    ordered = sorted(draft_picks, key=lambda p: p.pick_no)
    if [p.pick_no for p in ordered] != list(range(1, len(ordered) + 1)):
        raise ValueError("The provider returned an incomplete draft history. Retry before replacing recorded picks.")
    team_ids = {str(team_id): i for i, team_id in enumerate(league.get("teamIds") or [], 1) if team_id is not None}

    for draft_pick in ordered:
        source = draft_pick.player
        matched = matcher.match(source)
        team_num = team_ids.get(str(draft_pick.provider_team_id), draft_pick.team_num)
        if draft_pick.provider_team_id is not None and not team_num:
            raise ValueError("A drafted team is missing from the published order. Refresh league settings and retry.")
        if not team_num and num_teams:
            team_num = _snake_team(draft_pick.pick_no, num_teams)
        pick = {
            "pickNum": draft_pick.pick_no,
            "teamNum": team_num or 1,
            "synced": True,
            "sourceName": source.name,
            "sourcePosition": source.position,
            "sourceTeam": source.team,
            "providerPlayerId": source.provider_id,
            "providerTeamId": draft_pick.provider_team_id,
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
            pick["playerId"] = source.provider_id or f"{source.name or 'Unknown'}|{_position(source.position)}"
            if pick["playerId"] in seen_player_ids:
                pick["playerId"] = f"{source.name or 'Unknown'} (pick {draft_pick.pick_no})|{_position(source.position)}"
            pick["unmatched"] = True
            unmatched.append({
                "pickNum": draft_pick.pick_no,
                "name": source.name,
                "pos": source.position,
                "nflTeam": source.team,
                "id": source.provider_id,
            })
        picks.append(pick)
        seen_player_ids.add(pick["playerId"])

    return {
        "picks": picks,
        "matched": len(picks) - len(unmatched),
        "unmatched": unmatched,
        "totalPicks": len(picks),
        "nextPickNum": (picks[-1]["pickNum"] + 1) if picks else 1,
        "hasTradedPicks": bool(num_teams and league.get("draftType") == "snake" and any(
            pick["teamNum"] != _snake_team(pick["pickNum"], num_teams) for pick in picks)),
    }


def _snake_team(pick_no: int, num_teams: int) -> int:
    """Seat that owns ``pick_no`` in a snake draft (1-indexed)."""
    rnd, idx = divmod(pick_no - 1, num_teams)
    return (num_teams - idx) if rnd % 2 else (idx + 1)


def _team_number_map(league: dict, synced_teams: Sequence[SyncedRosterTeam]) -> List[int]:
    saved = [_norm(name) for name in league.get("teamNames") or []]
    ids = {str(value): i for i, value in enumerate(league.get("teamIds") or [], 1) if value is not None}
    result = []
    for fallback, team in enumerate(synced_teams, 1):
        if str(team.provider_id) in ids:
            result.append(ids[str(team.provider_id)])
        elif saved.count(_norm(team.name)) == 1:
            result.append(saved.index(_norm(team.name)) + 1)
        elif not saved and not ids:
            result.append(fallback)
        else:
            raise ValueError("Could not identify a roster's team. Refresh league settings and select your team before syncing.")
    if len(set(result)) != len(result):
        raise ValueError("Roster team names are ambiguous. Refresh league settings to load provider team IDs.")
    return result


class _PlayerMatcher:
    def __init__(self, players: Sequence[Player]):
        self.players = list(players)
        from .identity import player_aliases, player_indexes
        self.canonical, self.aliases = player_indexes(self.players)
        self.ambiguous_aliases = {
            alias for player in self.players for alias in player_aliases(player)
            if alias not in self.canonical and alias not in self.aliases
        }
        self.by_exact: Dict[tuple, Optional[Player]] = {}
        # Candidate names are stored already normalized: matching normalizes on
        # both sides, so re-deriving these per lookup was both wasted work and a
        # source of threshold/comparison mismatches.
        self.norm_names_by_pos: Dict[str, List[str]] = {}
        for player in self.players:
            norm = _norm(player.name)
            pos = _position(player.position)
            key = (norm, pos)
            if key not in self.by_exact:
                self.by_exact[key] = player
                self.norm_names_by_pos.setdefault(pos, []).append(norm)
            elif self.by_exact[key] is not None and self.by_exact[key].key() != player.key():
                self.by_exact[key] = None

    def match(self, synced: SyncedRosterPlayer) -> Optional[Player]:
        pos = _position(synced.position)

        saved_id = str(synced.provider_id or "")
        canonical_id = self.aliases.get(saved_id, saved_id)
        direct = self.canonical.get(canonical_id)
        if direct is not None:
            return direct
        if saved_id in self.ambiguous_aliases:
            # Do not undo the shared identity index's ambiguity check through
            # a provider- or name-based fallback that chooses an arbitrary row.
            return None

        if not synced.name or not pos:
            return None

        if pos == "DST":
            dst = self._match_dst(synced)
            if dst:
                return dst

        norm = _norm(synced.name)
        if (norm, pos) in self.by_exact:
            return self.by_exact[(norm, pos)]

        names = self.norm_names_by_pos.get(pos, [])

        # Containment catches "Marvin Harrison" vs "Marvin Harrison Jr.". Take
        # the closest length rather than the first hit: returning whichever
        # candidate happened to come first made the result depend on the order
        # of the player file, so the same sync could bind differently after a
        # data pull reshuffled it.
        contained = [n for n in names if norm and (norm in n or n in norm)]
        if contained:
            best = min(contained, key=lambda n: (abs(len(n) - len(norm)), n))
            return self.by_exact.get((best, pos))

        # Both sides are compact-normalized here, so the edit budget is measured
        # against the same string shape it is applied to.
        max_distance = 2 if len(norm) <= 12 else 3
        fuzzy = best_match(norm, names, max_distance=max_distance)
        if fuzzy:
            return self.by_exact.get((fuzzy, pos))
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


def _norm(value: str) -> str:
    return normalize_player_name(value, compact=True)
