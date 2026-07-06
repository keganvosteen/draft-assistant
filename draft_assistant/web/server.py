"""Lightweight HTTP server for the Draft Assistant web UI.

Serves static files from ./static/ and exposes a thin JSON API so the
React frontend can load player data from the Python backend.
"""
from __future__ import annotations

import json
import os
import threading
import time
import traceback
import webbrowser
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional

from ..models import DraftState, LeagueConfig
from ..profiles import DEFAULT_PROFILE, ensure_profile, load_profile_config
from ..providers.base import build_provider
from ..free_agents import free_agent_recommendations
from ..platform_sync import synced_rosters_to_picks
from ..rollout import rollout_values
from ..sample_data import sample_players
from ..scoring import fantasy_points
from ..storage import load_players, load_state, save_players, save_state
from .scoring import STANDARD_SCORING, scoring_for_league

STATIC_DIR = Path(__file__).parent / "static"

# Last-resort fallback only (a past season's byes — goes stale). Byes are
# preferred from player data, then from per-team byes derived from that data.
BYE_WEEKS = {
    "ARI": 13, "ATL": 12, "BAL": 8, "BUF": 6, "CAR": 6, "CHI": 14,
    "CIN": 8, "CLE": 14, "DAL": 10, "DEN": 11, "DET": 5, "GB": 13,
    "HOU": 11, "IND": 11, "JAX": 11, "KC": 6, "LAC": 10, "LAR": 5,
    "LV": 12, "MIA": 9, "MIN": 13, "NE": 14, "NO": 12, "NYG": 11,
    "NYJ": 7, "PHI": 7, "PIT": 14, "SEA": 14, "SF": 10, "TB": 9,
    "TEN": 9, "WAS": 14,
}


def _team_byes_from_players(players) -> dict:
    """Derive each team's bye week from whichever players carry one.

    This self-heals every season from pulled data instead of relying on the
    hardcoded table above.
    """
    byes: dict = {}
    for player in players:
        if player.team and player.bye_week and player.team not in byes:
            byes[player.team] = player.bye_week
    return byes

# Tracks background tasks (pull-free-data, collect-all, etc.)
_tasks: dict[str, dict] = {}
_task_lock = threading.Lock()


def _player_to_js(player, config: LeagueConfig, team_byes: Optional[dict] = None) -> dict:
    """Convert a Python Player to the JS frontend's expected format.

    stdPts is standard (0 pt/rec) scoring; recPts is the full 1-pt-per-reception
    bonus so the frontend computes: ppr = stdPts + recPts, half = stdPts + 0.5*recPts.
    K/DST don't vary with reception format, so they are scored with the league's
    own scoring config (STANDARD_SCORING has no kicker/defense stat weights).
    """
    # Board scoring runs through the same historical/age model as Auction + CLI,
    # so accumulated history and aging shape the rankings — not just raw
    # current-season projections.
    if player.age is not None or player.historical_stats:
        from ..historical import adjust_projections
        proj = adjust_projections(player, config.scoring)
    else:
        proj = player.projections

    if player.position in {"K", "DST"}:
        std_pts = fantasy_points(proj, config.scoring)
    else:
        std_pts = fantasy_points(proj, STANDARD_SCORING)
    rec_bonus = float(proj.get("rec", 0))
    adp = player.adp if player.adp else 999
    team = player.team or ""
    bye = (
        player.bye_week
        or (team_byes or {}).get(team)
        or BYE_WEEKS.get(team)
    )

    tier = 5
    if adp <= 12:
        tier = 1
    elif adp <= 30:
        tier = 2
    elif adp <= 60:
        tier = 3
    elif adp <= 90:
        tier = 4

    # Raw stat lines the frontend needs to apply fully custom scoring.
    custom_keys = (
        "pass_yd", "pass_td", "pass_int", "pass_2pt",
        "rush_yd", "rush_td", "rush_2pt",
        "rec", "rec_yd", "rec_td", "rec_2pt",
        "sack_taken", "fumbles", "fumbles_total", "fum_ret_td",
    )
    stats = {
        key: round(float(proj.get(key, 0.0)), 1)
        for key in custom_keys
        if proj.get(key)
    }

    return {
        "id": player.key(),
        "name": player.name,
        "pos": player.position,
        "nflTeam": player.team or "FA",
        "adp": round(adp, 1),
        "stdPts": round(std_pts, 1),
        "recPts": round(rec_bonus, 1),
        "tier": tier,
        "byeWeek": bye,
        "age": player.age,
        "stats": stats,
    }


