"""Run a draft strategy benchmark from the command line."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from draft_assistant.config import load_config
from draft_assistant.strategy_sim import load_benchmark_players, run_benchmark


def _rank_label(rank: int) -> str:
    if rank == 1:
        return "1st (WIN)"
    if rank == 2:
        return "2nd"
    if rank == 3:
        return "3rd"
    return f"{rank}th"


def main() -> None:
    parser = argparse.ArgumentParser(description="Run draft simulation benchmark.")
    parser.add_argument("--config", default="league.config.yaml", help="Path to league config")
    parser.add_argument("--players", default="data/projections.json", help="Path to projections JSON")
    parser.add_argument("--sims", type=int, default=24, help="Simulations per pick in rollout engine")
    parser.add_argument("--slot", type=int, default=None, help="Run only one draft slot with verbose logs")
    parser.add_argument("--noise", type=float, default=0.0, help="Std dev of Gaussian ADP noise on each opponent's board")
    parser.add_argument("--trials", type=int, default=1, help="Drafts per slot (use >1 with --noise)")
    args = parser.parse_args()

    if sys.stdout.encoding != "utf-8":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    config = load_config(args.config)
    players = load_benchmark_players(args.players)
    print("\n=======================================================")
    print(f" DRAFT SIMULATION BENCHMARK ({config.teams} Teams)")
    print(f" Config: {args.config}")
    print(f" Players: {len(players)} total | Sims/pick: {args.sims} | Noise: {args.noise} | Trials/slot: {args.trials}")
    print("=======================================================\n")

    rows = run_benchmark(
        config,
        players,
        sims_per_pick=args.sims,
        slot_filter=args.slot,
        adp_noise=args.noise,
        trials=args.trials,
        log=lambda message: print(message, flush=True),
    )
    wins = 0
    for row in rows:
        if row["rank"] == 1:
            wins += 1
        print(
            " Done! "
            f"Slot: {row['slot']}.{row['trial']} | "
            f"User Pts: {row['user_score']:.1f} | "
            f"Avg Opp: {row['avg_opp']:.1f} | "
            f"Best Opp: {row['max_opp']:.1f} | "
            f"Rank: {_rank_label(row['rank'])} "
            f"(Diff vs Best: {row['diff_max']:+.1f})",
            flush=True,
        )

    win_rate = (wins / len(rows)) * 100.0 if rows else 0.0
    print("\n-------------------------------------------------------")
    print(f" SUMMARY: User Engine won {wins}/{len(rows)} drafts ({win_rate:.1f}% Win Rate)")
    print("-------------------------------------------------------\n")


if __name__ == "__main__":
    main()
