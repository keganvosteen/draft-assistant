from __future__ import annotations
import argparse
import csv
import os
from typing import List

from .config import DEFAULT_CONFIG, load_config, save_config
from .models import DraftState
from .providers.base import build_provider
from .storage import load_state, save_state, save_players
from .draft import DraftTracker
from .suggest import suggest_players
from .historical import confidence_score
from .importers.fantasypros import load_offense_csv, load_k_csv, load_dst_csv, merge_players
from .importers.fftoday import fetch_all_fftoday
from .export import export_players_csv


def _cmd_draft() -> None:
    from .ui import run_interactive
    run_interactive()


def cmd_init(args: argparse.Namespace) -> None:
    if not os.path.exists("league.config.yaml"):
        save_config(load_config())
        print("Created league.config.yaml with defaults.")
    else:
        print("league.config.yaml already exists.")
    state = load_state()
    save_state(state)
    # Seed sample data if missing
    if not os.path.exists("data/projections.json"):
        from .sample_data import sample_players
        save_players(sample_players())
        print("Seeded sample projections at data/projections.json")
    print("Init complete.")


def _load_all() -> tuple:
    config = load_config()
    state = load_state()
    provider = build_provider(config.provider)
    players = provider.fetch_players()
    return config, state, players


def cmd_fetch(args: argparse.Namespace) -> None:
    config, state, players = _load_all()
    print(f"Loaded {len(players)} players from provider.")
    # Persist current snapshot
    save_players(players)
    print("Saved to data/projections.json")


def cmd_suggest(args: argparse.Namespace) -> None:
    config, state, players = _load_all()
    tracker = DraftTracker(config, state, players)
    avail = tracker.available_players()
    ranked = suggest_players(config, avail, tracker.my_roster(), top_n=args.top, total_picks=len(state.picks))
    print(f"Top {len(ranked)} suggestions:")
    for p, pts, vor, score in ranked:
        extras = []
        if p.adp:
            extras.append(f"ADP:{p.adp:.1f}")
        if p.age is not None:
            extras.append(f"Age:{p.age}")
        conf = confidence_score(p)
        if conf != 0.5:  # only show if we have meaningful data
            extras.append(f"Conf:{conf:.0%}")
        extra_str = " " + " ".join(extras) if extras else ""
        print(f"- {p.name} ({p.position}) Pts:{pts:.1f} VOR:{vor:.1f} Score:{score:.1f}{extra_str}")


def cmd_pick(args: argparse.Namespace, mine: bool) -> None:
    config, state, players = _load_all()
    tracker = DraftTracker(config, state, players)
    picked = tracker.record_pick(args.player, position=args.position, my_pick=mine)
    if not picked:
        print("No matching available player found.")
        return
    save_state(state)
    who = "Your pick" if mine else "Pick"
    print(f"{who}: {picked.name} ({picked.position})")


def cmd_undo(args: argparse.Namespace) -> None:
    config, state, players = _load_all()
    tracker = DraftTracker(config, state, players)
    steps = getattr(args, "steps", 1) or 1
    undone = tracker.undo(steps)
    if not undone:
        print("No picks to undo.")
        return
    save_state(state)
    for key in undone:
        print(f"Undid: {key}")
    print(f"({len(undone)} pick(s) undone)")


def cmd_roster(args: argparse.Namespace) -> None:
    config, state, players = _load_all()
    tracker = DraftTracker(config, state, players)
    roster = tracker.my_roster()
    print("My Roster:")
    for pos in ["QB", "RB", "WR", "TE", "K", "DST"]:
        lst = roster.get(pos, [])
        if lst:
            names = ", ".join(p.name for p in lst)
            print(f"- {pos}: {names}")
    # Needs
    from .suggest import needs_by_position
    needs = needs_by_position(config, roster)
    print("Needs:")
    for pos, n in needs.items():
        print(f"- {pos}: {n}")


def cmd_save(args: argparse.Namespace) -> None:
    state = load_state()
    save_state(state)
    print("State saved.")


def cmd_load(args: argparse.Namespace) -> None:
    state = load_state()
    print(f"Loaded state with {len(state.picks)} picks.")