def _load_players(profile: str):
    paths = ensure_profile(profile)
    config = load_profile_config(paths)
    provider = build_provider(config.provider)
    players = provider.fetch_players()
    if not players:
        if not os.path.exists(paths.projections_path):
            save_players(sample_players(), paths.projections_path)
        provider = build_provider(config.provider)
        players = provider.fetch_players()
    return players, config


def _prune_tasks():
    """Remove finished tasks older than 10 minutes or trim when task count exceeds 50."""
    now = time.time()
    cutoff = now - 600
    expired = [
        tid for tid, task in _tasks.items()
        if task["status"] in ("done", "error") and task.get("created_at", now) < cutoff
    ]
    for tid in expired:
        _tasks.pop(tid, None)
    if len(_tasks) > 50:
        finished = [
            tid for tid, task in _tasks.items()
            if task["status"] in ("done", "error")
        ]
        for tid in finished[: len(_tasks) - 50]:
            _tasks.pop(tid, None)


def _run_task(task_id: str, fn, *args, **kwargs):
    """Run *fn* in a background thread, storing result in _tasks."""
    def _worker():
        try:
            result = fn(*args, **kwargs)
            with _task_lock:
                _tasks[task_id]["status"] = "done"
                _tasks[task_id]["result"] = result
        except Exception as exc:
            with _task_lock:
                _tasks[task_id]["status"] = "error"
                _tasks[task_id]["error"] = f"{exc}\n{traceback.format_exc()}"

    with _task_lock:
        _prune_tasks()
        _tasks[task_id] = {
            "status": "running",
            "result": None,
            "error": None,
            "created_at": time.time(),
        }
    threading.Thread(target=_worker, daemon=True).start()


def _pick_player_ids(picks) -> list[str]:
    ids: list[str] = []
    if not isinstance(picks, list):
        return ids
    for pick in picks:
        if isinstance(pick, str):
            ids.append(pick)
        elif isinstance(pick, dict):
            player_id = pick.get("playerId") or pick.get("player_id") or pick.get("id")
            if isinstance(player_id, str):
                ids.append(player_id)
    return ids


def _my_pick_ids(picks, draft_position: int) -> list[str]:
    ids: list[str] = []
    if not isinstance(picks, list):
        return ids
    for pick in picks:
        if not isinstance(pick, dict):
            continue
        player_id = pick.get("playerId") or pick.get("player_id") or pick.get("id")
        if not isinstance(player_id, str):
            continue
        try:
            team_num = int(pick.get("teamNum"))
        except (TypeError, ValueError):
            continue
        if team_num == draft_position:
            ids.append(player_id)
    return ids


def _free_agent_row(rec) -> dict:
    drop = rec.drop_player
    return {
        "id": rec.player.key(),
        "name": rec.player.name,
        "pos": rec.player.position,
        "nflTeam": rec.player.team or "FA",
        "adp": round(rec.player.adp, 1) if rec.player.adp else None,
        "byeWeek": rec.player.bye_week,
        "points": rec.points,
        "vor": rec.vor,
        "score": rec.score,
        "rosterGain": rec.roster_gain,
        "starterGain": rec.starter_gain,
        "benchGain": rec.bench_gain,
        "reason": rec.reason,
        "drop": ({
            "id": drop.key(),
            "name": drop.name,
            "pos": drop.position,
            "nflTeam": drop.team or "FA",
            "points": rec.drop_points,
        } if drop else None),
    }


