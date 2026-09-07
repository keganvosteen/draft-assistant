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
import re
import time
from typing import Dict, List, Optional
from urllib.error import HTTPError
from urllib.parse import parse_qs, quote, urlencode, urlparse
from urllib.request import Request, urlopen

from ..platform_sync import SyncedDraftPick, SyncedRosterPlayer, SyncedRosterTeam

AUTH_URL = "https://api.login.yahoo.com/oauth2/request_auth"
TOKEN_URL = "https://api.login.yahoo.com/oauth2/get_token"
API_BASE = "https://fantasysports.yahooapis.com/fantasy/v2"
DEFAULT_REDIRECT = "oob"  # also works with a registered https://localhost/ URI

# Yahoo NFL stat_id -> app scoring key. Comprehensive league-specific mapping
# covering passing, rushing, receiving, fumbles, kicking, and defense/special teams.
YAHOO_STAT_IDS = {
    # Passing
    4: "pass_yd", 5: "pass_td", 6: "pass_int", 7: "pass_2pt",
    # Rushing
    9: "rush_yd", 10: "rush_td", 14: "rush_2pt",
    # Receiving
    11: "rec", 12: "rec_yd", 13: "rec_td", 15: "rec_2pt",
    # Misc / Turnovers
    16: "fumbles", 17: "fumbles_total",
    # Kicking
    19: "fg_0_19", 20: "fg_20_29", 21: "fg_30_39", 22: "fg_40_49",
    23: "fg_50_plus", 24: "fg_60_plus",
    25: "pat_made", 26: "fg_miss",
    # Defense / Special Teams
    27: "sack", 28: "def_int", 29: "fumble_recovery",
    30: "int_ret_td", 31: "safety", 32: "blk_kick", 33: "krt_td",
}

# Standard Yahoo stat names for dynamic matching against stat_categories definitions
YAHOO_STAT_NAMES = {
    "passing yards": "pass_yd",
    "passing touchdowns": "pass_td",
    "passing interceptions": "pass_int",
    "passing 2-point conversions": "pass_2pt",
    "2-point conversions": "pass_2pt",
    "rushing yards": "rush_yd",
    "rushing touchdowns": "rush_td",
    "rushing 2-point conversions": "rush_2pt",
    "receptions": "rec",
    "receiving yards": "rec_yd",
    "receiving touchdowns": "rec_td",
    "receiving 2-point conversions": "rec_2pt",
    "fumbles lost": "fumbles",
    "total fumbles": "fumbles_total",
    "fumbles": "fumbles_total",
    "field goals 0-19 yards": "fg_0_19",
    "field goals 20-29 yards": "fg_20_29",
    "field goals 30-39 yards": "fg_30_39",
    "field goals 40-49 yards": "fg_40_49",
    "field goals 50+ yards": "fg_50_plus",
    "field goals 50 yards or more": "fg_50_plus",
    "field goals 60+ yards": "fg_60_plus",
    "point after attempt made": "pat_made",
    "pat made": "pat_made",
    "point after attempt missed": "pat_miss",
    "field goals missed": "fg_miss",
    "sacks": "sack",
    "fumble recoveries": "fumble_recovery",
    "fumbles recovered": "fumble_recovery",
    "safeties": "safety",
    "blocked kicks": "blk_kick",
    "defensive touchdowns": "int_ret_td",
    "kickoff and punt return touchdowns": "krt_td",
    "return touchdowns": "krt_td",
}

# Yahoo roster-position label -> our roster key (typed flex preserved).
YAHOO_POS = {
    "QB": "QB", "RB": "RB", "WR": "WR", "TE": "TE", "K": "K", "DEF": "DST", "D": "DST",
    "W/R/T": "FLEX", "W/R": "RBWR", "W/T": "WRTE", "Q/W/R/T": "SUPERFLEX", "OP": "SUPERFLEX",
    "FLEX": "FLEX", "BN": "BN", "IR": "IR",
}