def main() -> None:
    parser = argparse.ArgumentParser(prog="draft-assistant", description="Fantasy Football Draft Assistant")
    sub = parser.add_subparsers(dest="command")

    # Primary command: interactive draft UI
    p_draft = sub.add_parser("draft", help="Launch interactive draft UI (recommended)")
    p_draft.set_defaults(func=lambda a: _cmd_draft())

    p_init = sub.add_parser("init", help="Initialize config and sample data")
    p_init.set_defaults(func=cmd_init)

    p_fetch = sub.add_parser("fetch", help="Fetch/refresh player data")
    p_fetch.set_defaults(func=cmd_fetch)

    p_suggest = sub.add_parser("suggest", help="Show top suggestions")
    p_suggest.add_argument("-n", "--top", type=int, default=12)
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

    # Import FantasyPros CSVs
    def cmd_import_fpros(args: argparse.Namespace) -> None:
        offense_players = load_offense_csv(args.offense) if args.offense else []
        k_players = load_k_csv(args.k) if args.k else []
        dst_players = load_dst_csv(args.dst) if args.dst else []
        players = merge_players(offense_players, k_players, dst_players)
        if not players:
            print("No players imported. Check file paths and formats.")
            return
        out = args.out or "data/projections.json"
        save_players(players, out)
        print(f"Imported {len(players)} players to {out}")

    p_import = sub.add_parser("import-fpros", help="Import FantasyPros CSVs (offense/K/DST)")
    p_import.add_argument("--offense", type=str, help="Path to FantasyPros offense CSV")
    p_import.add_argument("--k", type=str, help="Path to FantasyPros kicker CSV")
    p_import.add_argument("--dst", type=str, help="Path to FantasyPros DST CSV")
    p_import.add_argument("--out", type=str, default="data/projections.json", help="Output JSON path")
    p_import.set_defaults(func=cmd_import_fpros)

    # Pull free FFToday projections (experimental)
    def cmd_pull_fftoday(args: argparse.Namespace) -> None:
        season = args.season
        print(f"Fetching FFToday projections for {season}…")
        players = fetch_all_fftoday(season)
        if not players:
            print("No players fetched. The site may have changed or blocked requests.")
            return
        out_json = args.out or "data/projections.json"
        save_players(players, out_json)
        print(f"Saved {len(players)} players to {out_json}")
        if args.csv:
            export_players_csv(players, args.csv)
            print(f"Also wrote CSV to {args.csv}")

    p_pull = sub.add_parser("pull-fftoday", help="Fetch free FFToday projections and save to JSON/CSV")
    p_pull.add_argument("--season", type=int, default=2024)
    p_pull.add_argument("--out", type=str, default="data/projections.json")
    p_pull.add_argument("--csv", type=str, default=None)
    p_pull.set_defaults(func=cmd_pull_fftoday)

    # Draft log
    def cmd_log(args: argparse.Namespace) -> None:
        config, state, players = _load_all()
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

    # Collect historical data from Sleeper
    def cmd_collect(args: argparse.Namespace) -> None:
        from .collectors.sleeper_historical import collect_players
        players = collect_players(
            current_season=args.season,
            history_seasons=args.history,
        )
        if not players:
            print("Collection failed or returned no players.")
            return
        out = args.out or "data/projections.json"
        save_players(players, out)
        print(f"Saved {len(players)} enriched players to {out}")

    p_collect = sub.add_parser("collect", help="Collect player data with historical stats from Sleeper API")
    p_collect.add_argument("--season", type=int, default=2025, help="Current/upcoming season year")
    p_collect.add_argument("--history", type=int, default=3, help="Number of prior seasons to collect")
    p_collect.add_argument("--out", type=str, default="data/projections.json")
    p_collect.set_defaults(func=cmd_collect)

    # Multi-source consensus
    def cmd_consensus(args: argparse.Namespace) -> None:
        from .consensus import build_consensus
        sources = args.sources
        if not sources or len(sources) < 2:
            print("Provide at least 2 source files: --sources file1.json file2.json ...")
            return
        build_consensus(sources, method=args.method, output_path=args.out)

    p_consensus = sub.add_parser("consensus", help="Merge multiple projection sources into consensus")
    p_consensus.add_argument("--sources", nargs="+", required=True, help="Paths to projection JSON files")
    p_consensus.add_argument("--method", choices=["median", "mean"], default="median")
    p_consensus.add_argument("--out", type=str, default="data/projections.json")
    p_consensus.set_defaults(func=cmd_consensus)

    # Auction dollar values
    def cmd_auction(args: argparse.Namespace) -> None:
        config, state, players = _load_all()
        from .auction import compute_dollar_values
        values = compute_dollar_values(config, players, budget_per_team=args.budget)
        # Sort by value descending
        sorted_vals = sorted(values.items(), key=lambda x: x[1], reverse=True)
        player_map = {p.key(): p for p in players}
        print(f"Auction values (${args.budget}/team, {config.teams} teams):")
        for key, val in sorted_vals[:args.top]:
            p = player_map.get(key)
            if p:
                print(f"  ${val:6.1f}  {p.name} ({p.position})")

    p_auction = sub.add_parser("auction", help="Show auction dollar values for players")
    p_auction.add_argument("--budget", type=int, default=200, help="Budget per team")
    p_auction.add_argument("-n", "--top", type=int, default=50, help="Show top N players")
    p_auction.set_defaults(func=cmd_auction)

    args = parser.parse_args()
    if hasattr(args, "func"):
        args.func(args)
    elif args.command is None:
        # No subcommand → launch interactive UI
        _cmd_draft()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
