"""Quality checks for a production projection board.

The collectors intentionally tolerate partial upstream failures so a user can
still inspect what was returned.  Shipping that partial board as the default is
different: missing byes, history, provenance, or an entire scoring position can
silently invalidate recommendations.  This module provides the stricter gate
used by packaging and CI for the repository's bundled board.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Dict, Iterable, List, Optional

from .context import current_bye_week
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

#: Share of the byes held by players on an NFL team that the engine may be
#: ignoring. A healthy pull leaves a handful -- someone who changed teams since
#: the stamp, a team code the schedule does not list -- and those must not
#: block a release. A board saved before bye provenance existed has *every* bye
#: in that state, and that is the failure this exists to catch: 1,325 stored
#: byes, none of them used.
MAX_STALE_BYE_SHARE = 0.02


@dataclass(frozen=True)
class ProjectionQualityReport:
    total: int
    position_counts: Dict[str, int]
    projected: int
    with_adp: int
    with_bye: int
    #: Byes ``current_bye_week`` will actually return, judged for ``bye_season``.
    with_verified_bye: int
    #: Players on an NFL team whose stored bye week the engine would ignore.
    stale_byes: int
    #: The season the board's own bye stamps name; None when nothing is stamped.
    bye_season: Optional[int]
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


def board_bye_season(players: Iterable[Player]) -> Optional[int]:
    """The season a board's byes are stamped for: the newest its stamps name.

    Provenance is judged against this, deliberately not the calendar. The gate
    runs offline on every pull request and release build against a tracked
    board that only changes when someone regenerates it; measured against
    ``date.today()`` that same board would turn red on New Year's Day and stay
    red until the next schedule is published in May. The newest stamp wins, so
    a board that mixes seasons still has its older stamps counted as stale.
    """
    seasons: List[int] = []
    for player in players:
        try:
            seasons.append(int((player.metadata or {}).get("bye_season")))
        except (TypeError, ValueError):
            continue
    return max(seasons) if seasons else None


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
    bye_season = board_bye_season(board)

    def verified_bye(player: Player) -> bool:
        # Ask the same question the engine asks. Counting a non-null bye_week
        # is how a board with 1,325 stored byes and none in use passed here.
        return bool(player.metadata) and current_bye_week(player, bye_season) is not None

    with_verified_bye = sum(verified_bye(player) for player in board)
    # Board-wide, not just the draftable head: the waiver wire reads byes for
    # the deep pool too. Players with no NFL team are left out -- they have no
    # bye to verify, and refresh-byes could not stamp one if they did.
    on_team_with_bye = [p for p in board if p.team and p.bye_week is not None]
    stale_byes = sum(not verified_bye(player) for player in on_team_with_bye)
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
    relevant_bye = sum(verified_bye(p) for p in relevant)
    relevant_history = sum(bool(p.historical_stats) for p in relevant)
    relevant_kickers = [p for p in relevant if p.position == "K"]
    relevant_projected_kickers = sum(bool(p.projections) for p in relevant_kickers)

    require_ratio("projection", relevant_projected, n_relevant, 0.58)
    require_ratio("verified bye-week", relevant_bye, n_relevant, 0.50)
    # A board with no byes at all fails the coverage line above and stops
    # there. This one is for byes that are present and unusable, which coverage
    # of the head alone would report as a board that simply never had any.
    if stale_byes > len(on_team_with_bye) * MAX_STALE_BYE_SHARE:
        why = (f"bye_season/bye_team do not match the board's {bye_season} stamps"
               if bye_season is not None else "no bye_season stamp anywhere on the board")
        issues.append(
            f"{stale_byes} of {len(on_team_with_bye)} players on an NFL team carry a "
            f"bye week the engine ignores ({why}); expected at most "
            f"{MAX_STALE_BYE_SHARE:.0%} -- run refresh-byes"
        )
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
        with_verified_bye=with_verified_bye,
        stale_byes=stale_byes,
        bye_season=bye_season,
        with_history=with_history,
        with_metadata=with_metadata,
        consensus=consensus,
        kickers=kickers,
        projected_kickers=projected_kickers,
        duplicate_ids=duplicate_ids,
        issues=issues,
    )
