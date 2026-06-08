"""Lightweight HTTP server for the Draft Assistant web UI.

Serves static files from ./static/ and exposes a thin JSON API so the
React frontend can load player data from the Python backend.
"""
from __future__ import annotations

import json
import os
import threading
import traceback
import webbrowser
from functools import partial
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from typing import Optional

from ..models import LeagueConfig
from ..profiles import DEFAULT_PROFILE, ensure_profile, load_profile_config
from ..providers.base import build_provider
from ..sample_data import sample_players
from ..scoring import fantasy_points
from ..storage import load_state, save_players, save_state

STATIC_DIR = Path(__file__).parent / "static"

STANDARD_SCORING = {
    "pass_yd": 0.04, "pass_td": 4, "pass_int": -2,
    "rush_yd": 0.1, "rush_td": 6,
    "rec_yd": 0.1, "rec_td": 6,
    "fumbles": -2,
}

BYE_WEEKS = {
    "ARI": 13, "ATL": 12, "BAL": 8, "BUF": 6, "CAR": 6, "CHI": 14,
    "CIN": 8, "CLE": 14, "DAL": 10, "DEN": 11, "DET": 5, "GB": 13,
    "HOU": 11, "IND": 11, "JAX": 11, "KC": 6, "LAC": 10, "LAR": 5,
    "LV": 12, "MIA": 9, "MIN": 13, "NE": 14, "NO": 12, "NYG": 11,
    "NYJ": 7, "PHI": 7, "PIT": 14, "SEA": 14, "SF": 10, "TB": 9,
    "TEN": 9, "WAS": 14,
}

# Tracks background tasks (pull-free-data, collect-all, etc.)
_tasks: dict[str, dict] = {}
_task_lock = threading.Lock()


def _player_to_js(player, config: LeagueConfig) -> dict:
    """Convert a Python Player to the JS frontend's expected format."""
    std_pts = fantasy_points(player.projections, STANDARD_SCORING)
    rec_bonus = float(player.projections.get("rec", 0)) * 0.5
    adp = player.adp if player.adp else 999
    bye = player.bye_week or BYE_WEEKS.get(player.team or "", None)

    tier = 5
    if adp <= 12:
        tier = 1
    elif adp <= 30:
        tier = 2
    elif adp <= 60:
        tier = 3
    elif adp <= 90:
        tier = 4

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
        _tasks[task_id] = {"status": "running", "result": None, "error": None}
    threading.Thread(target=_worker, daemon=True).start()


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
        elif self.path == "/api/save-draft":
            self._handle_save_draft()
        elif self.path == "/api/load-draft":
            self._handle_load_draft()
        elif self.path == "/api/export-log":
            self._handle_export_log()
        else:
            self._send_json({"error": "not found"}, 404)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    # ── helpers ────────────────────────────────────────────────────────────

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        if length:
            return json.loads(self.rfile.read(length))
        return {}

    def _send_json(self, data, code=200):
        body = json.dumps(data).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    # ── existing endpoints ────────────────────────────────────────────────

    def _handle_players(self):
        try:
            players, config = _load_players(self.profile)
            js_players = [_player_to_js(p, config) for p in players]
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

    def _handle_get_state(self):
        try:
            paths = ensure_profile(self.profile)
            state = load_state(paths.state_path)
            self._send_json({
                "picks": state.picks,
                "my_picks": state.my_picks,
                "my_team_name": state.my_team_name,
                "league_teams": state.league_teams,
            })
        except Exception as exc:
            self._send_json({"error": str(exc)}, 500)

    def _handle_save_state(self):
        try:
            body = self._read_body()
            paths = ensure_profile(self.profile)
            state = load_state(paths.state_path)
            if "picks" in body:
                state.picks = body["picks"]
            if "my_picks" in body:
                state.my_picks = body["my_picks"]
            save_state(state, paths.state_path)
            self._send_json({"ok": True})
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
                )
                save_players(result.players, paths.projections_path)
                reports = [
                    {"source": r.source, "records": r.records, "ok": r.ok, "detail": r.detail}
                    for r in result.reports
                ]
                return {"players": len(result.players), "reports": reports}

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
            body = self._read_body()
            paths = ensure_profile(self.profile)
            state = load_state(paths.state_path)
            if "picks" in body:
                state.picks = body["picks"]
            if "my_picks" in body:
                state.my_picks = body["my_picks"]
            save_state(state, paths.state_path)
            self._send_json({"ok": True, "path": str(paths.state_path)})
        except Exception as exc:
            self._send_json({"error": str(exc)}, 500)

    def _handle_load_draft(self):
        try:
            paths = ensure_profile(self.profile)
            state = load_state(paths.state_path)
            self._send_json({
                "picks": state.picks,
                "my_picks": state.my_picks,
                "my_team_name": state.my_team_name,
                "league_teams": state.league_teams,
            })
        except Exception as exc:
            self._send_json({"error": str(exc)}, 500)

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

    def log_message(self, format, *args):
        pass


def run_server(
    port: int = 8080,
    profile: str = DEFAULT_PROFILE,
    open_browser: bool = True,
) -> None:
    handler = partial(DraftAPIHandler, profile=profile)
    server = HTTPServer(("127.0.0.1", port), handler)
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
