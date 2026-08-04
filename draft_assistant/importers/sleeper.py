"""Sleeper league import, roster sync, and live draft-pick sync.

Sleeper's league API is public and read-only — no OAuth (Yahoo) and no session
cookies (ESPN) — so a league id, or just a username, is enough.

Unlike the ESPN/Yahoo roster sync (which reconstructs a plausible draft from
current rosters), Sleeper exposes the draft itself: every pick with its real
pick number and seat. That means picks land in true draft order and the board
knows who is actually on the clock, so this can be polled live mid-draft.
"""
from __future__ import annotations

import json
from typing import Dict, List, Optional
from urllib.parse import quote
from urllib.request import Request, urlopen

from ..platform_sync import SyncedDraftPick, SyncedRosterPlayer, SyncedRosterTeam

SLEEPER_BASE = "https://api.sleeper.app/v1"

# Sleeper roster_positions entries -> our roster keys. Flex variants map to the
# TYPED flex keys (models.FLEX_TYPES) so eligibility survives the import: a
# REC_FLEX must not be fillable by an RB, a SUPER_FLEX can take a QB.
SLEEPER_SLOTS = {
    "QB": "QB", "RB": "RB", "WR": "WR", "TE": "TE", "K": "K", "DEF": "DST",
    "FLEX": "FLEX", "REC_FLEX": "WRTE", "WRRB_FLEX": "RBWR",
    "SUPER_FLEX": "SUPERFLEX", "BN": "BN",
}
# IDP / reserve slots we deliberately ignore — the engine has no IDP model, and
# IR/taxi spots are not draftable roster capacity.
SLEEPER_IGNORED_SLOTS = {"IDP_FLEX", "DL", "LB", "DB", "IR", "TAXI"}

# Sleeper scoring_settings keys -> app stat keys. Sleeper's naming is already
# very close to ours (the projection importer copies most keys straight
# through); this covers the renames and the defense/kicker differences.
SLEEPER_SCORING = {
    "pass_yd": "pass_yd", "pass_td": "pass_td", "pass_int": "pass_int", "pass_2pt": "pass_2pt",
    "rush_yd": "rush_yd", "rush_td": "rush_td", "rush_2pt": "rush_2pt",
    "rec": "rec", "rec_yd": "rec_yd", "rec_td": "rec_td", "rec_2pt": "rec_2pt",
    "fum_lost": "fumbles", "fum": "fumbles_total",
    # "sack" in scoring_settings is a defense recording one (a positive); the
    # QB-sacked penalty is a separate key in our scoring config.
    "sack": "sack", "int": "def_int", "fum_rec": "fumble_recovery", "safe": "safety",
    "blk_kick": "blk_kick", "def_td": "int_ret_td", "fum_rec_td": "fum_ret_td",
    "def_st_td": "int_ret_td", "blk_kick_ret_td": "blk_kick_ret_td",
    "pr_td": "prt_td", "kr_td": "krt_td",
    "xpm": "pat_made", "fgmiss": "fg_miss",
    "fgm_40_49": "fg_40_49", "fgm_50_59": "fg_50_59", "fgm_60p": "fg_60_plus",
}
# Sleeper splits short field goals into three buckets; we carry one. Leagues
# almost always weight the three identically, so their mean is exact in
# practice and a fair approximation when it isn't.
_FG_SHORT_KEYS = ("fgm_0_19", "fgm_20_29", "fgm_30_39")


# ── HTTP ─────────────────────────────────────────────────────────────────────

def _seg(value: object) -> str:
    """Escape a value being interpolated into a request path.

    League ids, draft ids and usernames arrive from the browser. Unescaped, a
    ``?``, ``#`` or ``../`` in one of them reshapes the request the app makes.
    """
    return quote(str(value or ""), safe="")


def _get(path: str, timeout: int = 20) -> object:
    req = Request(f"{SLEEPER_BASE}/{path.lstrip('/')}", headers={
        "User-Agent": "draft-assistant/1.0 (+https://github.com/)",
        "Accept": "application/json",
    })
    with urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode("utf-8")
    return json.loads(body) if body.strip() else None


# ── Public API ───────────────────────────────────────────────────────────────

def fetch_user(username: str) -> Dict[str, object]:
    """Resolve a Sleeper username (or user id) to its user record."""
    user = _get(f"user/{_seg(username)}")
    if not isinstance(user, dict) or not user.get("user_id"):
        raise RuntimeError(f"No Sleeper user named {username!r}")
    return user


