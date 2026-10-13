"""Validate that a projection JSON file is safe to bundle for a live draft."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from draft_assistant.data_quality import evaluate_projection_quality
from draft_assistant.storage import load_players


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", nargs="?", default="data/projections.json")
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()

    path = Path(args.path)
    try:
        players = load_players(str(path))
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        print(f"Projection quality check failed: {exc}", file=sys.stderr)
        return 1

    report = evaluate_projection_quality(players)
    if args.as_json:
        print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
    else:
        status = "PASS" if report.ok else "FAIL"
        # "with byes" alone read as healthy on a board whose every bye was
        # being ignored; the verified count is the one the engine uses.
        verified = (f"{report.with_verified_bye} verified for {report.bye_season}"
                    if report.bye_season is not None else "0 verified, none stamped")
        print(
            f"Projection quality: {status} — {report.total} players, "
            f"{report.projected} projected, {report.with_adp} with ADP, "
            f"{report.with_bye} with byes ({verified}), "
            f"{report.with_history} with history, {report.consensus} consensus"
        )
        for issue in report.issues:
            print(f"- {issue}")
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
