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
import math
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
APPROVAL_URL = "https://sports.yahoo.com/developer/access/"


class YahooAPIError(RuntimeError):
    """A safe message and stable error code for Yahoo's HTTP failures."""

    def __init__(self, message: str, *, status: int = 502, code: str = "yahoo_api_error"):
        super().__init__(message)
        self.status = status
        self.code = code


def _http_error(exc: HTTPError, *, token_request: bool = False) -> YahooAPIError:
    with exc:
        detail = exc.read(8192).decode("utf-8", "replace")
    challenge = str(exc.headers.get("WWW-Authenticate", "")) if exc.headers else ""
    if "additional_authorization_required" in detail + challenge:
        return YahooAPIError(
            "Yahoo has not granted Fantasy Sports API access to this connection. "
            "Check that this Client ID has approved Fantasy Sports read access. "
            "If its permissions changed, authorize again. You can import copied league settings while access is pending.",
            status=403, code="yahoo_additional_authorization_required",
        )
    if token_request:
        return YahooAPIError(
            "Yahoo could not authorize this connection. Check the saved Client ID, secret, and redirect URI, "
            "then get a new authorize link and paste its new code or redirect URL.",
            status=401, code="yahoo_auth_required",
        )
    if exc.code == 401:
        return YahooAPIError("Your Yahoo authorization has expired or was revoked. Authorize with Yahoo again.",
                             status=401, code="yahoo_auth_required")
    if exc.code == 403:
        return YahooAPIError("Yahoo denied access to this league. Check this account's league membership and Fantasy Sports permissions.",
                             status=403, code="yahoo_access_denied")
    if exc.code == 429:
        return YahooAPIError("Yahoo is limiting requests. Wait a moment and retry.", status=429)
    return YahooAPIError(f"Yahoo returned HTTP {exc.code}. Please retry.")

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

    Yahoo's authorization-code flow requests the app's approved permissions.
    Fantasy Sports read access requires approval for this Client ID; adding an
    identity scope cannot grant that access.
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
        raise _http_error(exc, token_request=True) from None
    if not isinstance(tok, dict) or not tok.get("access_token"):
        raise YahooAPIError("Yahoo did not return an access token. Get a new authorize link and try again.",
                             status=401, code="yahoo_auth_required")
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
        raise _http_error(exc) from None


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
        team_key = str(_first(tb, "team_key") or "").strip()
        if not team_key or team_key in seen:
            continue
        name = str(_first(tb, "name") or "").strip() or team_key
        position_text = str(_first(tb, "draft_position") or "")
        draft_pos = int(position_text) if re.fullmatch(r"[0-9]+", position_text) else None
        # Check current login ownership at team level and within manager blocks
        is_owned = _first(tb, "is_owned_by_current_login") in (1, "1", True)
        for mgr in _find_all(tb, "manager"):
            if isinstance(mgr, dict) and mgr.get("is_current_login") in (1, "1", True):
                is_owned = True
        seen.add(team_key)
        parsed.append({
            "team_key": team_key,
            "name": name,
            "draft_position": draft_pos,
            "is_current_login": is_owned,
        })
    return parsed


def _complete_draft_order(teams: List[Dict], num_teams: int) -> bool:
    """Only a complete, unique seat permutation represents a published order."""
    return (num_teams > 0 and len(teams) == num_teams
            and {team["draft_position"] for team in teams} == set(range(1, num_teams + 1)))