def extract_code(code_or_url: str) -> str:
    """Extract authorization code from either a raw code or a full redirect URL.

    Users frequently copy the full address bar after Yahoo redirects (e.g.
    ``https://localhost/?code=xyz123``). This reliably pulls out the code parameter.
    """
    raw = (code_or_url or "").strip()
    if "?" in raw or raw.startswith("http://") or raw.startswith("https://"):
        try:
            parsed = urlparse(raw)
            qs = parse_qs(parsed.query)
            if "code" in qs and qs["code"]:
                return qs["code"][0].strip()
        except Exception:
            pass
    if "code=" in raw:
        part = raw.split("code=", 1)[1]
        return part.split("&", 1)[0].strip()
    return raw


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

def _seg(value: object) -> str:
    """Escape a value being interpolated into a request path.

    League and team keys come from the browser. Yahoo's keys contain dots
    (``461.l.1234``), which ``quote`` leaves alone, but a ``?`` or ``../`` in a
    hand-supplied key would otherwise reshape the request.
    """
    return quote(str(value or ""), safe="")


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
        if "additional_authorization_required" in detail:
            raise RuntimeError(
                "Yahoo Fantasy Sports API access is not enabled for your Developer App ID yet. "
                "Yahoo requires submitting the access request form at https://sports.yahoo.com/developer/access/ "
                "to approve your Client ID for Fantasy Sports access."
            )
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
    settings = _api_get(access_token, f"league/{_seg(league_key)}/settings")
    teams = _api_get(access_token, f"league/{_seg(league_key)}/teams")
    return _parse_league(settings, teams, league_key)


def fetch_league_rosters(access_token: str, league_key: str) -> List[SyncedRosterTeam]:
    """Fetch every team roster in a Yahoo league.

    Yahoo roster data is team-scoped, so we list league teams first and then ask
    for each team's roster. Returned players are provider-neutral rows for the
    local matcher.
    """
    teams_data = _api_get(access_token, f"league/{_seg(league_key)}/teams")
    teams: List[SyncedRosterTeam] = []
    for team_key, team_name in _team_key_names(teams_data):
        roster = _api_get(access_token, f"team/{_seg(team_key)}/roster")
        teams.append(SyncedRosterTeam(
            name=team_name,
            provider_id=team_key,
            players=_parse_roster_players(roster, league_key),
        ))
    return teams


def _parse_scoring(settings: Dict) -> Dict[str, float]:
    """Parse league-specific scoring settings from Yahoo stat_modifiers and stat_categories."""
    id_map: Dict[int, str] = dict(YAHOO_STAT_IDS)

    # Enhance with named stat definitions from stat_categories if available
    for st in _find_all(settings, "stat"):
        if not isinstance(st, dict):
            continue
        sid = _to_int(st.get("stat_id"))
        if not sid:
            continue
        name = str(st.get("name") or "").strip().lower()
        pos_type = str(st.get("position_type") or "").strip().upper()
        if not name:
            continue
        if "interception" in name:
            id_map[sid] = "def_int" if pos_type in ("DT", "DEF", "DST") else "pass_int"
        elif "fumble" in name and "lost" in name:
            id_map[sid] = "fumbles"
        elif name in YAHOO_STAT_NAMES:
            id_map[sid] = YAHOO_STAT_NAMES[name]

    scoring: Dict[str, float] = {}
    for st in _find_all(settings, "stat"):
        if not isinstance(st, dict):
            continue
        sid = _to_int(st.get("stat_id"))
        val = st.get("value")
        if sid in id_map and val is not None:
            try:
                scoring[id_map[sid]] = float(val)
            except (TypeError, ValueError):
                pass

    # Bucket short field goals: if 0-19, 20-29, 30-39 are specified, take average for fg_0_39
    short_fgs = [scoring[k] for k in ("fg_0_19", "fg_20_29", "fg_30_39") if k in scoring]
    if short_fgs:
        scoring["fg_0_39"] = round(sum(short_fgs) / len(short_fgs), 3)

    # 50+ kicks: spread across fg_50_59 and fg_60_plus if not separately configured
    if "fg_50_plus" in scoring:
        val = scoring.pop("fg_50_plus")
        scoring.setdefault("fg_50_59", val)
        scoring.setdefault("fg_60_plus", val)

    # Defensive & return TDs: ensure both interception and fumble return TDs are credited
    if "int_ret_td" in scoring:
        scoring.setdefault("fum_ret_td", scoring["int_ret_td"])
    if "krt_td" in scoring:
        scoring.setdefault("prt_td", scoring["krt_td"])

    return scoring


