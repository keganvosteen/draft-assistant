from __future__ import annotations

import json
import mimetypes
import os
import threading
import webbrowser
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, urlparse

from .config import DEFAULT_CONFIG
from .draft import DraftTracker
from .draft_value import DraftValue, draft_aware_values, draft_window
from .historical import confidence_score
from .models import DraftState, LeagueConfig, Player
from .profiles import (
    DEFAULT_PROFILE,
    ProfilePaths,
    ensure_profile,
    list_profiles,
    load_profile_config,
    save_profile_config,
)
from .providers.base import build_provider
from .projections import compute_points, replacement_levels
from .sample_data import sample_players
from .storage import load_state, save_players, save_state
from .suggest import _bye_week_penalty, _position_need_multiplier, needs_by_position


STATIC_DIR = Path(__file__).with_name("web_static")
DEFAULT_SCORE_LIMIT = 20
WEB_CANDIDATE_POOL = 80
WEB_MONTE_CARLO_SIMS = 120


def run_web_ui(
    profile: str = DEFAULT_PROFILE,
    host: str = "127.0.0.1",
    port: int = 8765,
    open_browser: bool = True,
) -> None:
    """Run the local browser UI backed by the Python draft engine."""
    handler = _handler_factory(profile)
    server = ThreadingHTTPServer((host, port), handler)
    url = f"http://{host}:{server.server_port}/?profile={profile}"
    print(f"Draft Assistant web UI: {url}")
    print("Press Ctrl+C to stop.")
    if open_browser:
        threading.Timer(0.35, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping web UI.")
    finally:
        server.server_close()


def _handler_factory(default_profile: str):
    class DraftAssistantHandler(BaseHTTPRequestHandler):
        server_version = "DraftAssistantWeb/1.0"

        def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
            parsed = urlparse(self.path)
            if parsed.path == "/":
                self._serve_static("index.html")
                return
            if parsed.path == "/favicon.ico":
                self.send_response(204)
                self.end_headers()
                return
            if parsed.path.startswith("/static/"):
                self._serve_static(parsed.path.removeprefix("/static/"))
                return
            if parsed.path == "/api/profiles":
                self._send_json({"profiles": list_profiles(), "defaultProfile": default_profile})
                return
            if parsed.path == "/api/state":
                params = parse_qs(parsed.query)
                profile = params.get("profile", [default_profile])[0]
                self._send_json(build_snapshot(profile))
                return
            self.send_error(404, "Not found")

        def do_POST(self) -> None:  # noqa: N802 - stdlib handler API
            parsed = urlparse(self.path)
            try:
                payload = self._read_json()
                profile = str(payload.get("profile") or default_profile)
                if parsed.path == "/api/pick":
                    self._send_json(record_pick(profile, payload))
                    return
                if parsed.path == "/api/undo":
                    self._send_json(undo_pick(profile, int(payload.get("steps") or 1)))
                    return
                if parsed.path == "/api/reset":
                    self._send_json(reset_draft(profile))
                    return
                if parsed.path == "/api/config":
                    self._send_json(update_config(profile, payload.get("config") or {}))
                    return
                self.send_error(404, "Not found")
            except ValueError as exc:
                self._send_json({"ok": False, "error": str(exc)}, status=400)
            except Exception as exc:  # pragma: no cover - defensive API boundary
                self._send_json({"ok": False, "error": str(exc)}, status=500)

        def log_message(self, fmt: str, *args: object) -> None:
            print(f"[web] {self.address_string()} - {fmt % args}")

        def _serve_static(self, relative_path: str) -> None:
            target = (STATIC_DIR / relative_path).resolve()
            static_root = STATIC_DIR.resolve()
            if not str(target).startswith(str(static_root)) or not target.is_file():
                self.send_error(404, "Static file not found")
                return
            content_type = mimetypes.guess_type(os.fspath(target))[0] or "application/octet-stream"
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            with open(target, "rb") as f:
                self.wfile.write(f.read())

        def _read_json(self) -> Dict[str, Any]:
            length = int(self.headers.get("Content-Length", "0") or 0)
            raw = self.rfile.read(length).decode("utf-8") if length else "{}"
            try:
                data = json.loads(raw or "{}")
            except json.JSONDecodeError as exc:
                raise ValueError("Invalid JSON request body.") from exc
            if not isinstance(data, dict):
                raise ValueError("Request body must be a JSON object.")
            return data

        def _send_json(self, data: Dict[str, Any], status: int = 200) -> None:
            body = json.dumps(data, ensure_ascii=True).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return DraftAssistantHandler


def build_snapshot(profile: str = DEFAULT_PROFILE) -> Dict[str, Any]:
    paths, config, state, players = _load_context(profile)
    tracker = DraftTracker(config, state, players)
    available = tracker.available_players()
    my_roster = tracker.my_roster()
    points_map = compute_points(players, config.scoring)
    repl = replacement_levels(available, config.scoring, config.teams, config.roster)
    scored = _scored_recommendations(config, available, my_roster, state)
    scored_map = {item["key"]: item for item in scored}
    pick_index = {key: i + 1 for i, key in enumerate(state.picks)}
    my_pick_set = set(state.my_picks)

    serialized_players = []
    for player in players:
        key = player.key()
        pts = round(points_map.get(key, 0.0), 2)
        vor = round(pts - repl.get(player.position, 0.0), 2)
        row = _serialize_player(player, pts, vor)
        row["drafted"] = key in pick_index
        row["myPick"] = key in my_pick_set
        row["pickNumber"] = pick_index.get(key)
        if key in scored_map:
            row.update(scored_map[key])
        serialized_players.append(row)

    serialized_players.sort(
        key=lambda p: (
            p.get("drafted", False),
            -(p.get("score") if p.get("score") is not None else -999999),
            p.get("adp") if p.get("adp") is not None else 9999,
            p.get("name", ""),
        )
    )

    return {
        "ok": True,
        "profile": paths.profile,
        "profiles": list_profiles(),
        "config": asdict(config),
        "state": _serialize_state(config, state),
        "players": serialized_players,
        "recommendations": scored[:12],
        "needs": needs_by_position(config, my_roster),
        "roster": _serialize_roster(my_roster, scored_map, points_map, repl),
        "draft": _draft_summary(config, state),
        "source": {
            "players": len(players),
            "available": len(available),
            "projectionsPath": paths.projections_path,
            "configPath": paths.config_path,
            "statePath": paths.state_path,
        },
    }


def record_pick(profile: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    paths, config, state, players = _load_context(profile)
    key = str(payload.get("key") or "")
    if not key:
        raise ValueError("Pick request requires a player key.")
    player_map = {player.key(): player for player in players}
    player = player_map.get(key)
    if player is None:
        raise ValueError("Player is not in the projection pool.")
    if key in state.picked_set():
        raise ValueError("Player has already been drafted.")

    mine = payload.get("mine")
    if mine is None:
        mine = _current_team(config, state) == _draft_slot(config)
    state.picks.append(key)
    if bool(mine):
        state.my_picks.append(key)
    save_state(state, paths.state_path)
    return build_snapshot(profile)


def undo_pick(profile: str, steps: int = 1) -> Dict[str, Any]:
    paths, config, state, players = _load_context(profile)
    tracker = DraftTracker(config, state, players)
    tracker.undo(max(1, steps))
    save_state(state, paths.state_path)
    return build_snapshot(profile)


def reset_draft(profile: str) -> Dict[str, Any]:
    paths, config, state, _players = _load_context(profile)
    state.picks = []
    state.my_picks = []
    if len(state.league_teams) != config.teams:
        state.league_teams = [f"Team {i + 1}" for i in range(max(1, config.teams))]
    save_state(state, paths.state_path)
    return build_snapshot(profile)


def update_config(profile: str, raw_config: Dict[str, Any]) -> Dict[str, Any]:
    paths, config, state, _players = _load_context(profile)
    config.teams = _clamp_int(raw_config.get("teams", config.teams), 4, 20)
    config.roster = {
        "QB": _clamp_int((raw_config.get("roster") or {}).get("QB", config.roster.get("QB", 1)), 0, 5),
        "RB": _clamp_int((raw_config.get("roster") or {}).get("RB", config.roster.get("RB", 2)), 0, 8),
        "WR": _clamp_int((raw_config.get("roster") or {}).get("WR", config.roster.get("WR", 2)), 0, 8),
        "TE": _clamp_int((raw_config.get("roster") or {}).get("TE", config.roster.get("TE", 1)), 0, 5),
        "FLEX": _clamp_int((raw_config.get("roster") or {}).get("FLEX", config.roster.get("FLEX", 1)), 0, 5),
        "K": _clamp_int((raw_config.get("roster") or {}).get("K", config.roster.get("K", 0)), 0, 3),
        "DST": _clamp_int((raw_config.get("roster") or {}).get("DST", config.roster.get("DST", 0)), 0, 3),
        "BN": _clamp_int((raw_config.get("roster") or {}).get("BN", config.roster.get("BN", 6)), 0, 15),
    }
    scoring = raw_config.get("scoring")
    if isinstance(scoring, dict) and scoring:
        config.scoring = {str(k): float(v) for k, v in scoring.items()}
    draft = dict(config.draft or {})
    raw_draft = raw_config.get("draft") or {}
    draft["slot"] = _clamp_int(raw_draft.get("slot", draft.get("slot", 1)), 1, config.teams)
    draft["monte_carlo_sims"] = _clamp_int(
        raw_draft.get("monte_carlo_sims", draft.get("monte_carlo_sims", 250)),
        0,
        1000,
    )
    draft["adp_noise"] = float(raw_draft.get("adp_noise", draft.get("adp_noise", 8.0)))
    draft["candidate_pool"] = _clamp_int(
        raw_draft.get("candidate_pool", draft.get("candidate_pool", 120)),
        40,
        500,
    )
    config.draft = draft
    provider = config.provider or {}
    if not provider:
        config.provider = {"type": "local_json", "options": {"path": paths.projections_path}}
    save_profile_config(config, paths)
    if len(state.league_teams) != config.teams:
        state.league_teams = [f"Team {i + 1}" for i in range(config.teams)]
        save_state(state, paths.state_path)
    return build_snapshot(profile)


def _load_context(profile: str) -> tuple[ProfilePaths, LeagueConfig, DraftState, List[Player]]:
    paths = ensure_profile(profile)
    config = load_profile_config(paths)
    state = load_state(paths.state_path)
    provider = build_provider(config.provider)
    players = provider.fetch_players()
    if not players:
        players = sample_players()
        save_players(players, paths.projections_path)
    return paths, config, state, players


def _scored_recommendations(
    config: LeagueConfig,
    available: List[Player],
    my_roster: Dict[str, List[Player]],
    state: DraftState,
    limit: int = DEFAULT_SCORE_LIMIT,
) -> List[Dict[str, Any]]:
    needs = needs_by_position(config, my_roster)
    total_roster_spots = sum(int(v) for v in config.roster.values())
    scoring_config = _web_scoring_config(config)
    base_values = draft_aware_values(
        config=scoring_config,
        available=available,
        my_roster=my_roster,
        state=state,
        top_n=limit,
    )
    total_picks = len(state.picks)
    rows: List[Dict[str, Any]] = []
    for item in base_values:
        player = item.player
        need_mult = _position_need_multiplier(
            player.position,
            needs,
            config,
            my_roster,
            total_picks,
            total_roster_spots,
        )
        extra_bye = _bye_week_penalty(player, my_roster)
        final_score = round(item.score * need_mult - extra_bye, 2)
        row = _serialize_draft_value(item, final_score, need_mult, extra_bye)
        row["reason"] = _reason_label(row, needs)
        rows.append(row)
    rows.sort(key=lambda row: (row["score"], row["vor"], row["points"]), reverse=True)
    return rows


def _web_scoring_config(config: LeagueConfig) -> LeagueConfig:
    draft = dict(config.draft or {})
    draft["monte_carlo_sims"] = min(
        int(draft.get("monte_carlo_sims", WEB_MONTE_CARLO_SIMS) or WEB_MONTE_CARLO_SIMS),
        WEB_MONTE_CARLO_SIMS,
    )
    draft["candidate_pool"] = min(
        int(draft.get("candidate_pool", WEB_CANDIDATE_POOL) or WEB_CANDIDATE_POOL),
        WEB_CANDIDATE_POOL,
    )
    return LeagueConfig(
        teams=config.teams,
        roster=dict(config.roster),
        scoring=dict(config.scoring),
        provider=dict(config.provider),
        draft=draft,
    )


def _serialize_player(player: Player, points: float, vor: float) -> Dict[str, Any]:
    metadata = player.metadata if isinstance(player.metadata, dict) else {}
    age = player.age if player.age is not None else metadata.get("age")
    experience = player.experience if player.experience is not None else metadata.get("years_exp")
    return {
        "key": player.key(),
        "id": player.id,
        "name": player.name,
        "position": player.position,
        "team": player.team or "",
        "byeWeek": player.bye_week,
        "adp": player.adp,
        "points": points,
        "vor": vor,
        "age": age,
        "experience": experience,
        "injuryCount": len(player.injury_history),
        "confidence": round(confidence_score(player), 2),
        "metadata": {
            "status": metadata.get("status"),
            "sources": metadata.get("sources", []),
            "adpStdev": metadata.get("adp_stdev"),
        },
    }


def _serialize_draft_value(
    item: DraftValue,
    final_score: float,
    need_mult: float,
    extra_bye: float,
) -> Dict[str, Any]:
    player = item.player
    return {
        "key": player.key(),
        "id": player.id,
        "name": player.name,
        "position": player.position,
        "team": player.team or "",
        "byeWeek": player.bye_week,
        "adp": player.adp,
        "points": round(item.points, 2),
        "vor": round(item.vor, 2),
        "score": final_score,
        "baseScore": round(item.score, 2),
        "lineupGain": round(item.lineup_gain, 2),
        "scarcity": round(item.scarcity, 2),
        "nextPickValue": round(item.next_pick_value, 2),
        "needMultiplier": round(need_mult, 2),
        "byePenalty": round(item.bye_penalty + extra_bye, 2),
        "slotType": _slot_type(player.position, need_mult),
    }


def _serialize_roster(
    roster: Dict[str, List[Player]],
    scored_map: Dict[str, Dict[str, Any]],
    points_map: Dict[str, float],
    repl: Dict[str, float],
) -> Dict[str, List[Dict[str, Any]]]:
    out: Dict[str, List[Dict[str, Any]]] = {}
    for pos, players in roster.items():
        out[pos] = []
        for player in players:
            key = player.key()
            pts = round(points_map.get(key, 0.0), 2)
            row = _serialize_player(player, pts, round(pts - repl.get(pos, 0.0), 2))
            if key in scored_map:
                row.update(scored_map[key])
            out[pos].append(row)
    return out


def _serialize_state(config: LeagueConfig, state: DraftState) -> Dict[str, Any]:
    teams = max(1, int(config.teams))
    return {
        "myTeamName": state.my_team_name,
        "leagueTeams": state.league_teams,
        "picks": list(state.picks),
        "myPicks": list(state.my_picks),
        "pickCount": len(state.picks),
        "round": (len(state.picks) // teams) + 1,
        "pickInRound": (len(state.picks) % teams) + 1,
    }


def _draft_summary(config: LeagueConfig, state: DraftState) -> Dict[str, Any]:
    window = draft_window(config, state)
    current_team = _current_team(config, state)
    slot = _draft_slot(config)
    return {
        "slot": slot,
        "currentPick": len(state.picks) + 1,
        "currentTeam": current_team,
        "isMyPick": current_team == slot,
        "nextMyPick": window.next_my_pick,
        "followingMyPick": window.following_my_pick,
        "picksUntilNext": window.picks_until_next,
    }


def _current_team(config: LeagueConfig, state: DraftState) -> int:
    teams = max(1, int(config.teams))
    pick_num = len(state.picks) + 1
    round_num = ((pick_num - 1) // teams) + 1
    pick_in_round = ((pick_num - 1) % teams) + 1
    if round_num % 2 == 1:
        return pick_in_round
    return teams - pick_in_round + 1


def _draft_slot(config: LeagueConfig) -> int:
    teams = max(1, int(config.teams))
    return min(max(int((config.draft or {}).get("slot", 1)), 1), teams)


def _slot_type(position: str, need_mult: float) -> str:
    if need_mult >= 1.0:
        return "starter" if position not in {"RB", "WR", "TE"} else "starter/flex"
    if need_mult >= 0.75:
        return "bench"
    return "depth"


def _reason_label(row: Dict[str, Any], needs: Dict[str, int]) -> str:
    pos = row["position"]
    if needs.get(pos, 0) > 0:
        return f"Fills {pos}"
    if pos in {"RB", "WR", "TE"} and needs.get("FLEX", 0) > 0:
        return "Fills FLEX"
    if row.get("scarcity", 0) >= 8:
        return "Scarcity"
    if row.get("nextPickValue", 0) >= 8:
        return "Wait-aware"
    return "Best value"


def _clamp_int(value: Any, low: int, high: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = low
    return min(max(parsed, low), high)
