"""Yahoo Fantasy league import via OAuth2.

Yahoo has no public-league shortcut like ESPN — it requires OAuth2. The user
registers a Yahoo app (client id + secret), authorizes once, and we exchange the
returned code for tokens (persisted locally, never leaving the machine). Yahoo's
API gives league SETTINGS (scoring, roster, teams + manager names) and ADP, but
NOT preseason projections — those keep coming from the Sleeper/FFToday/ESPN
consensus, scored with the imported Yahoo rules.

This module is pure logic (build URLs, exchange tokens, fetch + parse). The
caller (web/server.py) persists the credentials/token dicts.
"""
from __future__ import annotations

import base64
import json
import time
from typing import Dict, List, Optional
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from ..platform_sync import SyncedRosterPlayer, SyncedRosterTeam

AUTH_URL = "https://api.login.yahoo.com/oauth2/request_auth"
TOKEN_URL = "https://api.login.yahoo.com/oauth2/get_token"
API_BASE = "https://fantasysports.yahooapis.com/fantasy/v2"
DEFAULT_REDIRECT = "oob"  # also works with a registered https://localhost/ URI

# Yahoo NFL stat_id -> app scoring key. The high-confidence offensive set; the
# stat_modifiers values become the per-unit weights. (K/DST stat ids vary and
# are left to the consensus' own K/DST handling.)
YAHOO_STAT_IDS = {
    4: "pass_yd", 5: "pass_td", 6: "pass_int",
    9: "rush_yd", 10: "rush_td",
    11: "rec", 12: "rec_yd", 13: "rec_td",
}

# Yahoo roster-position label -> our roster key (typed flex preserved).
YAHOO_POS = {
    "QB": "QB", "RB": "RB", "WR": "WR", "TE": "TE", "K": "K", "DEF": "DST",
    "W/R/T": "FLEX", "W/R": "RBWR", "W/T": "WRTE", "Q/W/R/T": "SUPERFLEX",
    "BN": "BN", "IR": "IR",
}


# ── OAuth ─────────────────────────────────────────────────────────────────────

def auth_url(client_id: str, redirect_uri: str = DEFAULT_REDIRECT) -> str:
    """Authorization URL the user opens to grant access.

    No `scope` param: Yahoo OAuth2 rejects fantasy scope values (`invalid_scope`)
    — Fantasy access is governed by the app's API Permissions in the developer
    console (the app must have "Fantasy Sports → Read"), not a request scope.
    """
    return AUTH_URL + "?" + urlencode({
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "language": "en-us",
    })


def _token_request(client_id: str, client_secret: str, data: Dict[str, str]) -> Dict:
    body = urlencode(data).encode()
    basic = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    req = Request(TOKEN_URL, data=body, headers={
        "Authorization": f"Basic {basic}",
        "Content-Type": "application/x-www-form-urlencoded",
    })
    try:
        with urlopen(req, timeout=30) as resp:
            tok = json.loads(resp.read())
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:300]
        raise RuntimeError(f"Yahoo token request failed ({exc.code}): {detail}")
    tok["obtained_at"] = int(time.time())
    return tok


def exchange_code(client_id: str, client_secret: str, code: str,
                  redirect_uri: str = DEFAULT_REDIRECT) -> Dict:
    """Exchange the authorization code for access + refresh tokens."""
    return _token_request(client_id, client_secret, {
        "grant_type": "authorization_code",
        "redirect_uri": redirect_uri,
        "code": code.strip(),
    })


def refresh_access_token(client_id: str, client_secret: str, refresh_token: str,
                         redirect_uri: str = DEFAULT_REDIRECT) -> Dict:
    return _token_request(client_id, client_secret, {
        "grant_type": "refresh_token",
        "redirect_uri": redirect_uri,
        "refresh_token": refresh_token,
    })


def token_is_expired(token: Dict) -> bool:
    obtained = int(token.get("obtained_at", 0))
    expires_in = int(token.get("expires_in", 3600))
    return time.time() >= obtained + expires_in - 120  # 2-min safety margin


# ── API ───────────────────────────────────────────────────────────────────────

def _api_get(access_token: str, path: str) -> Dict:
    sep = "&" if "?" in path else "?"
    url = f"{API_BASE}/{path}{sep}format=json"
    req = Request(url, headers={
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
    })
    try:
        with urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:300]
        raise RuntimeError(f"Yahoo API {path} failed ({exc.code}): {detail}")


def _find_all(obj, key: str) -> List:
    """Collect every value stored under `key` anywhere in Yahoo's nested JSON."""
    out: List = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == key:
                out.append(v)
            out.extend(_find_all(v, key))
    elif isinstance(obj, list):
        for item in obj:
            out.extend(_find_all(item, key))
    return out


def _first(obj, key):
    vals = _find_all(obj, key)
    return vals[0] if vals else None


def list_leagues(access_token: str) -> List[Dict[str, str]]:
    """The signed-in user's NFL leagues: [{league_key, name, season}]."""
    data = _api_get(access_token, "users;use_login=1/games;game_keys=nfl/leagues")
    leagues = []
    seen = set()
    for key in _find_all(data, "league_key"):
        if key in seen:
            continue
        seen.add(key)
        leagues.append({"league_key": key})
    # attach name/season by matching league blocks
    for block in _find_all(data, "league"):
        key = _first(block, "league_key")
        if not key:
            continue
        for lg in leagues:
            if lg["league_key"] == key:
                lg["name"] = _first(block, "name") or key
                lg["season"] = _first(block, "season")
    for lg in leagues:
        lg.setdefault("name", lg["league_key"])
    return leagues