def fetch_user_leagues(username: str, season: int) -> List[Dict[str, object]]:
    """List a user's NFL leagues for ``season`` (for the league picker)."""
    user = fetch_user(username)
    raw = _get(f"user/{_seg(user['user_id'])}/leagues/nfl/{_seg(season)}")
    leagues = raw if isinstance(raw, list) else []
    return [{
        "leagueId": str(lg.get("league_id")),
        "name": lg.get("name") or str(lg.get("league_id")),
        "season": str(lg.get("season") or season),
        "totalRosters": _to_int(lg.get("total_rosters")) or 0,
        "status": lg.get("status") or "",
        "draftId": str(lg.get("draft_id")) if lg.get("draft_id") else None,
    } for lg in leagues if isinstance(lg, dict)]


def fetch_league(league_id: str, username: Optional[str] = None) -> Dict[str, object]:
    """Read a Sleeper league's settings in the same shape as the ESPN importer.

    When ``username`` is given and that user is in the draft, the returned
    payload also carries their draft slot as ``draftPosition``.
    """
    league = _get(f"league/{_seg(league_id)}")
    if not isinstance(league, dict) or not league.get("league_id"):
        raise RuntimeError(f"No Sleeper league with id {league_id!r}")
    users = _get(f"league/{_seg(league_id)}/users")
    rosters = _get(f"league/{_seg(league_id)}/rosters")

    draft = None
    draft_id = league.get("draft_id")
    if draft_id:
        try:
            draft = _get(f"draft/{_seg(draft_id)}")
        except Exception:
            draft = None

    user_id = None
    if username:
        try:
            user_id = str(fetch_user(username).get("user_id"))
        except Exception:
            user_id = None

    return _parse_league(league, users, rosters, draft, user_id)


def fetch_league_rosters(league_id: str) -> List[SyncedRosterTeam]:
    """Current rosters as provider-neutral rows for the local matcher.

    Sleeper rosters carry only player ids. That's enough on its own when the
    board was built from Sleeper (players keep a ``sleeper_id``), but boards
    pulled by ``collect-all`` have no such id — so ids are also resolved to
    names here, which lets the usual name+position matching finish the job.
    """
    league = _get(f"league/{_seg(league_id)}")
    league = league if isinstance(league, dict) else {}
    users = _get(f"league/{_seg(league_id)}/users")
    rosters = _get(f"league/{_seg(league_id)}/rosters")
    draft = None
    if league.get("draft_id"):
        try:
            draft = _get(f"draft/{_seg(league['draft_id'])}")
        except Exception:
            draft = None
    return _parse_rosters(users, rosters, draft, _player_index())


# Sleeper's player dictionary is ~5MB, so it's fetched at most once per run and
# only for roster sync — the live draft feed carries names on the picks.
_PLAYER_INDEX: Dict[str, dict] = {}


def _player_index() -> Dict[str, dict]:
    global _PLAYER_INDEX
    if not _PLAYER_INDEX:
        try:
            data = _get("players/nfl", timeout=60)
        except Exception:
            return {}
        if isinstance(data, dict):
            _PLAYER_INDEX = {str(k): v for k, v in data.items() if isinstance(v, dict)}
    return _PLAYER_INDEX


def fetch_draft(draft_id: str) -> Dict[str, object]:
    """Draft metadata: status, type, seat mapping."""
    draft = _get(f"draft/{_seg(draft_id)}")
    if not isinstance(draft, dict) or not draft.get("draft_id"):
        raise RuntimeError(f"No Sleeper draft with id {draft_id!r}")
    return draft


def fetch_draft_picks(draft_id: str, draft: Optional[dict] = None) -> List[SyncedDraftPick]:
    """Every pick made so far, in pick order, with its real seat number.

    Pass an already-fetched ``draft`` to save a request when polling.
    """
    draft = draft if draft is not None else fetch_draft(draft_id)
    return _parse_draft_picks(_get(f"draft/{_seg(draft_id)}/picks"), draft)


def league_draft_id(league_id: str) -> Optional[str]:
    """The league's current draft id (leagues can have several over time)."""
    try:
        league = _get(f"league/{_seg(league_id)}")
    except Exception as exc:
        raise RuntimeError(f"No Sleeper league with id {league_id!r} ({exc})") from exc
    if isinstance(league, dict) and league.get("draft_id"):
        return str(league["draft_id"])
    drafts = _get(f"league/{_seg(league_id)}/drafts")
    if isinstance(drafts, list) and drafts:
        newest = max(drafts, key=lambda d: _to_int((d or {}).get("start_time")) or 0)
        if isinstance(newest, dict) and newest.get("draft_id"):
            return str(newest["draft_id"])
    return None


# ── Pure parsers (network-free, unit tested) ─────────────────────────────────