def _parse_teams(teams: Dict) -> List[Dict]:
    """Parse team metadata: team_key, name, draft_position, and user login ownership."""
    parsed: List[Dict] = []
    seen = set()
    for tb in _find_all(teams, "team"):
        team_key = _first(tb, "team_key")
        if not team_key or team_key in seen:
            continue
        name = _first(tb, "name") or team_key
        draft_pos = _to_int(_first(tb, "draft_position"))
        # Check current login ownership at team level and within manager blocks
        is_owned = _first(tb, "is_owned_by_current_login") in (1, "1", True)
        for mgr in _find_all(tb, "manager"):
            if isinstance(mgr, dict) and mgr.get("is_current_login") in (1, "1", True):
                is_owned = True
        seen.add(team_key)
        parsed.append({
            "team_key": str(team_key),
            "name": str(name),
            "draft_position": draft_pos,
            "is_current_login": is_owned,
        })
    return parsed


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

    scoring = _parse_scoring(settings)

    parsed_teams = _parse_teams(teams)
    # When Yahoo provides draft_position on teams, sort by it so teamNames are in draft order
    has_positions = any(t.get("draft_position") is not None for t in parsed_teams)
    if has_positions:
        parsed_teams.sort(key=lambda t: t.get("draft_position") or 999)

    team_names = [t["name"] for t in parsed_teams if t.get("name")]

    # Detect user's own team and draft seat
    user_team = next((t for t in parsed_teams if t.get("is_current_login")), None)
    draft_position = None
    if user_team:
        if user_team.get("draft_position"):
            draft_position = user_team["draft_position"]
        elif user_team["name"] in team_names:
            draft_position = team_names.index(user_team["name"]) + 1

    draft_type_raw = str(_first(settings, "draft_type") or "").lower()
    draft_type = "auction" if "auction" in draft_type_raw else "snake"
    draft_status = str(_first(settings, "draft_status") or "")
    season = str(_first(settings, "season") or "")

    out: Dict[str, object] = {
        "name": name,
        "numTeams": num_teams or len(team_names) or 10,
        "rosterSlots": roster,
        "scoring": scoring,
        "teamNames": team_names,
        "yahooLeagueKey": league_key,
        "draftType": draft_type,
    }
    if season:
        out["season"] = season
    if draft_status:
        out["draftStatus"] = draft_status
    if draft_position:
        out["draftPosition"] = draft_position
    if user_team and user_team.get("name"):
        out["myTeamName"] = user_team["name"]

    return out


def fetch_draft_picks(access_token: str, league_key: str) -> List[SyncedDraftPick]:
    """Fetch real draft picks from Yahoo's draftresults API in pick order."""
    draft_data = _api_get(access_token, f"league/{_seg(league_key)}/draftresults")
    teams_data = _api_get(access_token, f"league/{_seg(league_key)}/teams")
    rosters: Optional[List[SyncedRosterTeam]] = None
    try:
        rosters = fetch_league_rosters(access_token, league_key)
    except Exception:
        pass
    return _parse_draft_picks(draft_data, teams_data, rosters)


