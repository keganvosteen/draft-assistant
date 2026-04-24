from __future__ import annotations

import argparse
import os

from .draft import DraftTracker
from .export import export_players_csv
from .importers.fantasypros import load_dst_csv, load_k_csv, load_offense_csv, merge_players
from .importers.fftoday import fetch_all_fftoday
from .importers.free_sources import pull_free_data
from .profiles import DEFAULT_PROFILE, ensure_profile, load_profile_config
from .providers.base import build_provider
from .sample_data import sample_players
from .storage import load_state, save_players, save_state
from .suggest import suggest_players


def launch_desktop_ui(profile: str = DEFAULT_PROFILE) -> None:
    from .ui_desktop import run_ui

    run_ui(initial_profile=profile)


def launch_terminal_ui(profile: str = DEFAULT_PROFILE) -> None:
    from .ui import run_interactive

    run_interactive(profile=profile)


def cmd_init(args: argparse.Namespace) -> None:
    paths = ensure_profile(args.profile)
    config = load_profile_config(paths)
    provider = build_provider(config.provider)
    seeded = False

    # Seed sample data if missing or empty.
    if not os.path.exists(paths.projections_path) or not provider.fetch_players():
        save_players(sample_players(), paths.projections_path)
        seeded = True

    print(f"Initialized profile '{paths.profile}'.")
    print(f"Config: {paths.config_path}")
    print(f"State: {paths.state_path}")
    print(f"Projections: {paths.projections_path}")
    if seeded:
        print("Seeded sample projections.")
    print("Init complete.")


def _load_all(profile: str) -> tuple:
    paths = ensure_profile(profile)
    config = load_profile_config(paths)
    state = load_state(paths.state_path)
    provider = build_provider(config.provider)
    players = provider.fetch_players()
    return config, state, players, paths


def cmd_fetch(args: argparse.Namespace) -> None:
    config, state, players, paths = _load_all(args.profile)
    print(f"Loaded {len(players)} players from provider.")
    save_players(players, paths.projections_path)
    print(f"Saved to {paths.projections_path}")


def cmd_suggest(args: argparse.Namespace) -> None:
    config, state, players, _paths = _load_all(args.profile)
    if args.draft_slot is not None or args.sims is not None:
        draft_settings = dict(config.draft or {})
        if args.draft_slot is not None:
            draft_settings["slot"] = args.draft_slot
        if args.sims is not None:
            draft_settings["monte_carlo_sims"] = args.sims
        config.draft = draft_settings
    tracker = DraftTracker(config, state, players)
    avail = tracker.available_players()
    ranked = suggest_players(config, avail, tracker.my_roster(), top_n=args.top, draft_state=state)
    print(f"Top {len(ranked)} suggestions:")
    for p, pts, vor, score in ranked:
        adp = f" ADP:{p.adp:.1f}" if p.adp else ""
        print(f"- {p.name} ({p.position}) Score:{score:.1f} Pts:{pts:.1f} VOR:{vor:.1f}{adp}")


def cmd_pick(args: argparse.Namespace, mine: bool) -> None:
    config, state, players, paths = _load_all(args.profile)
    tracker = DraftTracker(config, state, players)
    picked = tracker.record_pick(args.player, position=args.position, my_pick=mine)
    if not picked:
        print("No matching available player found.")
        return
    save_state(state, paths.state_path)
    who = "Your pick" if mine else "Pick"
    print(f"{who}: {picked.name} ({picked.position})")


def cmd_undo(args: argparse.Namespace) -> None:
    config, state, players, paths = _load_all(args.profile)
    tracker = DraftTracker(config, state, players)
    steps = getattr(args, "steps", 1) or 1
    undone = tracker.undo(steps)
    if not undone:
        print("No picks to undo.")
        return
    save_state(state, paths.state_path)
    for key in undone:
        print(f"Undid: {key}")
    if len(undone) > 1:
        print(f"({len(undone)} pick(s) undone)")