def _parse_league(
    league: dict,
    users: object,
    rosters: object,
    draft: Optional[dict],
    user_id: Optional[str] = None,
) -> Dict[str, object]:
    league_id = str(league.get("league_id") or "")
    settings = league.get("settings") or {}

    roster: Dict[str, int] = {}
    for slot in league.get("roster_positions") or []:
        key = SLEEPER_SLOTS.get(str(slot).upper())
        if key:
            roster[key] = roster.get(key, 0) + 1
    # Make the standard editor slots explicit (0 when absent) so an imported
    # roster overrides the form defaults instead of inheriting them.
    for key in ("QB", "RB", "WR", "TE", "FLEX", "K", "DST", "BN"):
        roster.setdefault(key, 0)

    scoring = _parse_scoring(league.get("scoring_settings") or {})

    names = _team_names_by_slot(users, rosters, draft,
                                _to_int(settings.get("num_teams")) or _to_int(league.get("total_rosters")))

    num_teams = (
        _to_int(league.get("total_rosters"))
        or _to_int(settings.get("num_teams"))
        or len([n for n in names if n])
        or 10
    )

    out: Dict[str, object] = {
        "name": league.get("name") or f"Sleeper {league_id}",
        "numTeams": num_teams,
        "rosterSlots": roster,
        "scoring": scoring,
        "teamNames": names[:num_teams],
        "sleeperLeagueId": league_id,
        "season": str(league.get("season") or ""),
        "status": league.get("status") or "",
    }
    if draft:
        out["sleeperDraftId"] = str(draft.get("draft_id") or "")
        out["draftType"] = "auction" if draft.get("type") == "auction" else "snake"
        out["draftStatus"] = draft.get("status") or ""
        slot = _slot_for_user(draft, user_id)
        if slot:
            out["draftPosition"] = slot
    elif league.get("draft_id"):
        out["sleeperDraftId"] = str(league["draft_id"])
    return out


def _parse_scoring(raw: dict) -> Dict[str, float]:
    scoring: Dict[str, float] = {}
    for sleeper_key, app_key in SLEEPER_SCORING.items():
        value = raw.get(sleeper_key)
        if value is None:
            continue
        try:
            scoring[app_key] = float(value)
        except (TypeError, ValueError):
            continue
    short_fgs = [float(raw[k]) for k in _FG_SHORT_KEYS
                 if isinstance(raw.get(k), (int, float))]
    if short_fgs:
        scoring["fg_0_39"] = round(sum(short_fgs) / len(short_fgs), 3)
    # Many leagues bucket every 50+ kick together; spread it across both of our
    # long buckets so a 55 and a 61 yarder are both scored.
    if isinstance(raw.get("fgm_50p"), (int, float)):
        scoring.setdefault("fg_50_59", float(raw["fgm_50p"]))
        scoring.setdefault("fg_60_plus", float(raw["fgm_50p"]))
    return scoring


def _parse_rosters(
    users: object,
    rosters: object,
    draft: Optional[dict],
    player_index: Optional[Dict[str, dict]] = None,
) -> List[SyncedRosterTeam]:
    owner_names = _owner_names(users)
    slot_by_roster = _slot_by_roster_id(draft)
    teams: List[SyncedRosterTeam] = []
    for roster in rosters if isinstance(rosters, list) else []:
        if not isinstance(roster, dict):
            continue
        roster_id = _to_int(roster.get("roster_id"))
        owner_id = str(roster.get("owner_id") or "")
        players = [
            _roster_player(str(pid), (player_index or {}).get(str(pid)))
            for pid in roster.get("players") or [] if pid
        ]
        teams.append(SyncedRosterTeam(
            name=owner_names.get(owner_id) or f"Team {roster_id or len(teams) + 1}",
            provider_id=str(roster_id) if roster_id else None,
            players=players,
        ))
    # Order teams by draft seat when the draft tells us the seating, so team N
    # in the app is the team that actually picks from slot N.
    if slot_by_roster:
        teams.sort(key=lambda t: slot_by_roster.get(_to_int(t.provider_id) or -1, 99))
    return teams


def _roster_player(player_id: str, meta: Optional[dict]) -> SyncedRosterPlayer:
    """A rostered player id, with name/position filled in when we know them."""
    meta = meta or {}
    name = str(meta.get("full_name") or "").strip()
    if not name:
        name = " ".join(part for part in [meta.get("first_name"), meta.get("last_name")]
                        if part).strip()
    positions = meta.get("fantasy_positions") or []
    position = str(meta.get("position") or (positions[0] if positions else "") or "")
    return SyncedRosterPlayer(
        name=name,
        position=position,
        team=str(meta.get("team") or "") or None,
        provider_id=f"sleeper:{player_id}",
    )