def _parse_draft_picks(
    draft_data: Dict,
    teams_data: Dict,
    rosters: Optional[List[SyncedRosterTeam]] = None,
) -> List[SyncedDraftPick]:
    """Pure parse of Yahoo draft results into SyncedDraftPick objects."""
    parsed_teams = _parse_teams(teams_data)
    seat_by_team: Dict[str, int] = {}
    for idx, t in enumerate(parsed_teams, 1):
        seat = t.get("draft_position") or idx
        seat_by_team[t["team_key"]] = seat

    player_by_key: Dict[str, SyncedRosterPlayer] = {}
    if rosters:
        for team in rosters:
            for p in team.players:
                if p.provider_id:
                    pid = p.provider_id.split(":", 1)[-1]
                    player_by_key[pid] = p
                    player_by_key[p.provider_id] = p
                if p.name:
                    player_by_key[p.name] = p

    picks: List[SyncedDraftPick] = []
    for dr in _find_all(draft_data, "draft_result"):
        if not isinstance(dr, dict):
            continue
        pick_no = _to_int(dr.get("pick"))
        if not pick_no:
            continue
        team_key = str(dr.get("team_key") or "")
        team_num = seat_by_team.get(team_key, 0)
        player_key = str(dr.get("player_key") or "")
        player_id = player_key.split(".p.", 1)[-1] if ".p." in player_key else player_key

        flat = _flatten_yahoo_player(dr)
        name = flat.get("name")
        position = flat.get("position")
        team = flat.get("team")

        if (not name or not position) and (player_id in player_by_key or player_key in player_by_key):
            matched_rp = player_by_key.get(player_id) or player_by_key.get(player_key)
            if matched_rp:
                name = name or matched_rp.name
                position = position or matched_rp.position
                team = team or matched_rp.team

        provider_id = f"yahoo:{player_id}" if player_id else None
        picks.append(SyncedDraftPick(
            pick_no=pick_no,
            team_num=team_num,
            player=SyncedRosterPlayer(
                name=name or f"Player {player_id}",
                position=position or "",
                team=team,
                provider_id=provider_id,
            ),
        ))

    picks.sort(key=lambda p: p.pick_no)
    return picks


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
            player_key = str(flat["player_key"])
            provider_id = f"yahoo:{player_key.replace(game_key + '.p.', '')}"
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