def fetch_draft_analysis(access_token: str, league_key: str,
                         limit: int = 400) -> List[Dict[str, object]]:
    """Yahoo's league-wide draft analysis: real ADP from actual Yahoo drafts.

    Pages through the league's player collection (Yahoo caps pages at 25)
    sorted by Yahoo's overall rank, reading the ``draft_analysis``
    subresource: ``average_pick``, ``average_round``, ``average_cost``,
    ``percent_drafted``. Undrafted players report ``"-"`` — those rows are
    skipped, and paging stops once a full page has no drafted players
    (the sort means everyone after that is deeper still).

    This is the ADP board the user's actual draft room runs on, which makes
    it a better availability signal for a Yahoo league than the public
    FFC/Sleeper boards.
    """
    rows: List[Dict[str, object]] = []
    start = 0
    while start < limit:
        count = min(25, limit - start)
        data = _api_get(
            access_token,
            f"league/{_seg(league_key)}/players;start={start};count={count};sort=OR/draft_analysis",
        )
        page = _find_all(data, "player")
        if not page:
            break
        page_rows = 0
        for raw in page:
            flat = _flatten_yahoo_player(raw)
            avg_pick = _to_float(flat.get("average_pick"))
            if not flat.get("name") or not flat.get("position"):
                continue
            if avg_pick is None or avg_pick <= 0:
                continue
            rows.append({
                "name": flat["name"],
                "position": str(flat["position"]).split(",")[0].strip().upper(),
                "team": (flat.get("team") or "").upper() or None,
                "average_pick": avg_pick,
                "average_round": _to_float(flat.get("average_round")),
                "average_cost": _to_float(flat.get("average_cost")),
                "percent_drafted": _to_float(flat.get("percent_drafted")),
            })
            page_rows += 1
        if page_rows == 0:
            break
        start += len(page)
        if len(page) < count:
            break
    return rows



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
    num_teams = num_teams if num_teams > 0 else len(parsed_teams) or 10
    order_ready = _complete_draft_order(parsed_teams, num_teams)
    # Before Yahoo publishes every seat, use stable IDs for display order only.
    # Partial draft positions and API collection order cannot determine a draft.
    parsed_teams.sort(key=lambda t: t["draft_position"] if order_ready else t["team_key"])
    team_names = [t["name"] for t in parsed_teams]
    team_ids = [t["team_key"] for t in parsed_teams]
    owned_teams = [t for t in parsed_teams if t["is_current_login"]]
    user_team = owned_teams[0] if len(owned_teams) == 1 else None
    # The app also uses this index to select a roster when order is unpublished.
    draft_position = team_ids.index(user_team["team_key"]) + 1 if user_team else None

    draft_type_raw = str(_first(settings, "draft_type") or "").lower()
    draft_type = "auction" if "auction" in draft_type_raw else "snake"
    draft_status = str(_first(settings, "draft_status") or "")
    season = str(_first(settings, "season") or "")

    out: Dict[str, object] = {
        "name": name,
        "numTeams": num_teams,
        "rosterSlots": roster,
        "scoring": scoring,
        "teamNames": team_names,
        "teamIds": team_ids,
        "draftOrderReady": order_ready,
        "teamSelectionRequired": user_team is None,
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
        out["myTeamId"] = user_team["team_key"]

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
    num_teams = _to_int(_first(teams_data, "num_teams")) or len(parsed_teams)
    order_ready = _complete_draft_order(parsed_teams, num_teams)
    seat_by_team = {t["team_key"]: t["draft_position"] for t in parsed_teams} if order_ready else {}

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
        team_key = str(dr.get("team_key") or "").strip()
        if not team_key:
            raise ValueError("Yahoo returned a draft pick without a team ID. Retry before replacing recorded picks.")
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
            provider_team_id=team_key,
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
    return [(team["team_key"], team["name"]) for team in _parse_teams(teams)]


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
            # draft_analysis fields (fetch_draft_analysis); "-" means undrafted.
            for key in ("average_pick", "average_round", "average_cost", "percent_drafted"):
                if key in obj and not isinstance(obj[key], (dict, list)):
                    flat[key] = str(obj[key])
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


def _to_float(value) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_settings_text(text: str) -> Dict[str, object]:
    """Read labelled Yahoo settings without inventing missing league values."""
    raw = text.strip().replace("\u00a0", " ")
    if not raw:
        raise ValueError("Please paste your Yahoo league settings text")

    def field(*labels: str, scope: str = raw) -> Optional[str]:
        # Clipboard tables can put a value after a colon, tab, or newline.
        # Exact, anchored labels avoid confusing League ID with League Name,
        # or the K at the end of Quarterback with the kicker roster row.
        pattern = (
            r"^[ \t]*(?:" + "|".join(re.escape(label) for label in labels) + r")"
            r"(?:[ \t]*:[ \t]*|[ \t]*\t[ \t]*| {2,}|\r?\n[ \t]*)"
            r"([^\r\n]+)"
        )
        values = list(dict.fromkeys(
            match.group(1).strip()
            for match in re.finditer(pattern, scope, re.I | re.M)
        ))
        if len(values) > 1:
            raise ValueError(f"Conflicting values for {labels[0]}; paste one league's settings page.")
        return values[0] if values else None

    name = field("League Name") or field("League")
    teams_text = field("Max Teams", "Number of Teams", "Teams")
    if not name or not teams_text:
        raise ValueError("Include League Name and Max Teams when copying your Yahoo settings page.")
    if not teams_text.isdigit() or not 2 <= int(teams_text) <= 32:
        raise ValueError("Max Teams must be a whole number between 2 and 32.")
    num_teams = int(teams_text)

    roster = {key: 0 for key in ("QB", "RB", "WR", "TE", "FLEX", "K", "DST", "BN")}
    positions = field("Roster Positions")
    if positions:
        for token in positions.split(","):
            label = token.strip().upper()
            key = YAHOO_POS.get(label)
            if not key:
                raise ValueError(f"Unsupported roster position '{label}'; review the copied Roster Positions row.")
            roster[key] = roster.get(key, 0) + 1
    else:
        roster_labels = {
            "QB": ("Quarterback", "QB", "Quarterback (QB)"),
            "RB": ("Running Back", "RB", "Running Back (RB)"),
            "WR": ("Wide Receiver", "WR", "Wide Receiver (WR)"),
            "TE": ("Tight End", "TE", "Tight End (TE)"),
            "FLEX": ("Flex", "W/R/T", "Flex (W/R/T)"),
            "WRTE": ("W/T", "Flex (W/T)"),
            "RBWR": ("W/R", "R/W", "Flex (W/R)", "Flex (R/W)"),
            "SUPERFLEX": ("Superflex", "Q/W/R/T", "W/R/T/Q", "Superflex (Q/W/R/T)"),
            "K": ("Kicker", "K", "Kicker (K)"),
            "DST": ("Defense/Special Teams", "Defense", "DEF", "DST", "Defense (DEF)"),
            "BN": ("Bench", "BN", "Bench (BN)"),
            "IR": ("Injured Reserve", "IR", "Injured Reserve (IR)"),
        }
        for key, labels in roster_labels.items():
            count = field(*labels)
            if count is None:
                continue
            if not count.isdigit() or not 0 <= int(count) <= 30:
                raise ValueError(f"{labels[0]} roster count must be a whole number from 0 to 30.")
            roster[key] = int(count)
    if not any(count for key, count in roster.items() if key != "IR"):
        raise ValueError("No roster positions were found. Copy the complete Yahoo league settings page.")
    if sum(roster.values()) > 50:
        raise ValueError("The imported roster may contain at most 50 slots.")

    def number(*labels: str, yards: bool = False, scope: str = raw) -> Optional[float]:
        value = field(*labels, scope=scope)
        if value is None:
            return None
        match = re.fullmatch(
            r"([+-]?(?:\d+(?:\.\d*)?|\.\d+))\s*(?:(yards? per point)|(points?(?: per yard)?))?",
            value, re.I,
        )
        if not match:
            raise ValueError(
                f"Could not import {labels[0]} value '{value}'. "
                "Bonus formulas or other extra rules need manual review."
            )
        parsed = float(match.group(1))
        if not math.isfinite(parsed):
            raise ValueError(f"{labels[0]} must be a finite number.")
        if match.group(2):
            if not yards or parsed <= 0:
                raise ValueError(f"{labels[0]} yards per point must be greater than zero.")
            parsed = round(1.0 / parsed, 6)
        return parsed

    scoring = {}
    scoring_labels = {
        "pass_yd": ("Passing Yards", "Passing Yard"),
        "pass_td": ("Passing Touchdowns", "Passing Touchdown"),
        "rush_yd": ("Rushing Yards", "Rushing Yard"),
        "rush_td": ("Rushing Touchdowns", "Rushing Touchdown"),
        "rec": ("Receptions", "Reception"),
        "rec_yd": ("Receiving Yards", "Receiving Yard"),
        "rec_td": ("Receiving Touchdowns", "Receiving Touchdown"),
        "fumbles": ("Fumbles Lost",),
        "fumbles_total": ("Total Fumbles", "Fumbles Total", "Fumbles (Total)"),
        "sack": ("Sacks", "Sack"),
        "fumble_recovery": ("Fumble Recoveries", "Fumble Recovery"),
        "int_ret_td": ("Touchdown (DEF)", "Defensive Touchdowns", "Defensive Touchdown"),
        "safety": ("Safeties", "Safety"),
        "blk_kick": ("Blocked Kicks", "Blocked Kick", "Block Kicks"),
        "krt_td": ("Kickoff and Punt Return Touchdowns", "Return Touchdowns"),
        "fg_0_19": ("Field Goals 0-19 Yards",),
        "fg_20_29": ("Field Goals 20-29 Yards",),
        "fg_30_39": ("Field Goals 30-39 Yards",),
        "fg_40_49": ("Field Goals 40-49 Yards",),
        "fg_50_59": ("Field Goals 50+ Yards", "Field Goals 50-59 Yards"),
        "fg_60_plus": ("Field Goals 60+ Yards",),
        "pat_made": ("Point After Attempt Made", "PAT Made"),
        "pat_miss": ("Point After Attempt Missed", "PAT Missed"),
        "fg_miss": ("Field Goals Missed", "Field Goal Missed"),
    }
    for key, labels in scoring_labels.items():
        value = number(*labels, yards=key in {"pass_yd", "rush_yd", "rec_yd"})
        if value is not None:
            scoring[key] = value

    # Yahoo uses "Interceptions" in both its offense and defense tables. Keep
    # those sections separate instead of applying the first value to both.
    defense = re.search(
        r"^[ \t]*(?:Defense(?:/Special Teams)?[ \t]*$|Sacks?[ \t]*(?::|\t|\r?$))",
        raw, re.I | re.M,
    )
    offense_text = raw[:defense.start()] if defense else raw
    defense_text = raw[defense.start():] if defense else ""
    pass_int = number("Passing Interceptions", "Interceptions Thrown", "Pass Int")
    if pass_int is None:
        pass_int = number("Interceptions", "Interception", scope=offense_text)
    if pass_int is not None:
        scoring["pass_int"] = pass_int
    def_int = number("Interception Return", "Interceptions (DEF)")
    if def_int is None:
        def_int = number("Interceptions", "Interception", scope=defense_text)
    if def_int is not None:
        scoring["def_int"] = def_int

    two_pt = number("2-Point Conversions", "2-Point Conversion", "2PT Conversions")
    for key, label in (("pass_2pt", "Passing"), ("rush_2pt", "Rushing"), ("rec_2pt", "Receiving")):
        value = number(f"{label} 2-Point Conversions", f"{label} 2-Point Conversion")
        if value is not None or two_pt is not None:
            scoring[key] = value if value is not None else two_pt
    for source, destination in (
        ("int_ret_td", "fum_ret_td"), ("krt_td", "prt_td"), ("fg_50_59", "fg_60_plus"),
    ):
        if source in scoring:
            scoring.setdefault(destination, scoring[source])
    short_fgs = [scoring[key] for key in ("fg_0_19", "fg_20_29", "fg_30_39") if key in scoring]
    if short_fgs:
        scoring["fg_0_39"] = round(sum(short_fgs) / len(short_fgs), 3)
    if not scoring:
        raise ValueError("No scoring values were found. Include the scoring tables when copying Yahoo settings.")

    out: Dict[str, object] = {
        "name": name,
        "platform": "Yahoo",
        "numTeams": num_teams,
        "rosterSlots": roster,
        "scoring": scoring,
        "draftOrderReady": False,
    }
    draft_type = field("Draft Type")
    if draft_type:
        if any(word in draft_type.lower() for word in ("auction", "salary cap")):
            out["draftType"] = "auction"
        elif any(word in draft_type.lower() for word in ("standard", "snake", "autopick", "offline")):
            out["draftType"] = "snake"
        else:
            raise ValueError(f"Unrecognized Draft Type '{draft_type}'; check the copied settings.")
    rec = scoring.get("rec", 0)
    out["scoringType"] = "ppr" if rec >= 0.9 else "half-ppr" if rec >= 0.4 else "standard"
    missing = [
        label for key, label in (
            ("pass_yd", "passing yards"), ("pass_td", "passing touchdowns"),
            ("pass_int", "passing interceptions"), ("rush_yd", "rushing yards"),
            ("rush_td", "rushing touchdowns"), ("rec", "receptions"),
            ("rec_yd", "receiving yards"), ("rec_td", "receiving touchdowns"),
            ("fumbles", "fumbles lost"),
        ) if key not in scoring
    ]
    warnings = []
    if missing:
        warnings.append("No copied value for " + ", ".join(missing) + "; review scoring before saving.")
    if not draft_type:
        warnings.append("No draft type found; review it on the Basics tab.")
    if warnings:
        out["importWarnings"] = warnings

    team_names = []
    for line in raw.splitlines():
        match = re.match(r"^\s*\d+[.)]\s+([A-Za-z0-9\s_\-.']+?)(?:\s+\(.*?\))?\s*$", line)
        if match and len(match.group(1).strip()) > 1:
            candidate = match.group(1).strip()
            if candidate not in team_names:
                team_names.append(candidate)
    if len(team_names) >= 2:
        out["teamNames"] = team_names[:num_teams]
    return out

