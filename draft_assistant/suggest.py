from __future__ import annotations
from typing import Dict, List, Tuple

from .models import LeagueConfig, Player
from .projections import compute_points, replacement_levels


NEED_BOOST = 1.10
FILLED_PENALTY = 0.70


def needs_by_position(config: LeagueConfig, my_roster: Dict[str, List[Player]]) -> Dict[str, int]:
    needs: Dict[str, int] = {}
    for pos in ["QB", "RB", "WR", "TE", "K", "DST"]:
        target = int(config.roster.get(pos, 0))
        have = len(my_roster.get(pos, []))
        needs[pos] = max(target - have, 0)
    # Flex doesn't show in position-specific needs
    return needs


def suggest_players(config: LeagueConfig, available: List[Player], my_roster: Dict[str, List[Player]], top_n: int = 12) -> List[Tuple[Player, float, float, float]]:
    # Returns list of tuples: (player, points, vor, score)
    pts_map = compute_points(available, config.scoring)
    repl = replacement_levels(available, config.scoring, config.teams, config.roster)
    needs = needs_by_position(config, my_roster)

    ranked: List[Tuple[Player, float, float, float]] = []
    for p in available:
        pts = pts_map.get(p.key(), 0.0)
        rep = repl.get(p.position, 0.0)
        vor = pts - rep

        need_mult = NEED_BOOST if needs.get(p.position, 0) > 0 else FILLED_PENALTY
        score = vor * need_mult
        ranked.append((p, pts, vor, score))

    ranked.sort(key=lambda t: (t[3], t[2], t[1]), reverse=True)
    return ranked[:top_n]