def parse_settings_text(text: str) -> Dict[str, object]:
    """Parse copied/pasted text from a Yahoo Fantasy league settings page."""
    raw = text.strip()
    if not raw:
        raise ValueError("Please paste your Yahoo league settings text")

    # 1. League name
    name = "Yahoo League"
    name_m = re.search(r"(?:League Name|League)\s*[:\t]?\s*([^\n\r]+)", raw, re.I)
    if name_m:
        val = name_m.group(1).strip()
        if val and not val.lower().startswith("settings"):
            name = val
    else:
        first_line = raw.splitlines()[0].strip()
        if first_line and len(first_line) < 50 and not any(k in first_line.lower() for k in ("http", "settings", "draft")):
            name = first_line

    # 2. Number of teams
    teams_m = re.search(r"(?:Max Teams|Teams|Number of Teams)\s*[:\t]?\s*(\d+)", raw, re.I)
    num_teams = int(teams_m.group(1)) if teams_m else 10

    # 3. Draft type
    draft_type = "snake"
    dt_m = re.search(r"Draft Type\s*[:\t]?\s*([^\n\r]+)", raw, re.I)
    if dt_m and any(k in dt_m.group(1).lower() for k in ("auction", "salary cap")):
        draft_type = "auction"

    # 4. Roster positions
    roster = {"QB": 0, "RB": 0, "WR": 0, "TE": 0, "FLEX": 0, "K": 0, "DST": 0, "BN": 0}
    pos_m = re.search(r"Roster Positions\s*[:\t]?\s*([^\n\r]+)", raw, re.I)
    if pos_m:
        tokens = [p.strip().upper() for p in pos_m.group(1).split(",") if p.strip()]
        for tok in tokens:
            key = YAHOO_POS.get(tok)
            if key:
                roster[key] = roster.get(key, 0) + 1
    else:
        line_patterns = [
            (r"(?:Quarterback|QB)\b.*?[:\t]?\s*(\d+)", "QB"),
            (r"(?:Running Back|RB)\b.*?[:\t]?\s*(\d+)", "RB"),
            (r"(?:Wide Receiver|WR)\b.*?[:\t]?\s*(\d+)", "WR"),
            (r"(?:Tight End|TE)\b.*?[:\t]?\s*(\d+)", "TE"),
            (r"(?:W/R/T|Flex|W/R/T/Q)\b.*?[:\t]?\s*(\d+)", "FLEX"),
            (r"(?:W/T)\b.*?[:\t]?\s*(\d+)", "WRTE"),
            (r"(?:R/W|W/R)\b.*?[:\t]?\s*(\d+)", "RBWR"),
            (r"(?:Superflex|Q/W/R/T)\b.*?[:\t]?\s*(\d+)", "SUPERFLEX"),
            (r"(?:Kicker|K)\b.*?[:\t]?\s*(\d+)", "K"),
            (r"(?:Defense/Special Teams|Defense|DEF|DST)\b.*?[:\t]?\s*(\d+)", "DST"),
            (r"(?:Bench|BN)\b.*?[:\t]?\s*(\d+)", "BN"),
            (r"(?:Injured Reserve|IR)\b.*?[:\t]?\s*(\d+)", "IR"),
        ]
        for pat, key in line_patterns:
            m = re.search(pat, raw, re.I)
            if m:
                roster[key] = int(m.group(1))

    if not any(roster.values()):
        roster = {"QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 1, "K": 1, "DST": 1, "BN": 6}

    # 5. Scoring settings
    scoring = {}
    def _parse_num(pat, default=None):
        m = re.search(pat, raw, re.I)
        if not m:
            return default
        try:
            return float(m.group(1))
        except (ValueError, TypeError):
            return default

    # Passing
    pass_yd_raw = _parse_num(r"Passing Yards?\s*[:\t]?\s*(\d+(?:\.\d+)?)")
    if pass_yd_raw is not None:
        scoring["pass_yd"] = round(1.0 / pass_yd_raw, 4) if pass_yd_raw >= 1 else pass_yd_raw
    else:
        scoring["pass_yd"] = 0.04

    scoring["pass_td"] = _parse_num(r"Passing Touchdowns?\s*[:\t]?\s*([+-]?\d+(?:\.\d+)?)", 4.0)
    scoring["pass_int"] = _parse_num(r"(?:Interceptions|Interceptions Thrown|Pass Int)\s*[:\t]?\s*([+-]?\d+(?:\.\d+)?)", -2.0)

    # Rushing
    rush_yd_raw = _parse_num(r"Rushing Yards?\s*[:\t]?\s*(\d+(?:\.\d+)?)")
    if rush_yd_raw is not None:
        scoring["rush_yd"] = round(1.0 / rush_yd_raw, 4) if rush_yd_raw >= 1 else rush_yd_raw
    else:
        scoring["rush_yd"] = 0.1

    scoring["rush_td"] = _parse_num(r"Rushing Touchdowns?\s*[:\t]?\s*([+-]?\d+(?:\.\d+)?)", 6.0)

    # Receiving
    rec = _parse_num(r"Receptions?\s*[:\t]?\s*([+-]?\d+(?:\.\d+)?)", 0.5)
    scoring["rec"] = rec
    rec_yd_raw = _parse_num(r"Receiving Yards?\s*[:\t]?\s*(\d+(?:\.\d+)?)")
    if rec_yd_raw is not None:
        scoring["rec_yd"] = round(1.0 / rec_yd_raw, 4) if rec_yd_raw >= 1 else rec_yd_raw
    else:
        scoring["rec_yd"] = 0.1
    scoring["rec_td"] = _parse_num(r"Receiving Touchdowns?\s*[:\t]?\s*([+-]?\d+(?:\.\d+)?)", 6.0)

    # 2PT & Fumbles
    two_pt = _parse_num(r"(?:2-Point Conversions?|2PT Conversions?)\s*[:\t]?\s*([+-]?\d+(?:\.\d+)?)", 2.0)
    scoring["pass_2pt"] = _parse_num(r"Passing 2-Point Conversions?\s*[:\t]?\s*([+-]?\d+(?:\.\d+)?)", two_pt)
    scoring["rush_2pt"] = _parse_num(r"Rushing 2-Point Conversions?\s*[:\t]?\s*([+-]?\d+(?:\.\d+)?)", two_pt)
    scoring["rec_2pt"] = _parse_num(r"Receiving 2-Point Conversions?\s*[:\t]?\s*([+-]?\d+(?:\.\d+)?)", two_pt)
    scoring["fumbles"] = _parse_num(r"Fumbles Lost\s*[:\t]?\s*([+-]?\d+(?:\.\d+)?)", -2.0)
    fumbles_tot = _parse_num(r"(?:Total Fumbles|Fumbles Total|Fumbles \(Total\))\s*[:\t]?\s*([+-]?\d+(?:\.\d+)?)")
    if fumbles_tot is not None:
        scoring["fumbles_total"] = fumbles_tot

    # Defense
    scoring["sack"] = _parse_num(r"Sacks?\s*[:\t]?\s*([+-]?\d+(?:\.\d+)?)", 1.0)
    scoring["def_int"] = _parse_num(r"(?:Interception Return|Interceptions? \(DEF\))\s*[:\t]?\s*([+-]?\d+(?:\.\d+)?)", 2.0)
    scoring["fumble_recovery"] = _parse_num(r"Fumble Recover(?:y|ies)\s*[:\t]?\s*([+-]?\d+(?:\.\d+)?)", 2.0)
    def_td = _parse_num(r"(?:Touchdown \(DEF\)|Defensive Touchdowns?)\s*[:\t]?\s*([+-]?\d+(?:\.\d+)?)", 6.0)
    scoring["int_ret_td"] = def_td
    scoring["fum_ret_td"] = def_td
    scoring["safety"] = _parse_num(r"Safet(?:y|ies)\s*[:\t]?\s*([+-]?\d+(?:\.\d+)?)", 2.0)
    scoring["blk_kick"] = _parse_num(r"Blocked? Kicks?\s*[:\t]?\s*([+-]?\d+(?:\.\d+)?)", 2.0)

    # Kicking
    fg_0_19 = _parse_num(r"Field Goals? 0-19 Yards?\s*[:\t]?\s*([+-]?\d+(?:\.\d+)?)")
    fg_20_29 = _parse_num(r"Field Goals? 20-29 Yards?\s*[:\t]?\s*([+-]?\d+(?:\.\d+)?)")
    fg_30_39 = _parse_num(r"Field Goals? 30-39 Yards?\s*[:\t]?\s*([+-]?\d+(?:\.\d+)?)")
    fg_short = [v for v in (fg_0_19, fg_20_29, fg_30_39) if v is not None]
    if fg_short:
        scoring["fg_0_39"] = round(sum(fg_short) / len(fg_short), 2)
    else:
        scoring["fg_0_39"] = 3.0

    scoring["fg_40_49"] = _parse_num(r"Field Goals? 40-49 Yards?\s*[:\t]?\s*([+-]?\d+(?:\.\d+)?)", 4.0)
    fg_50 = _parse_num(r"Field Goals? 50\+ Yards?\s*[:\t]?\s*([+-]?\d+(?:\.\d+)?)", 5.0)
    scoring["fg_50_59"] = fg_50
    scoring["fg_60_plus"] = fg_50
    scoring["pat_made"] = _parse_num(r"(?:Point After Attempt Made|PAT Made)\s*[:\t]?\s*([+-]?\d+(?:\.\d+)?)", 1.0)
    fg_miss = _parse_num(r"Field Goals? Missed\s*[:\t]?\s*([+-]?\d+(?:\.\d+)?)")
    if fg_miss is not None:
        scoring["fg_miss"] = fg_miss

    scoring_type = "ppr" if rec >= 0.9 else "half-ppr" if rec >= 0.4 else "standard"

    # Team names if present
    team_names = []
    for line in raw.splitlines():
        line = line.strip()
        tm = re.match(r"^\d+[\.\)]\s+([A-Za-z0-9\s_\-\.']+?)(?:\s+\(.*?\))?$", line)
        if tm:
            candidate = tm.group(1).strip()
            if len(candidate) > 1 and candidate not in team_names:
                team_names.append(candidate)

    out: Dict[str, object] = {
        "name": name,
        "platform": "Yahoo",
        "numTeams": num_teams,
        "draftType": draft_type,
        "rosterSlots": roster,
        "scoring": scoring,
        "scoringType": scoring_type,
    }
    if team_names and len(team_names) >= 2:
        out["teamNames"] = team_names[:num_teams]
    return out
