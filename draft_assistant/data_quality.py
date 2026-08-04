"""Quality checks for a production projection board.

The collectors intentionally tolerate partial upstream failures so a user can
still inspect what was returned.  Shipping that partial board as the default is
different: missing byes, history, provenance, or an entire scoring position can
silently invalidate recommendations.  This module provides the stricter gate
used by packaging and CI for the repository's bundled board.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Dict, Iterable, List

from .models import Player


MIN_POSITION_COUNTS = {
    "QB": 50,
    "RB": 100,
    "WR": 150,
    "TE": 50,
    "K": 20,
    "DST": 20,
}


@dataclass(frozen=True)
class ProjectionQualityReport:
    total: int
    position_counts: Dict[str, int]
    projected: int
    with_adp: int
    with_bye: int
    with_history: int
    with_metadata: int
    consensus: int
    kickers: int
    projected_kickers: int
    duplicate_ids: int
    issues: List[str]

    @property
    def ok(self) -> bool:
        return not self.issues

    def to_dict(self) -> dict:
        data = asdict(self)
        data["ok"] = self.ok
        return data


def evaluate_projection_quality(players: Iterable[Player]) -> ProjectionQualityReport:
    """Return a strict release-quality report for a bundled player board."""
    board = list(players)
    total = len(board)
    positions: Dict[str, int] = {}
    for player in board:
        positions[player.position] = positions.get(player.position, 0) + 1

    projected = sum(bool(player.projections) for player in board)
    with_adp = sum(player.adp is not None for player in board)
    with_bye = sum(player.bye_week is not None for player in board)
    with_history = sum(bool(player.historical_stats) for player in board)
    with_metadata = sum(bool(player.metadata) for player in board)
    consensus = sum(
        (player.metadata or {}).get("projection_source") == "consensus"
        for player in board
    )
    kickers = sum(player.position == "K" for player in board)
    projected_kickers = sum(
        player.position == "K" and bool(player.projections) for player in board
    )
    player_ids = [player.key() for player in board]
    duplicate_ids = len(player_ids) - len(set(player_ids))

    issues: List[str] = []
    if total < 500:
        issues.append(f"player pool is too small ({total}; expected at least 500)")
    if duplicate_ids:
        issues.append(f"player pool contains {duplicate_ids} duplicate stable ids")
    for position, minimum in MIN_POSITION_COUNTS.items():
        count = positions.get(position, 0)
        if count < minimum:
            issues.append(
                f"{position} pool is too small ({count}; expected at least {minimum})"
            )

    def require_ratio(label: str, count: int, minimum: float) -> None:
        ratio = (count / total) if total else 0.0
        if ratio < minimum:
            issues.append(
                f"{label} coverage is {ratio:.1%} ({count}/{total}); "
                f"expected at least {minimum:.0%}"
            )

    require_ratio("projection", projected, 0.58)
    require_ratio("ADP", with_adp, 0.15)
    require_ratio("bye-week", with_bye, 0.50)
    require_ratio("historical-stat", with_history, 0.50)
    require_ratio("provenance metadata", with_metadata, 0.50)
    if consensus == 0:
        issues.append("no player has a multi-source consensus projection")
    if kickers and projected_kickers / kickers < 0.50:
        issues.append(
            f"kicker projection coverage is {projected_kickers}/{kickers}; "
            "expected at least 50%"
        )

    return ProjectionQualityReport(
        total=total,
        position_counts=positions,
        projected=projected,
        with_adp=with_adp,
        with_bye=with_bye,
        with_history=with_history,
        with_metadata=with_metadata,
        consensus=consensus,
        kickers=kickers,
        projected_kickers=projected_kickers,
        duplicate_ids=duplicate_ids,
        issues=issues,
    )
