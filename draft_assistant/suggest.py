from __future__ import annotations
from typing import Dict, List, Optional, Tuple

from .draft_value import draft_aware_values
from .models import DraftState, LeagueConfig, Player


def needs_by_position(config: LeagueConfig, my_roster: Dict[str, List[Player]]) -> Dict[str, int]:
    needs: Dict[str, int] = {}
    for pos in ["QB", "RB", "WR", "TE", "K", "DST"]:
        target = int(config.roster.get(pos, 0))
        have = len(my_roster.get(pos, []))
        needs[pos] = max(target - have, 0)
    flex_target = int(config.roster.get("FLEX", 0))
    eligible_have = sum(len(my_roster.get(pos, [])) for pos in ["RB", "WR", "TE"])
    eligible_slots = sum(int(config.roster.get(pos, 0)) for pos in ["RB", "WR", "TE"]) + flex_target
    eligible_need = max(eligible_slots - eligible_have, 0)
    base_eligible_need = sum(needs.get(pos, 0) for pos in ["RB", "WR", "TE"])
    needs["FLEX"] = max(eligible_need - base_eligible_need, 0)
    return needs


def suggest_players(
    config: LeagueConfig,
    available: List[Player],
    my_roster: Dict[str, List[Player]],
    top_n: int = 12,
    draft_state: Optional[DraftState] = None,
) -> List[Tuple[Player, float, float, float]]:
    # Returns list of tuples: (player, points, VOR, draft-aware score).
    ranked = draft_aware_values(
        config=config,
        available=available,
        my_roster=my_roster,
        state=draft_state,
        top_n=top_n,
    )
    return [(item.player, item.points, item.vor, item.score) for item in ranked]

