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
    historical_stats: Dict[int, Dict[str, float]] = field(default_factory=dict)  # year -> stat dict
    previous_team: Optional[str] = None
    draft_capital: Optional[str] = None  # e.g. "1st-round", "UDFA"
    injury_history: List[str] = field(default_factory=list)

    def key(self) -> str:
        return f"{self.name}|{self.position}"


@dataclass
class LeagueConfig:
    teams: int
    roster: Dict[str, int]
    scoring: Dict[str, float]
    provider: Dict[str, object]


@dataclass
class DraftState:
    my_team_name: str
    league_teams: List[str]
    picks: List[str] = field(default_factory=list)  # player key strings in pick order
    my_picks: List[str] = field(default_factory=list)

    def picked_set(self) -> Set[str]:
        return set(self.picks)

