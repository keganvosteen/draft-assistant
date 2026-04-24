"""Interactive terminal UI for the draft assistant."""
from __future__ import annotations

import os
import sys
from typing import Dict, List, Optional, Tuple

try:
    import readline  # noqa: F401  # Optional: command history on Unix-like shells.
except ImportError:  # pragma: no cover - Windows has no stdlib readline.
    readline = None

from .config import DEFAULT_CONFIG
from .draft import DraftTracker
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
from .storage import load_state, save_state, save_players
from .suggest import needs_by_position, suggest_players

POSITIONS = ["QB", "RB", "WR", "TE", "FLEX", "K", "DST", "BN"]
SCORING_PRESETS = {
    "ppr": {"rec": 1.0},
    "half": {"rec": 0.5},
    "standard": {"rec": 0.0},
}

CLEAR = "\033[2J\033[H"
BOLD = "\033[1m"
DIM = "\033[2m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
CYAN = "\033[36m"
RED = "\033[31m"
RESET = "\033[0m"


def _clear():
    sys.stdout.write(CLEAR)
    sys.stdout.flush()


def _header(title: str):
    width = 60
    print(f"\n{BOLD}{CYAN}{'=' * width}{RESET}")
    print(f"{BOLD}{CYAN}{title:^{width}}{RESET}")
    print(f"{BOLD}{CYAN}{'=' * width}{RESET}\n")