def cmd_roster(args: argparse.Namespace) -> None:
    config, state, players, _paths = _load_all(args.profile)
    tracker = DraftTracker(config, state, players)
    roster = tracker.my_roster()
    print("My Roster:")
    for pos in ["QB", "RB", "WR", "TE", "K", "DST"]:
        lst = roster.get(pos, [])
        if lst:
            names = ", ".join(p.name for p in lst)
            print(f"- {pos}: {names}")
    from .suggest import needs_by_position

    needs = needs_by_position(config, roster)
    print("Needs:")
    for pos in ["QB", "RB", "WR", "TE", "FLEX", "K", "DST"]:
        print(f"- {pos}: {needs.get(pos, 0)}")


def cmd_save(args: argparse.Namespace) -> None:
    paths = ensure_profile(args.profile)
    state = load_state(paths.state_path)
    save_state(state, paths.state_path)
    print(f"State saved: {paths.state_path}")


def cmd_load(args: argparse.Namespace) -> None:
    paths = ensure_profile(args.profile)
    state = load_state(paths.state_path)
    print(f"Loaded state with {len(state.picks)} picks.")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="draft-assistant",
        description="Fantasy Football Draft Assistant (UI first, CLI commands available)",
    )
    parser.add_argument(
        "--profile",
        type=str,
        default=DEFAULT_PROFILE,
        help="League profile name (default: default)",
    )
    sub = parser.add_subparsers(dest="command")

    p_ui = sub.add_parser("ui", help="Launch desktop (Tkinter) UI")
    p_ui.set_defaults(func=lambda a: launch_desktop_ui(a.profile))

    p_draft = sub.add_parser("draft", help="Launch interactive terminal UI")
    p_draft.set_defaults(func=lambda a: launch_terminal_ui(a.profile))

    p_init = sub.add_parser("init", help="Initialize profile data")
    p_init.set_defaults(func=cmd_init)

    p_fetch = sub.add_parser("fetch", help="Fetch/refresh player data")
    p_fetch.set_defaults(func=cmd_fetch)

    p_suggest = sub.add_parser("suggest", help="Show top suggestions")
    p_suggest.add_argument("-n", "--top", type=int, default=12)
    p_suggest.add_argument("--draft-slot", type=int, default=None, help="Override snake draft slot for this run")
    p_suggest.add_argument("--sims", type=int, default=None, help="Override Monte Carlo simulation count for this run")
    p_suggest.set_defaults(func=cmd_suggest)

    p_pick = sub.add_parser("pick", help="Record a league pick")
    p_pick.add_argument("player", type=str)
    p_pick.add_argument("-p", "--position", type=str, default=None)
    p_pick.set_defaults(func=lambda a: cmd_pick(a, mine=False))

    p_mypick = sub.add_parser("mypick", help="Record your pick")
    p_mypick.add_argument("player", type=str)
    p_mypick.add_argument("-p", "--position", type=str, default=None)
    p_mypick.set_defaults(func=lambda a: cmd_pick(a, mine=True))

    p_undo = sub.add_parser("undo", help="Undo last pick(s)")
    p_undo.add_argument("-n", "--steps", type=int, default=1, help="Number of picks to undo")
    p_undo.set_defaults(func=cmd_undo)

    p_roster = sub.add_parser("roster", help="Show your roster and needs")
    p_roster.set_defaults(func=cmd_roster)

    p_save = sub.add_parser("save", help="Save draft state")
    p_save.set_defaults(func=cmd_save)

    p_load = sub.add_parser("load", help="Load draft state")
    p_load.set_defaults(func=cmd_load)

    def cmd_import_fpros(args: argparse.Namespace) -> None:
        paths = ensure_profile(args.profile)
        offense_players = load_offense_csv(args.offense) if args.offense else []
        k_players = load_k_csv(args.k) if args.k else []
        dst_players = load_dst_csv(args.dst) if args.dst else []
        players = merge_players(offense_players, k_players, dst_players)
        if not players:
            print("No players imported. Check file paths and formats.")
            return
        out = args.out or paths.projections_path
        save_players(players, out)
        print(f"Imported {len(players)} players to {out}")

    p_import = sub.add_parser("import-fpros", help="Import FantasyPros CSVs (offense/K/DST)")
    p_import.add_argument("--offense", type=str, help="Path to FantasyPros offense CSV")
    p_import.add_argument("--k", type=str, help="Path to FantasyPros kicker CSV")
    p_import.add_argument("--dst", type=str, help="Path to FantasyPros DST CSV")
    p_import.add_argument("--out", type=str, default=None, help="Output JSON path")
    p_import.set_defaults(func=cmd_import_fpros)

    def cmd_pull_fftoday(args: argparse.Namespace) -> None:
        paths = ensure_profile(args.profile)
        season = args.season
        print(f"Fetching FFToday projections for {season}...")
        players = fetch_all_fftoday(season)
        if not players:
            print("No players fetched. The site may have changed or blocked requests.")
            return
        out_json = args.out or paths.projections_path
        save_players(players, out_json)
        print(f"Saved {len(players)} players to {out_json}")
        if args.csv:
            export_players_csv(players, args.csv)
            print(f"Also wrote CSV to {args.csv}")

    p_pull = sub.add_parser("pull-fftoday", help="Fetch free FFToday projections and save to JSON/CSV")
    p_pull.add_argument("--season", type=int, default=2024)
    p_pull.add_argument("--out", type=str, default=None)
    p_pull.add_argument("--csv", type=str, default=None)
    p_pull.set_defaults(func=cmd_pull_fftoday)

    def cmd_pull_free_data(args: argparse.Namespace) -> None:
        paths = ensure_profile(args.profile)
        config = load_profile_config(paths)
        print("Pulling free data sources...")
        result = pull_free_data(
            config=config,
            season=args.season,
            stats_season=args.stats_season,
            teams=args.teams,
            adp_format=args.adp_format,
            include_fftoday=not args.skip_fftoday,
            espn_league_id=args.espn_league_id,
        )
        out_json = args.out or paths.projections_path
        save_players(result.players, out_json)
        print(f"Saved {len(result.players)} players to {out_json}")
        if args.csv:
            export_players_csv(result.players, args.csv)
            print(f"Also wrote CSV to {args.csv}")
        print("Source report:")
        for report in result.reports:
            status = "ok" if report.ok else "skipped/failed"
            detail = f" ({report.detail})" if report.detail else ""
            print(f"- {report.source}: {status}, {report.records} records{detail}")

    p_free = sub.add_parser("pull-free-data", help="Fetch and merge free public data sources")
    p_free.add_argument("--season", type=int, default=None, help="Projection season; defaults to current year")
    p_free.add_argument("--stats-season", type=int, default=None, help="Historical stats season; defaults to last year")
    p_free.add_argument("--teams", type=int, default=None, help="League team count for ADP")
    p_free.add_argument("--adp-format", choices=["standard", "half-ppr", "ppr"], default=None)
    p_free.add_argument("--espn-league-id", type=str, default=None, help="Optional public ESPN league id")
    p_free.add_argument("--skip-fftoday", action="store_true", help="Skip FFToday scraping")
    p_free.add_argument("--out", type=str, default=None)
    p_free.add_argument("--csv", type=str, default=None)
    p_free.set_defaults(func=cmd_pull_free_data)

    # log command
    def cmd_log(args: argparse.Namespace) -> None:
        import csv
        config, state, players, _paths = _load_all(args.profile)
        tracker = DraftTracker(config, state, players)
        log = tracker.draft_log()
        if not log:
            print("No picks recorded yet.")
            return
        teams = config.teams
        for pick_num, key, is_mine in log:
            rd = (pick_num - 1) // teams + 1
            pick_in_rd = (pick_num - 1) % teams + 1
            mine_flag = " *" if is_mine else ""
            p = tracker.players.get(key)
            name = p.name if p else key
            pos = p.position if p else "?"
            print(f"Rd {rd} Pick {pick_in_rd}: {name} ({pos}){mine_flag}")
        if args.csv:
            with open(args.csv, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(["pick", "round", "pick_in_round", "player", "position", "is_mine"])
                for pick_num, key, is_mine in log:
                    rd = (pick_num - 1) // teams + 1
                    pick_in_rd = (pick_num - 1) % teams + 1
                    p = tracker.players.get(key)
                    w.writerow([pick_num, rd, pick_in_rd, p.name if p else key, p.position if p else "", is_mine])
            print(f"Draft log exported to {args.csv}")

    p_log = sub.add_parser("log", help="Show draft pick log")
    p_log.add_argument("--csv", type=str, default=None, help="Export log to CSV")
    p_log.set_defaults(func=cmd_log)

    # collect (Sleeper API only)
    def cmd_collect(args: argparse.Namespace) -> None:
        paths = ensure_profile(args.profile)
        from .collectors.sleeper_historical import collect_players
        players = collect_players(
            current_season=args.season,
            history_seasons=args.history,
        )
        if not players:
            print("Collection failed or returned no players.")
            return
        out = args.out or paths.projections_path
        save_players(players, out)
        print(f"Saved {len(players)} enriched players to {out}")

    p_collect = sub.add_parser("collect", help="Collect Sleeper player data with historical stats")
    p_collect.add_argument("--season", type=int, default=2026)
    p_collect.add_argument("--history", type=int, default=3)
    p_collect.add_argument("--out", type=str, default=None)
    p_collect.set_defaults(func=cmd_collect)

    # collect-all (nflverse + Sleeper + FFC ADP)
    def cmd_collect_all(args: argparse.Namespace) -> None:
        paths = ensure_profile(args.profile)
        from .collectors.combined import collect_all
        players = collect_all(
            current_season=args.season,
            history_seasons=args.history,
            scoring_format=args.scoring,
            teams=args.teams,
            skip_sleeper=args.skip_sleeper,
            skip_adp=args.skip_adp,
        )
        if not players:
            print("Collection failed or returned no players.")
            return
        out = args.out or paths.projections_path
        save_players(players, out)
        print(f"\nSaved {len(players)} fully enriched players to {out}")

    p_ca = sub.add_parser("collect-all",
        help="Collect from all sources: nflverse + Sleeper + FFC ADP (requires nfl_data_py)")
    p_ca.add_argument("--season", type=int, default=2026)
    p_ca.add_argument("--history", type=int, default=3)
    p_ca.add_argument("--scoring", choices=["ppr", "half-ppr", "standard"], default="ppr")
    p_ca.add_argument("--teams", type=int, default=12)
    p_ca.add_argument("--out", type=str, default=None)
    p_ca.add_argument("--skip-sleeper", action="store_true")
    p_ca.add_argument("--skip-adp", action="store_true")
    p_ca.set_defaults(func=cmd_collect_all)

    # consensus (multi-source merge)
    def cmd_consensus(args: argparse.Namespace) -> None:
        paths = ensure_profile(args.profile)
        from .consensus import build_consensus
        out = args.out or paths.projections_path
        if not args.sources or len(args.sources) < 2:
            print("Provide at least 2 source files: --sources file1.json file2.json ...")
            return
        build_consensus(args.sources, method=args.method, output_path=out)

    p_consensus = sub.add_parser("consensus", help="Merge multiple projection sources")
    p_consensus.add_argument("--sources", nargs="+", required=True)
    p_consensus.add_argument("--method", choices=["median", "mean"], default="median")
    p_consensus.add_argument("--out", type=str, default=None)
    p_consensus.set_defaults(func=cmd_consensus)

    # auction
    def cmd_auction(args: argparse.Namespace) -> None:
        config, state, players, _paths = _load_all(args.profile)
        from .auction import compute_dollar_values
        values = compute_dollar_values(config, players, budget_per_team=args.budget)
        sorted_vals = sorted(values.items(), key=lambda x: x[1], reverse=True)
        player_map = {p.key(): p for p in players}
        print(f"Auction values (${args.budget}/team, {config.teams} teams):")
        for key, val in sorted_vals[:args.top]:
            p = player_map.get(key)
            if p:
                print(f"  ${val:6.1f}  {p.name} ({p.position})")

    p_auction = sub.add_parser("auction", help="Show auction dollar values")
    p_auction.add_argument("--budget", type=int, default=200)
    p_auction.add_argument("-n", "--top", type=int, default=50)
    p_auction.set_defaults(func=cmd_auction)

    args = parser.parse_args()
    if hasattr(args, "func"):
        args.func(args)
    else:
        # No subcommand: prefer terminal UI (always available); fall back to
        # desktop UI only if tkinter is present and terminal fails.
        try:
            launch_terminal_ui(args.profile)
        except Exception as exc:
            parser.print_help()
            print(f"\nUnable to launch terminal UI: {exc}")
            raise SystemExit(1)


if __name__ == "__main__":
    main()
