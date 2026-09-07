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

#: Coverage ratios are measured over the players who might actually be drafted,
#: not the whole pool. A provider's player universe grows without the board
#: getting worse -- Sleeper alone lists ~2,000 players with an ADP, most of whom
#: nobody projects because nobody drafts them. Scoring coverage against that
#: denominator punishes carrying *more* data: a pull that added ESPN and lifted
#: consensus in the top 200 from 76% to 88% still "failed" for having also
#: brought in a thousand undraftable names. A deep 12-team league makes about
#: 200 picks, so 300 is a generous cut that stays honest about what matters.
DRAFT_RELEVANT_BY_ADP = 300


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

    def require_ratio(label: str, count: int, denominator: int, minimum: float) -> None:
        ratio = (count / denominator) if denominator else 0.0
        if ratio < minimum:
            issues.append(
                f"{label} coverage is {ratio:.1%} ({count}/{denominator}); "
                f"expected at least {minimum:.0%}"
            )

    # The draftable slice: best ADP first, unranked players last. With no ADP
    # anywhere there is no head to speak of -- ordering would fall back to
    # whatever order the pull happened to emit, which can exclude a whole
    # position and quietly skip its check. Judge the entire board instead: a
    # pull that lost every ADP is broken, and the gate should get stricter when
    # information disappears, never more forgiving.
    relevant = board if not with_adp else sorted(
        board,
        key=lambda p: (p.adp is None, p.adp if p.adp is not None else 9999.0),
    )[:DRAFT_RELEVANT_BY_ADP]
    n_relevant = len(relevant)
    relevant_projected = sum(bool(p.projections) for p in relevant)
    relevant_bye = sum(p.bye_week is not None for p in relevant)
    relevant_history = sum(bool(p.historical_stats) for p in relevant)
    relevant_kickers = [p for p in relevant if p.position == "K"]
    relevant_projected_kickers = sum(bool(p.projections) for p in relevant_kickers)

    require_ratio("projection", relevant_projected, n_relevant, 0.58)
    require_ratio("bye-week", relevant_bye, n_relevant, 0.50)
    require_ratio("historical-stat", relevant_history, n_relevant, 0.50)
    # These two describe the whole board, not just its draftable head: a pull
    # that lost ADP or provenance wholesale is broken however deep you look.
    require_ratio("ADP", with_adp, total, 0.15)
    require_ratio("provenance metadata", with_metadata, total, 0.50)
    if consensus == 0:
        issues.append("no player has a multi-source consensus projection")
    if relevant_kickers and relevant_projected_kickers / len(relevant_kickers) < 0.50:
        issues.append(
            f"kicker projection coverage is {relevant_projected_kickers}/"
            f"{len(relevant_kickers)} among draftable kickers; expected at least 50%"
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