def _parse_draft_picks(raw: object, draft: Optional[dict]) -> List[SyncedDraftPick]:
    slot_by_roster = _slot_by_roster_id(draft)
    picks: List[SyncedDraftPick] = []
    for row in raw if isinstance(raw, list) else []:
        if not isinstance(row, dict):
            continue
        pick_no = _to_int(row.get("pick_no"))
        if not pick_no:
            continue
        # Auction drafts have no seat on the pick, so fall back to the roster
        # that won the player.
        seat = _to_int(row.get("draft_slot")) or slot_by_roster.get(_to_int(row.get("roster_id")) or -1)
        meta = row.get("metadata") or {}
        name = " ".join(part for part in [meta.get("first_name"), meta.get("last_name")] if part).strip()
        picks.append(SyncedDraftPick(
            pick_no=pick_no,
            team_num=seat or 0,
            player=SyncedRosterPlayer(
                name=name,
                position=str(meta.get("position") or ""),
                team=str(meta.get("team") or "") or None,
                provider_id=f"sleeper:{row['player_id']}" if row.get("player_id") else None,
            ),
        ))
    picks.sort(key=lambda p: p.pick_no)
    return picks


def _owner_names(users: object) -> Dict[str, str]:
    """user_id -> the team name they'd recognize (team name, else username)."""
    out: Dict[str, str] = {}
    for user in users if isinstance(users, list) else []:
        if not isinstance(user, dict):
            continue
        uid = str(user.get("user_id") or "")
        if not uid:
            continue
        team_name = ((user.get("metadata") or {}).get("team_name") or "").strip()
        out[uid] = team_name or str(user.get("display_name") or f"Team {uid}")
    return out


def _team_names_by_slot(
    users: object,
    rosters: object,
    draft: Optional[dict],
    num_teams: Optional[int],
) -> List[str]:
    """Team names indexed by draft slot (slot 1 first).

    Sleeper knows the real seating, so unlike the ESPN/Yahoo imports the names
    come out already in draft order and don't need dragging into place.
    """
    owner_names = _owner_names(users)
    owner_by_roster: Dict[int, str] = {}
    for roster in rosters if isinstance(rosters, list) else []:
        if isinstance(roster, dict):
            rid = _to_int(roster.get("roster_id"))
            if rid:
                owner_by_roster[rid] = str(roster.get("owner_id") or "")

    slot_by_roster = _slot_by_roster_id(draft)
    total = num_teams or len(owner_by_roster) or len(owner_names)
    if slot_by_roster:
        total = max(total, max(slot_by_roster.values(), default=0))
        by_slot: Dict[int, str] = {}
        for roster_id, slot in slot_by_roster.items():
            by_slot[slot] = owner_names.get(owner_by_roster.get(roster_id, ""), "") or f"Team {slot}"
        return [by_slot.get(slot, f"Team {slot}") for slot in range(1, total + 1)]

    draft_order = (draft or {}).get("draft_order") or {}
    if isinstance(draft_order, dict) and draft_order:
        total = max(total, max((_to_int(v) or 0) for v in draft_order.values()))
        by_slot = {}
        for uid, slot in draft_order.items():
            slot_num = _to_int(slot)
            if slot_num:
                by_slot[slot_num] = owner_names.get(str(uid), f"Team {slot_num}")
        return [by_slot.get(slot, f"Team {slot}") for slot in range(1, total + 1)]

    # No draft yet — fall back to roster order (the user reorders in the editor).
    return [owner_names.get(owner_by_roster.get(rid, ""), f"Team {rid}")
            for rid in sorted(owner_by_roster)]


def _slot_by_roster_id(draft: Optional[dict]) -> Dict[int, int]:
    """roster_id -> draft slot, from the draft's slot_to_roster_id map."""
    out: Dict[int, int] = {}
    for slot, roster_id in ((draft or {}).get("slot_to_roster_id") or {}).items():
        slot_num, rid = _to_int(slot), _to_int(roster_id)
        if slot_num and rid:
            out[rid] = slot_num
    return out


def _slot_for_user(draft: Optional[dict], user_id: Optional[str]) -> Optional[int]:
    if not user_id:
        return None
    order = (draft or {}).get("draft_order") or {}
    if isinstance(order, dict):
        return _to_int(order.get(str(user_id)))
    return None


def _to_int(value: object) -> Optional[int]:
    try:
        if value in (None, ""):
            return None
        return int(float(str(value)))
    except (TypeError, ValueError):
        return None
