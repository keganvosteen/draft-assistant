"""Lightweight HTTP server for the Draft Assistant web UI.

Serves static files from ./static/ and exposes a thin JSON API so the
React frontend can load player data from the Python backend.
"""
from __future__ import annotations

import json
import os
import threading
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


class DraftAPIHandler(SimpleHTTPRequestHandler):
    """Serves static files from STATIC_DIR and handles /api/ routes."""

    def __init__(self, *args, profile: str = DEFAULT_PROFILE, **kwargs):
        self.profile = profile
        super().__init__(*args, directory=str(STATIC_DIR), **kwargs)

    def do_GET(self):
        if self.path == "/api/players":
            self._handle_players()
        elif self.path == "/api/config":
            self._handle_config()
        elif self.path == "/api/state":
            self._handle_get_state()
        else:
            super().do_GET()

    def do_POST(self):
        if self.path == "/api/state":
            self._handle_save_state()
        else:
            self._send_json({"error": "not found"}, 404)

    def _send_json(self, data, code=200):
        body = json.dumps(data).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

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
            content_length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(content_length)) if content_length else {}
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