def _prompt(msg: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    val = input(f"  {msg}{suffix}: ").strip()
    return val if val else default


def _prompt_int(msg: str, default: int) -> int:
    raw = _prompt(msg, str(default))
    try:
        return int(raw)
    except ValueError:
        return default


def _prompt_float(msg: str, default: float) -> float:
    raw = _prompt(msg, str(default))
    try:
        return float(raw)
    except ValueError:
        return default


# ── Setup Wizard ──────────────────────────────────────────────


def _setup_wizard(paths: ProfilePaths) -> Tuple[LeagueConfig, DraftState]:
    """Interactive league setup. Returns (config, state)."""
    _clear()
    _header(f"FANTASY DRAFT ASSISTANT — LEAGUE SETUP [{paths.profile}]")

    teams = _prompt_int("Number of teams", 12)
    my_pick = _prompt_int("Your draft position (1-based)", 1)
    team_name = _prompt("Your team name", "My Team")

    # Scoring format
    print(f"\n  {BOLD}Scoring format:{RESET}")
    print("    1) PPR (1 pt per reception)")
    print("    2) Half PPR (0.5 pt)")
    print("    3) Standard (0 pt)")
    print("    4) Custom")
    fmt = _prompt("Choice", "1")

    scoring = dict(DEFAULT_CONFIG["scoring"])
    if fmt == "2":
        scoring["rec"] = 0.5
    elif fmt == "3":
        scoring["rec"] = 0.0
    elif fmt == "4":
        print(f"\n  {DIM}Enter scoring overrides (blank to keep default).{RESET}")
        for key in ["pass_yd", "pass_td", "pass_int", "rush_yd", "rush_td",
                     "rec", "rec_yd", "rec_td", "fumbles"]:
            scoring[key] = _prompt_float(f"  {key}", scoring.get(key, 0.0))

    # Roster slots
    print(f"\n  {BOLD}Roster slots:{RESET}")
    roster = dict(DEFAULT_CONFIG["roster"])
    for pos in POSITIONS:
        roster[pos] = _prompt_int(f"  {pos}", roster.get(pos, 0))

    provider = {
        "type": "local_json",
        "options": {"path": paths.projections_path},
    }

    draft_cfg = dict(DEFAULT_CONFIG["draft"])
    draft_cfg["slot"] = my_pick
    config = LeagueConfig(teams=teams, roster=roster, scoring=scoring, provider=provider, draft=draft_cfg)
    save_profile_config(config, paths)

    league_teams = [f"Team {i + 1}" for i in range(teams)]
    if 1 <= my_pick <= teams:
        league_teams[my_pick - 1] = team_name

    state = DraftState(
        my_team_name=team_name,
        league_teams=league_teams,
    )
    save_state(state, paths.state_path)

    # Data source
    data_path = paths.projections_path
    print(f"\n  {BOLD}Player data source:{RESET}")
    print("    1) Sample data (built-in, works offline)")
    print("    2) Collect real data (nflverse + Sleeper + ADP)")
    print(f"    3) Keep existing data{' (' + data_path + ')' if os.path.exists(data_path) else ''}")
    data_choice = _prompt("Choice", "1" if not os.path.exists(data_path) else "3")

    if data_choice == "2":
        season = _prompt_int("Season year", 2026)
        scoring_fmt = "ppr" if scoring.get("rec", 0) >= 1.0 else "half-ppr" if scoring.get("rec", 0) >= 0.5 else "standard"
        print(f"\n  {CYAN}Collecting data (this may take a minute)...{RESET}")
        try:
            from .collectors.combined import collect_all
            players = collect_all(
                current_season=season,
                history_seasons=3,
                scoring_format=scoring_fmt,
                teams=teams,
            )
            if players:
                save_players(players, data_path)
                print(f"\n  {GREEN}Saved {len(players)} players to {data_path}{RESET}")
            else:
                print(f"\n  {YELLOW}Collection returned no data. Falling back to sample data.{RESET}")
                from .sample_data import sample_players
                save_players(sample_players(), data_path)
        except Exception as e:
            print(f"\n  {RED}Collection failed: {e}{RESET}")
            print(f"  {YELLOW}Falling back to sample data.{RESET}")
            from .sample_data import sample_players
            save_players(sample_players(), data_path)
    elif data_choice == "1" or not os.path.exists(data_path):
        from .sample_data import sample_players
        save_players(sample_players(), data_path)
        print(f"\n  {GREEN}Seeded sample projections at {data_path}{RESET}")

    print(f"\n  {GREEN}League saved! {teams} teams, pick #{my_pick}, {_scoring_label(scoring)}{RESET}")
    input(f"\n  {DIM}Press Enter to start drafting…{RESET}")
    return config, state


def _scoring_label(scoring: dict) -> str:
    rec = scoring.get("rec", 0.0)
    if rec >= 1.0:
        return "PPR"
    elif rec >= 0.5:
        return "Half PPR"
    return "Standard"


# ── Draft Board ───────────────────────────────────────────────


def _show_board(tracker: DraftTracker, config: LeagueConfig, state: DraftState):
    """Show the live draft board: suggestions, roster, and needs."""
    _clear()
    avail = tracker.available_players()
    roster = tracker.my_roster()
    needs = needs_by_position(config, roster)
    total_picks = len(state.picks)

    ranked = suggest_players(config, avail, roster, top_n=10, total_picks=total_picks, draft_state=state)

    # Compact header
    rd = total_picks // config.teams + 1
    pick_in_rd = total_picks % config.teams + 1
    print(f"{BOLD}  Round {rd}, Pick {pick_in_rd}{RESET}  |  "
          f"{total_picks} picks made  |  "
          f"{len(avail)} available\n")

    # Two-column layout: suggestions on left, roster on right
    # Suggestions
    print(f"  {BOLD}{CYAN}TOP RECOMMENDATIONS{RESET}")
    print(f"  {'#':>2}  {'Player':<25} {'Pos':4} {'Pts':>6} {'VOR':>6} {'Score':>6}  {'Info'}")
    print(f"  {DIM}{'─' * 75}{RESET}")
    for i, (p, pts, vor, score) in enumerate(ranked, 1):
        extras = []
        if p.age is not None:
            extras.append(f"Age:{p.age}")
        conf = confidence_score(p)
        if conf != 0.5:
            extras.append(f"Conf:{conf:.0%}")
        if p.bye_week:
            extras.append(f"Bye:{p.bye_week}")
        info = " ".join(extras)

        need_flag = ""
        need = needs.get(p.position, 0)
        flex = needs.get("FLEX", 0) if p.position in {"RB", "WR", "TE"} else 0
        if need > 0:
            need_flag = f" {GREEN}NEED{RESET}"
        elif flex > 0:
            need_flag = f" {YELLOW}FLEX{RESET}"

        print(f"  {i:>2}. {p.name:<25} {p.position:4} {pts:>6.1f} {vor:>6.1f} {score:>6.1f}  {DIM}{info}{RESET}{need_flag}")

    # Roster
    print(f"\n  {BOLD}{CYAN}MY ROSTER{RESET}")
    total_filled = 0
    for pos in ["QB", "RB", "WR", "TE", "K", "DST"]:
        players_at = roster.get(pos, [])
        names = ", ".join(p.name for p in players_at) if players_at else f"{DIM}—{RESET}"
        slot_count = config.roster.get(pos, 0)
        filled = len(players_at)
        total_filled += filled
        status = f"{GREEN}{filled}/{slot_count}{RESET}" if filled >= slot_count else f"{YELLOW}{filled}/{slot_count}{RESET}"
        print(f"    {pos:4} [{status}]  {names}")

    # FLEX
    flex_target = config.roster.get("FLEX", 0)
    flex_open = needs.get("FLEX", 0)
    flex_filled = flex_target - flex_open
    flex_status = f"{GREEN}{flex_filled}/{flex_target}{RESET}" if flex_open == 0 else f"{YELLOW}{flex_filled}/{flex_target}{RESET}"
    print(f"    {'FLEX':4} [{flex_status}]  {DIM}(RB/WR/TE overflow){RESET}")

    # Needs summary line
    need_strs = [f"{pos}:{n}" for pos, n in needs.items() if n > 0 and pos != "FLEX"]
    if needs.get("FLEX", 0) > 0:
        need_strs.append(f"FLEX:{needs['FLEX']}")
    if need_strs:
        print(f"\n  {BOLD}Needs:{RESET} {', '.join(need_strs)}")
    else:
        print(f"\n  {GREEN}{BOLD}All starter slots filled!{RESET}")


def _show_log(tracker: DraftTracker, config: LeagueConfig):
    """Show draft log."""
    log = tracker.draft_log()
    if not log:
        print(f"\n  {DIM}No picks yet.{RESET}")
        return
    print(f"\n  {BOLD}{CYAN}DRAFT LOG{RESET}")
    for pick_num, key, is_mine in log:
        rd = (pick_num - 1) // config.teams + 1
        pick_in_rd = (pick_num - 1) % config.teams + 1
        p = tracker.players.get(key)
        name = p.name if p else key
        pos = p.position if p else "?"
        mine_flag = f" {GREEN}*{RESET}" if is_mine else ""
        print(f"    Rd {rd} Pick {pick_in_rd}: {name} ({pos}){mine_flag}")


def _show_auction(config: LeagueConfig, players: List[Player], budget: int = 200):
    from .auction import compute_dollar_values
    values = compute_dollar_values(config, players, budget_per_team=budget)
    sorted_vals = sorted(values.items(), key=lambda x: x[1], reverse=True)
    player_map = {p.key(): p for p in players}
    print(f"\n  {BOLD}{CYAN}AUCTION VALUES (${budget}/team){RESET}")
    for key, val in sorted_vals[:15]:
        p = player_map.get(key)
        if p:
            print(f"    ${val:6.1f}  {p.name} ({p.position})")


def _show_help():
    print(f"""
  {BOLD}{CYAN}COMMANDS{RESET}
    {BOLD}pick <name>{RESET}       Record someone else's pick
    {BOLD}my <name>{RESET}         Record YOUR pick
    {BOLD}pick <name> -p RB{RESET} Specify position for ambiguous names
    {BOLD}undo{RESET}              Undo last pick
    {BOLD}undo <N>{RESET}          Undo last N picks
    {BOLD}board{RESET}             Refresh the board
    {BOLD}log{RESET}               Show full draft log
    {BOLD}roster{RESET}            Show your roster details
    {BOLD}auction{RESET}           Show auction dollar values
    {BOLD}save{RESET}              Save draft state
    {BOLD}help{RESET}              Show this help
    {BOLD}quit{RESET}              Save and exit
""")


# ── Main Loop ─────────────────────────────────────────────────


def run_interactive(profile: str = DEFAULT_PROFILE):
    """Single entry point: setup (if needed) then live draft loop."""

    paths = ensure_profile(profile)

    # Load or create config
    config_exists = os.path.exists(paths.config_path)
    data_exists = os.path.exists(paths.projections_path)
    if config_exists and data_exists:
        print(f"\n  Found existing config for profile '{paths.profile}'.")
        choice = _prompt("Start new league setup or continue? (new/continue)", "continue")
        if choice.lower().startswith("n"):
            config, state = _setup_wizard(paths)
        else:
            config = load_profile_config(paths)
            state = load_state(paths.state_path)
    else:
        config, state = _setup_wizard(paths)

    # Load players
    provider = build_provider(config.provider)
    players = provider.fetch_players()
    if not players:
        from .sample_data import sample_players
        players = sample_players()
        save_players(players, paths.projections_path)
        print(f"  {GREEN}Loaded {len(players)} sample players.{RESET}")

    tracker = DraftTracker(config, state, players)

    # Show initial board
    _show_board(tracker, config, state)
    _show_help()

    # Enable readline tab completion for player names
    available_names = [p.name for p in players]

    def _completer(text, state_idx):
        prefix = text.lower()
        matches = [n for n in available_names if n.lower().startswith(prefix)]
        if state_idx < len(matches):
            return matches[state_idx]
        return None

    readline.set_completer(_completer)
    readline.parse_and_bind("tab: complete")
    readline.set_completer_delims("")

    while True:
        try:
            raw = input(f"\n  {BOLD}>{RESET} ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not raw:
            continue

        parts = raw.split(maxsplit=1)
        cmd = parts[0].lower()
        arg = parts[1] if len(parts) > 1 else ""

        if cmd in ("quit", "exit", "q"):
            save_state(state, paths.state_path)
            print(f"  {GREEN}Draft saved. Goodbye!{RESET}")
            break

        elif cmd == "help":
            _show_help()

        elif cmd == "board":
            _show_board(tracker, config, state)

        elif cmd == "pick":
            if not arg:
                print(f"  {RED}Usage: pick <player name>{RESET}")
                continue
            pos_filter = None
            if " -p " in arg:
                arg, pos_filter = arg.rsplit(" -p ", 1)
                pos_filter = pos_filter.strip().upper()
            picked = tracker.record_pick(arg, position=pos_filter, my_pick=False)
            if picked:
                save_state(state, paths.state_path)
                print(f"  {DIM}Picked: {picked.name} ({picked.position}){RESET}")
                _show_board(tracker, config, state)
            else:
                print(f"  {RED}No match found for '{arg}'. Try a different name.{RESET}")

        elif cmd in ("my", "mypick"):
            if not arg:
                print(f"  {RED}Usage: my <player name>{RESET}")
                continue
            pos_filter = None
            if " -p " in arg:
                arg, pos_filter = arg.rsplit(" -p ", 1)
                pos_filter = pos_filter.strip().upper()
            picked = tracker.record_pick(arg, position=pos_filter, my_pick=True)
            if picked:
                save_state(state, paths.state_path)
                print(f"  {GREEN}Your pick: {picked.name} ({picked.position}){RESET}")
                _show_board(tracker, config, state)
            else:
                print(f"  {RED}No match found for '{arg}'. Try a different name.{RESET}")

        elif cmd == "undo":
            steps = 1
            if arg:
                try:
                    steps = int(arg)
                except ValueError:
                    pass
            undone = tracker.undo(steps)
            if undone:
                save_state(state, paths.state_path)
                for key in undone:
                    print(f"  {YELLOW}Undid: {key}{RESET}")
                _show_board(tracker, config, state)
            else:
                print(f"  {DIM}Nothing to undo.{RESET}")

        elif cmd == "log":
            _show_log(tracker, config)

        elif cmd == "roster":
            _show_board(tracker, config, state)

        elif cmd == "auction":
            budget = 200
            if arg:
                try:
                    budget = int(arg)
                except ValueError:
                    pass
            _show_auction(config, tracker.available_players(), budget)

        elif cmd == "save":
            save_state(state, paths.state_path)
            print(f"  {GREEN}Draft state saved.{RESET}")

        else:
            print(f"  {RED}Unknown command: '{cmd}'. Type 'help' for commands.{RESET}")
