from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set


@dataclass
class Player:
    id: str
    name: str
    position: str
    team: Optional[str] = None
    bye_week: Optional[int] = None
    adp: Optional[float] = None
    projections: Dict[str, float] = field(default_factory=dict)
    # Extended fields for historical / contextual analysis
    age: Optional[int] = None
    experience: Optional[int] = None  # years in NFL
    historical_stats: Dict[int, Dict[str, float]] = field(default_factory=dict)
    previous_team: Optional[str] = None
    draft_capital: Optional[str] = None  # e.g. "1st-round", "UDFA"
    injury_history: List[str] = field(default_factory=list)
    # Free-form bucket for provider-specific extras
    metadata: Dict[str, object] = field(default_factory=dict)

    def key(self) -> str:
        """Stable persisted identity, falling back for hand-authored players."""
        stable_id = str(self.id or "").strip()
        return stable_id or self.legacy_key()

    def legacy_key(self) -> str:
        """Pre-v2 display-derived key retained for state-file migration."""
        return f"{self.name}|{self.position}"


@dataclass(frozen=True)
class PlayerSignal:
    """One timestamped, attributable piece of player context.

    Signals deliberately live outside ``Player.projections``.  Refreshing news
    must never compound a multiplier into the persisted baseline projection.
    ``player_id`` is a provider-qualified alias such as ``sleeper:1234`` or
    ``gsis:00-0031234`` and is joined to the board through provider metadata.
    """

    player_id: str
    kind: str
    value: str
    source: str
    observed_at: str
    effective_week: Optional[int] = None
    expires_at: Optional[str] = None
    attribution: Optional[str] = None
    details: Dict[str, object] = field(default_factory=dict)


@dataclass
class PlayerContext:
    """Cached dynamic inputs used to derive weekly and ROS point views."""

    season: int
    selected_week: int
    refreshed_at: Optional[str] = None
    signals: List[PlayerSignal] = field(default_factory=list)
    weekly_projections: Dict[str, Dict[str, float]] = field(default_factory=dict)
    actual_stats: Dict[str, Dict[str, float]] = field(default_factory=dict)
    source_health: Dict[str, Dict[str, object]] = field(default_factory=dict)


@dataclass
class LeagueConfig:
    teams: int
    roster: Dict[str, int]
    scoring: Dict[str, float]
    provider: Dict[str, object]
    draft: Dict[str, object] = field(default_factory=dict)


@dataclass
class DraftState:
    my_team_name: str
    league_teams: List[str]
    picks: List[str] = field(default_factory=list)  # player key strings in pick order
    my_picks: List[str] = field(default_factory=list)

    def picked_set(self) -> Set[str]:
        return set(self.picks)


# Flex roster slots → the positions eligible to fill each. Keys beyond "FLEX"
# let a league encode constrained flex spots — e.g. a WR/TE slot that must NOT be
# fillable by an RB — which changes positional value and draft strategy. The
# engine fills the most-restrictive flex slots first so eligibility is respected.
FLEX_TYPES: Dict[str, tuple] = {
    "FLEX": ("RB", "WR", "TE"),
    "WRTE": ("WR", "TE"),
    "RBWR": ("RB", "WR"),
    "SUPERFLEX": ("QB", "RB", "WR", "TE"),
    "OP": ("QB", "RB", "WR", "TE"),
}