class DraftAPIHandler(SimpleHTTPRequestHandler):
    """Serves static files from STATIC_DIR and handles /api/ routes."""

    def __init__(self, *args, profile: str = DEFAULT_PROFILE, **kwargs):
        self.profile = profile
        super().__init__(*args, directory=str(STATIC_DIR), **kwargs)

    # ── routing ───────────────────────────────────────────────────────────

    def do_GET(self):
        if self.path == "/api/players":
            self._handle_players()
        elif self.path == "/api/config":
            self._handle_config()
        elif self.path == "/api/state":
            self._handle_get_state()
        elif self.path == "/api/yahoo/status":
            self._handle_yahoo_status()
        elif self.path.startswith("/api/task/"):
            self._handle_task_status()
        else:
            super().do_GET()

    def do_POST(self):
        if self.path == "/api/state":
            self._handle_save_state()
        elif self.path == "/api/pull-free-data":
            self._handle_pull_free_data()
        elif self.path == "/api/collect-all":
            self._handle_collect_all()
        elif self.path == "/api/fetch":
            self._handle_fetch()
        elif self.path == "/api/auction":
            self._handle_auction()
        elif self.path == "/api/suggest":
            self._handle_suggest()
        elif self.path == "/api/free-agents":
            self._handle_free_agents()
        elif self.path == "/api/sync-league":
            self._handle_sync_league()
        elif self.path == "/api/import-espn":
            self._handle_import_espn()
        elif self.path == "/api/yahoo/connect":
            self._handle_yahoo_connect()
        elif self.path == "/api/yahoo/exchange":
            self._handle_yahoo_exchange()
        elif self.path == "/api/yahoo/import":
            self._handle_yahoo_import()
        elif self.path == "/api/save-draft":
            self._handle_save_draft()
        elif self.path == "/api/load-draft":
            self._handle_load_draft()
        elif self.path == "/api/export-log":
            self._handle_export_log()
        elif self.path == "/api/parse-draft-text":
            self._handle_parse_draft_text()
        else:
            self._send_json({"error": "not found"}, 404)

    # ── helpers ────────────────────────────────────────────────────────────
    # No CORS headers on purpose: the frontend is same-origin, and a wildcard
    # Access-Control-Allow-Origin would let any website the user has open
    # rewrite draft state or trigger data pulls on this local server.

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        if length:
            return json.loads(self.rfile.read(length))
        return {}

    @staticmethod
    def _picks_list(value) -> list:
        """Validate a picks payload: must be a list of player-key strings."""
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise ValueError("picks must be a list of player key strings")
        return value

    def _send_json(self, data, code=200):
        body = json.dumps(data).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # ── existing endpoints ────────────────────────────────────────────────

    def _handle_players(self):
        try:
            players, config = _load_players(self.profile)
            team_byes = _team_byes_from_players(players)
            js_players = [_player_to_js(p, config, team_byes) for p in players]
            self._send_json(js_players)
        except Exception as exc:
            self._send_json({"error": str(exc)}, 500)

    def _handle_config(self):
        try:
            paths = ensure_profile(self.profile)
            config = load_profile_config(paths)
            self._send_json({
                "teams": config.teams,
                "roster": config.roster,
                "scoring": config.scoring,
                "draft": config.draft,
            })
        except Exception as exc:
            self._send_json({"error": str(exc)}, 500)

    def _suggest_config(self, body: dict, config: LeagueConfig) -> LeagueConfig:
        """Build the effective LeagueConfig for a suggestion request.

        The league you create (server profile config) is the source of truth for
        scoring — including K/DST weights the browser never sees. The live UI may
        override teams / draft slot / roster slots / sim count per request, so
        the engine always reflects whatever league you are actually drafting.
        """
        league = body.get("league") or {}
        teams = int(league.get("numTeams") or config.teams)
        roster = dict(config.roster)
        slots = league.get("rosterSlots")
        if isinstance(slots, dict):
            roster.update({k: int(v) for k, v in slots.items() if v is not None})
        scoring = scoring_for_league(league, config.scoring)
        draft = dict(config.draft or {})
        if league.get("draftPosition"):
            draft["slot"] = max(1, min(int(league["draftPosition"]), teams))
        if league.get("sims"):
            draft["rollout_sims"] = max(1, int(league["sims"]))
        # Opponent ADP noise: the UI derives this from how many opponents are
        # autodrafting (more autodrafters -> they follow ADP -> less noise).
        if league.get("adpNoise") is not None:
            draft["adp_noise"] = max(0.0, float(league["adpNoise"]))
        # Common-random-numbers keeps impact stable at modest sim counts, so the
        # web default favors responsiveness; bump via league.sims for precision.
        draft.setdefault("rollout_sims", 24)
        return LeagueConfig(
            teams=teams, roster=roster, scoring=scoring,
            provider=config.provider, draft=draft,
        )

    def _handle_suggest(self):
        """Rank the board by the rest-of-draft season-points rollout engine.

        Body: {picks: [key...], my_picks: [key...], top: int, league: {...}}.
        Player ids are ``Player.key()`` ("name|POS"), matching /api/players, so
        the frontend can merge the returned impact scores straight onto its board.
        """
        try:
            body = self._read_body()
            picks = self._picks_list(body.get("picks", []))
            my_picks = self._picks_list(body.get("my_picks", []))
            top_n = max(1, int(body.get("top", 50)))
            players, config = _load_players(self.profile)
            eff = self._suggest_config(body, config)

            by_key = {p.key(): p for p in players}
            picked = set(picks)
            available = [p for k, p in by_key.items() if k not in picked]
            my_roster: dict = {}
            for k in my_picks:
                p = by_key.get(k)
                if p:
                    my_roster.setdefault(p.position, []).append(p)
            state = DraftState(
                my_team_name="Me",
                league_teams=[f"T{i + 1}" for i in range(eff.teams)],
                picks=picks,
                my_picks=my_picks,
            )

            results = rollout_values(eff, available, my_roster, state, top_n=top_n)
            rows = [{
                "id": r.player.key(),
                "name": r.player.name,
                "pos": r.player.position,
                "nflTeam": r.player.team or "FA",
                "adp": round(r.player.adp, 1) if r.player.adp else None,
                "byeWeek": r.player.bye_week,
                "points": r.points,
                "vor": r.vor,
                "immediateGain": r.immediate_gain,
                "projRoster": r.expected_roster_points,
                "impact": r.impact,
                "goneRisk": r.gone_risk,
                "byePenalty": r.bye_penalty,
            } for r in results]
            self._send_json({
                "suggestions": rows,
                "sims": results[0].sims if results else 0,
                "teams": eff.teams,
                "slot": int((eff.draft or {}).get("slot", 1)),
            })
        except ValueError as exc:
            self._send_json({"error": str(exc)}, 400)
        except Exception as exc:
            self._send_json({"error": str(exc)}, 500)

    def _handle_free_agents(self):
        """Scan all configured leagues and rank available waiver/free-agent adds.

        Body: {leagues: [{...}], picks: {leagueId: [{playerId, teamNum}...]}, top: int}.
        The browser owns the saved league list, while Python owns player data,
        scoring, and roster optimization.
        """
        try:
            body = self._read_body()
            leagues = body.get("leagues") or []
            if not isinstance(leagues, list):
                self._send_json({"error": "leagues must be a list"}, 400)
                return
            picks_by_league = body.get("picks") or {}
            if not isinstance(picks_by_league, dict):
                picks_by_league = {}
            top_n = max(1, min(int(body.get("top", 8)), 30))

            players, config = _load_players(self.profile)
            by_key = {p.key(): p for p in players}
            response_rows = []

            for index, league in enumerate(leagues):
                if not isinstance(league, dict):
                    continue
                league_id = str(league.get("id") or f"league-{index + 1}")
                league_picks = picks_by_league.get(league_id, [])
                draft_position = int(league.get("draftPosition") or 1)
                picked_keys = _pick_player_ids(league_picks)
                my_keys = _my_pick_ids(league_picks, draft_position)

                eff = self._suggest_config({"league": league}, config)
                available = [p for key, p in by_key.items() if key not in picked_keys]
                my_roster: dict = {}
                for key in my_keys:
                    player = by_key.get(key)
                    if player:
                        my_roster.setdefault(player.position, []).append(player)

                recs = free_agent_recommendations(eff, available, my_roster, top_n=top_n)
                response_rows.append({
                    "id": league_id,
                    "name": league.get("name") or f"League {index + 1}",
                    "platform": league.get("platform") or "",
                    "rostered": len(my_keys),
                    "available": len(available),
                    "recommendations": [_free_agent_row(rec) for rec in recs],
                })

            self._send_json({
                "scannedLeagues": len(response_rows),
                "leagues": response_rows,
            })
        except ValueError as exc:
            self._send_json({"error": str(exc)}, 400)
        except Exception as exc:
            self._send_json({"error": str(exc)}, 500)

    def _handle_sync_league(self):
        """Sync provider rosters into local synthetic picks for one web league."""
        try:
            body = self._read_body()
            league = body.get("league") or {}
            if not isinstance(league, dict):
                self._send_json({"error": "league must be an object"}, 400)
                return

            platform = str(league.get("platform") or "").lower()
            players, _config = _load_players(self.profile)

            if platform == "yahoo" or league.get("yahooLeagueKey"):
                league_key = str(league.get("yahooLeagueKey") or body.get("leagueKey") or "").strip()
                if not league_key:
                    self._send_json({"error": "Yahoo league is missing yahooLeagueKey"}, 400)
                    return
                from ..importers import yahoo
                rosters = yahoo.fetch_league_rosters(self._yahoo_access_token(), league_key)
                source = "Yahoo"
            elif platform == "espn" or league.get("espnLeagueId"):
                league_id = str(league.get("espnLeagueId") or body.get("leagueId") or "").strip()
                if not league_id:
                    self._send_json({"error": "ESPN league is missing espnLeagueId"}, 400)
                    return
                from ..importers.free_sources import default_projection_season, fetch_espn_rosters
                season = int(league.get("season") or body.get("season") or 0) or default_projection_season()
                rosters = fetch_espn_rosters(
                    season,
                    league_id,
                    espn_s2=body.get("espnS2") or league.get("espnS2"),
                    swid=body.get("swid") or league.get("swid"),
                )
                source = "ESPN"
            else:
                self._send_json({"error": "Sync supports imported ESPN or Yahoo leagues"}, 400)
                return

            result = synced_rosters_to_picks(rosters, players, league)
            result.update({
                "ok": True,
                "source": source,
                "leagueId": league.get("id"),
                "leagueName": league.get("name"),
                "rostered": sum(team["players"] for team in result["teams"]),
            })
            self._send_json(result)
        except Exception as exc:
            self._send_json({"error": str(exc)}, 500)

    def _handle_import_espn(self):
        """Read a public ESPN league's settings to auto-fill a league in the UI.

        Body: {leagueId, season?}. Returns name / numTeams / rosterSlots /
        scoringType / teamNames / espnLeagueId for the LeagueSetup form.
        """
        try:
            body = self._read_body()
            league_id = str(body.get("leagueId") or "").strip()
            if not league_id:
                self._send_json({"error": "leagueId required"}, 400)
                return
            from ..importers.free_sources import default_projection_season, fetch_espn_league
            season = int(body.get("season") or 0) or default_projection_season()
            info = fetch_espn_league(season, league_id)
            rec = float((info.get("scoring") or {}).get("rec", 0) or 0)
            info["scoringType"] = "ppr" if rec >= 0.9 else "half-ppr" if rec >= 0.4 else "standard"
            info["espnLeagueId"] = league_id
            info["season"] = season
            self._send_json(info)
        except Exception as exc:
            self._send_json({"error": f"Could not import league {league_id!r}: {exc}"}, 500)

    # ── Yahoo OAuth import ────────────────────────────────────────────────
    # Credentials + tokens are stored in the profile dir (local machine only).

    def _yahoo_store_path(self) -> str:
        paths = ensure_profile(self.profile)
        return os.path.join(os.path.dirname(str(paths.state_path)), "yahoo.json")

    def _yahoo_load(self) -> dict:
        path = self._yahoo_store_path()
        if os.path.exists(path):
            try:
                with open(path) as fh:
                    return json.load(fh)
            except (OSError, json.JSONDecodeError):
                return {}
        return {}

    def _yahoo_save(self, data: dict) -> None:
        from ..storage import atomic_write_json
        atomic_write_json(self._yahoo_store_path(), data)

    def _yahoo_access_token(self) -> str:
        from ..importers import yahoo
        data = self._yahoo_load()
        token = data.get("token") or {}
        if not token.get("access_token"):
            raise RuntimeError("Authorize with Yahoo first")
        if yahoo.token_is_expired(token):
            token = yahoo.refresh_access_token(
                data["client_id"],
                data["client_secret"],
                token["refresh_token"],
                data.get("redirect_uri", yahoo.DEFAULT_REDIRECT),
            )
            data["token"] = token
            self._yahoo_save(data)
        return token["access_token"]

    def _handle_yahoo_status(self):
        """Report whether Yahoo credentials/token are already saved locally."""
        try:
            data = self._yahoo_load()
            self._send_json({
                "hasCredentials": bool(data.get("client_id") and data.get("client_secret")),
                "hasToken": bool((data.get("token") or {}).get("access_token")),
                "redirectUri": data.get("redirect_uri") or "https://localhost/",
            })
        except Exception as exc:
            self._send_json({"error": str(exc)}, 500)

    def _handle_yahoo_connect(self):
        """Store/confirm Yahoo app credentials locally and return the authorize URL.

        Falls back to already-saved credentials when the body omits them, so a
        re-authorize doesn't require re-typing the Client ID/Secret.
        """
        try:
            from ..importers import yahoo
            body = self._read_body()
            data = self._yahoo_load()
            client_id = str(body.get("clientId") or data.get("client_id") or "").strip()
            client_secret = str(body.get("clientSecret") or data.get("client_secret") or "").strip()
            redirect = str(body.get("redirectUri") or data.get("redirect_uri") or yahoo.DEFAULT_REDIRECT).strip()
            if not client_id or not client_secret:
                self._send_json({"error": "clientId and clientSecret are required"}, 400)
                return
            data.update({"client_id": client_id, "client_secret": client_secret,
                         "redirect_uri": redirect})
            self._yahoo_save(data)
            self._send_json({"authUrl": yahoo.auth_url(client_id, redirect)})
        except Exception as exc:
            self._send_json({"error": str(exc)}, 500)

    def _handle_yahoo_exchange(self):
        """Exchange the pasted authorization code for tokens; list NFL leagues."""
        try:
            from ..importers import yahoo
            body = self._read_body()
            code = str(body.get("code") or "").strip()
            data = self._yahoo_load()
            if not data.get("client_id"):
                self._send_json({"error": "Enter your Yahoo credentials first"}, 400)
                return
            if not code:
                self._send_json({"error": "Paste the authorization code"}, 400)
                return
            token = yahoo.exchange_code(data["client_id"], data["client_secret"], code,
                                        data.get("redirect_uri", yahoo.DEFAULT_REDIRECT))
            data["token"] = token
            self._yahoo_save(data)
            self._send_json({"ok": True, "leagues": yahoo.list_leagues(token["access_token"])})
        except Exception as exc:
            self._send_json({"error": str(exc)}, 500)

    def _handle_yahoo_import(self):
        """Import a chosen Yahoo league as a form-ready payload (like ESPN)."""
        try:
            from ..importers import yahoo
            body = self._read_body()
            league_key = str(body.get("leagueKey") or "").strip()
            if not league_key:
                self._send_json({"error": "leagueKey required"}, 400)
                return
            data = self._yahoo_load()
            if not (data.get("token") or {}).get("access_token"):
                self._send_json({"error": "Authorize with Yahoo first"}, 400)
                return
            info = yahoo.fetch_league(self._yahoo_access_token(), league_key)
            rec = float((info.get("scoring") or {}).get("rec", 0) or 0)
            info["scoringType"] = "ppr" if rec >= 0.9 else "half-ppr" if rec >= 0.4 else "standard"
            self._send_json(info)
        except Exception as exc:
            self._send_json({"error": str(exc)}, 500)

    def _get_draft_state(self) -> dict:
        paths = ensure_profile(self.profile)
        state = load_state(paths.state_path)
        return {
            "picks": state.picks,
            "my_picks": state.my_picks,
            "my_team_name": state.my_team_name,
            "league_teams": state.league_teams,
        }

    def _save_draft_state(self) -> dict:
        body = self._read_body()
        paths = ensure_profile(self.profile)
        state = load_state(paths.state_path)
        if "picks" in body:
            state.picks = self._picks_list(body["picks"])
        if "my_picks" in body:
            state.my_picks = self._picks_list(body["my_picks"])
        save_state(state, paths.state_path)
        return {"ok": True, "path": str(paths.state_path)}

    def _handle_get_state(self):
        try:
            self._send_json(self._get_draft_state())
        except Exception as exc:
            self._send_json({"error": str(exc)}, 500)

    def _handle_save_state(self):
        try:
            self._save_draft_state()
            self._send_json({"ok": True})
        except ValueError as exc:
            self._send_json({"error": str(exc)}, 400)
        except Exception as exc:
            self._send_json({"error": str(exc)}, 500)

    # ── background task polling ───────────────────────────────────────────

    def _handle_task_status(self):
        task_id = self.path.split("/api/task/")[-1]
        with _task_lock:
            task = _tasks.get(task_id)
        if not task:
            self._send_json({"error": "unknown task"}, 404)
            return
        self._send_json({
            "status": task["status"],
            "result": task["result"],
            "error": task["error"],
        })

    # ── pull-free-data (async) ────────────────────────────────────────────

    def _handle_pull_free_data(self):
        try:
            body = self._read_body()
            profile = self.profile
            task_id = f"pull-free-data-{threading.get_ident()}-{id(body)}"

            def _do_pull():
                from ..importers.free_sources import pull_free_data as _pull
                from ..importers.free_sources import merge_historical_into
                paths = ensure_profile(profile)
                config = load_profile_config(paths)
                result = _pull(
                    config=config,
                    season=body.get("season"),
                    stats_season=body.get("statsSeason"),
                    teams=body.get("teams"),
                    adp_format=body.get("adpFormat"),
                    include_fftoday=not body.get("skipFftoday", False),
                    espn_league_id=body.get("espnLeagueId"),
                    history_seasons=body.get("history"),
                )
                # Accumulate history across pulls: keep prior seasons on disk
                # rather than overwriting them with this pull's seasons only.
                players = merge_historical_into(result.players, load_players(paths.projections_path))
                save_players(players, paths.projections_path)
                seasons = sorted({s for p in players for s in p.historical_stats})
                reports = [
                    {"source": r.source, "records": r.records, "ok": r.ok, "detail": r.detail}
                    for r in result.reports
                ]
                return {"players": len(players), "reports": reports,
                        "historySeasons": seasons,
                        "consensusPlayers": result.consensus_players,
                        "warnings": list(result.warnings)}

            _run_task(task_id, _do_pull)
            self._send_json({"taskId": task_id})
        except Exception as exc:
            self._send_json({"error": str(exc)}, 500)

    # ── collect-all (async, optional dependency) ──────────────────────────

    def _handle_collect_all(self):
        try:
            body = self._read_body()
            profile = self.profile
            task_id = f"collect-all-{threading.get_ident()}-{id(body)}"

            def _do_collect():
                from ..collectors.combined import collect_all
                paths = ensure_profile(profile)
                players = collect_all(
                    current_season=body.get("season", 2026),
                    history_seasons=body.get("history", 3),
                    scoring_format=body.get("scoring", "ppr"),
                    teams=body.get("teams", 12),
                    skip_sleeper=body.get("skipSleeper", False),
                    skip_adp=body.get("skipAdp", False),
                )
                save_players(players, paths.projections_path)
                return {"players": len(players)}

            _run_task(task_id, _do_collect)
            self._send_json({"taskId": task_id})
        except Exception as exc:
            self._send_json({"error": str(exc)}, 500)

    # ── fetch (sync, fast) ────────────────────────────────────────────────

    def _handle_fetch(self):
        try:
            paths = ensure_profile(self.profile)
            config = load_profile_config(paths)
            provider = build_provider(config.provider)
            players = provider.fetch_players()
            save_players(players, paths.projections_path)
            self._send_json({"ok": True, "players": len(players)})
        except Exception as exc:
            self._send_json({"error": str(exc)}, 500)

    # ── auction values ────────────────────────────────────────────────────

    def _handle_auction(self):
        try:
            body = self._read_body()
            budget = body.get("budget", 200)
            top_n = body.get("top", 50)
            paths = ensure_profile(self.profile)
            config = load_profile_config(paths)
            provider = build_provider(config.provider)
            players = provider.fetch_players()
            from ..auction import compute_dollar_values
            values = compute_dollar_values(config, players, budget_per_team=budget)
            sorted_vals = sorted(values.items(), key=lambda x: x[1], reverse=True)
            player_map = {p.key(): p for p in players}
            rows = []
            for key, val in sorted_vals[:top_n]:
                p = player_map.get(key)
                if p:
                    rows.append({
                        "name": p.name, "pos": p.position,
                        "team": p.team or "FA", "value": round(val, 1),
                    })
            self._send_json({"budget": budget, "teams": config.teams, "values": rows})
        except Exception as exc:
            self._send_json({"error": str(exc)}, 500)

    # ── save/load draft state ─────────────────────────────────────────────

    def _handle_save_draft(self):
        try:
            res = self._save_draft_state()
            self._send_json(res)
        except ValueError as exc:
            self._send_json({"error": str(exc)}, 400)
        except Exception as exc:
            self._send_json({"error": str(exc)}, 500)

    def _handle_load_draft(self):
        self._handle_get_state()

    # ── export draft log ──────────────────────────────────────────────────

    def _handle_export_log(self):
        try:
            body = self._read_body()
            pick_list = body.get("picks", [])
            num_teams = body.get("numTeams", 12)
            players_map = body.get("playersMap", {})
            import csv
            import io
            buf = io.StringIO()
            w = csv.writer(buf)
            w.writerow(["pick", "round", "pick_in_round", "team", "player", "position"])
            for i, pk in enumerate(pick_list):
                pick_num = i + 1
                rd = (pick_num - 1) // num_teams + 1
                pick_in_rd = (pick_num - 1) % num_teams + 1
                pid = pk.get("playerId", "")
                p = players_map.get(pid, {})
                w.writerow([pick_num, rd, pick_in_rd, pk.get("teamNum", ""),
                            p.get("name", pid), p.get("pos", "")])
            csv_str = buf.getvalue()
            body_bytes = csv_str.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/csv")
            self.send_header("Content-Disposition", 'attachment; filename="draft_log.csv"')
            self.send_header("Content-Length", str(len(body_bytes)))
            self.end_headers()
            self.wfile.write(body_bytes)
        except Exception as exc:
            self._send_json({"error": str(exc)}, 500)

    # ── parse draft room text (paste modal) ────────────────────────────────

    def _handle_parse_draft_text(self):
        try:
            body = self._read_body()
            raw_text = str(body.get("text") or "").strip()
            num_teams = int(body.get("numTeams") or 12)
            start_pick = int(body.get("startPick") or 1)

            players_in_body = body.get("players")
            if isinstance(players_in_body, list) and len(players_in_body) > 0:
                available_players = players_in_body
            else:
                loaded, _ = _load_players(self.profile)
                available_players = [{
                    "id": p.key(),
                    "name": p.name,
                    "pos": p.position,
                    "team": p.team or "",
                } for p in loaded]

            from ..draft_paste_parser import parse_draft_text
            parsed_items = parse_draft_text(
                raw_text=raw_text,
                all_players=available_players,
                num_teams=num_teams,
                start_pick=start_pick,
            )
            self._send_json({"items": parsed_items, "totalParsed": len(parsed_items)})
        except Exception as exc:
            self._send_json({"error": str(exc)}, 500)

    def log_message(self, format, *args):
        pass


def run_server(
    port: int = 8080,
    profile: str = DEFAULT_PROFILE,
    open_browser: bool = True,
) -> None:
    handler = partial(DraftAPIHandler, profile=profile)
    # Threaded: the rollout endpoint can take a couple seconds, and a
    # single-threaded server would freeze every other request (player data,
    # state saves, the next pick) while it runs.
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    url = f"http://127.0.0.1:{port}"
    print(f"Draft Assistant web UI: {url}")
    print("Press Ctrl+C to stop.")
    if open_browser:
        threading.Timer(0.5, webbrowser.open, args=[url]).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        server.shutdown()