def fetch_league(access_token: str, league_key: str) -> Dict[str, object]:
    """League settings + teams in the same shape as the ESPN importer."""
    settings = _api_get(access_token, f"league/{league_key}/settings")
    teams = _api_get(access_token, f"league/{league_key}/teams")
    return _parse_league(settings, teams, league_key)


def fetch_league_rosters(access_token: str, league_key: str) -> List[SyncedRosterTeam]:
    """Fetch every team roster in a Yahoo league.

    Yahoo roster data is team-scoped, so we list league teams first and then ask
    for each team's roster. Returned players are provider-neutral rows for the
    local matcher.
    """
    teams_data = _api_get(access_token, f"league/{league_key}/teams")
    teams: List[SyncedRosterTeam] = []
    for team_key, team_name in _team_key_names(teams_data):
        roster = _api_get(access_token, f"team/{team_key}/roster")
        teams.append(SyncedRosterTeam(
            name=team_name,
            provider_id=team_key,
            players=_parse_roster_players(roster, league_key),
        ))
    return teams


def _parse_league(settings: Dict, teams: Dict, league_key: str) -> Dict[str, object]:
    """Pure parse of Yahoo's nested settings/teams JSON (testable offline)."""
    name = _first(settings, "name") or league_key
    num_teams = _to_int(_first(settings, "num_teams")) or 0

    # Roster: roster_positions -> typed roster keys.
    roster: Dict[str, int] = {}
    for rp in _find_all(settings, "roster_position"):
        pos = rp.get("position") if isinstance(rp, dict) else None
        count = _to_int(rp.get("count")) if isinstance(rp, dict) else 0
        key = YAHOO_POS.get(pos)
        if key and count:
            roster[key] = roster.get(key, 0) + count
    for key in ("QB", "RB", "WR", "TE", "FLEX", "K", "DST", "BN"):
        roster.setdefault(key, 0)

    # Scoring: stat_modifiers value per stat_id -> app key.
    scoring: Dict[str, float] = {}
    for st in _find_all(settings, "stat"):
        if not isinstance(st, dict):
            continue
        sid = _to_int(st.get("stat_id"))
        if sid in YAHOO_STAT_IDS and st.get("value") is not None:
            try:
                scoring[YAHOO_STAT_IDS[sid]] = float(st["value"])
            except (TypeError, ValueError):
                pass

    # Team names (each team block carries name + a managers list).
    team_names: List[str] = []
    for tb in _find_all(teams, "team"):
        nm = _first(tb, "name")
        if isinstance(nm, str) and nm:
            team_names.append(nm)
    # de-dup preserving order
    seen = set()
    team_names = [n for n in team_names if not (n in seen or seen.add(n))]

    return {
        "name": name,
        "numTeams": num_teams or len(team_names) or 10,
        "rosterSlots": roster,
        "scoring": scoring,
        "teamNames": team_names,
        "yahooLeagueKey": league_key,
    }


def _team_key_names(teams: Dict) -> List[tuple[str, str]]:
    found: List[tuple[str, str]] = []
    seen = set()
    for block in _find_all(teams, "team"):
        team_key = _first(block, "team_key")
        name = _first(block, "name")
        if not team_key or team_key in seen:
            continue
        seen.add(team_key)
        found.append((str(team_key), str(name or team_key)))
    return found


def _parse_roster_players(roster: Dict, league_key: str) -> List[SyncedRosterPlayer]:
    out: List[SyncedRosterPlayer] = []
    game_key = league_key.split(".l.", 1)[0]
    for raw in _find_all(roster, "player"):
        flat = _flatten_yahoo_player(raw)
        name = flat.get("name")
        position = flat.get("position")
        player_id = flat.get("player_id")
        if not name or not position:
            continue
        provider_id = f"yahoo:{player_id}" if player_id else None
        # Yahoo player keys are game-scoped ("461.p.1234"). Keep the numeric id
        # for display/debug and leave matching primarily name+position based.
        if not provider_id and flat.get("player_key"):
            provider_id = f"yahoo:{str(flat['player_key']).replace(game_key + '.p.', '')}"
        out.append(SyncedRosterPlayer(
            name=name,
            position=position,
            team=flat.get("team"),
            provider_id=provider_id,
        ))
    return out


def _flatten_yahoo_player(raw) -> Dict[str, str]:
    flat: Dict[str, str] = {}

    def walk(obj):
        if isinstance(obj, dict):
            if "player_id" in obj:
                flat["player_id"] = str(obj["player_id"])
            if "player_key" in obj:
                flat["player_key"] = str(obj["player_key"])
            if "display_position" in obj:
                flat["position"] = str(obj["display_position"])
            if "editorial_team_abbr" in obj:
                flat["team"] = str(obj["editorial_team_abbr"])
            name = obj.get("name")
            if isinstance(name, dict) and name.get("full"):
                flat["name"] = str(name["full"])
            for value in obj.values():
                walk(value)
        elif isinstance(obj, list):
            for item in obj:
                walk(item)

    walk(raw)
    return flat


def _to_int(value) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
