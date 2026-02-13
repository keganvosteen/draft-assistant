"""Auction draft support.

Computes dollar values from VOR distribution and tracks budgets.
"""
from __future__ import annotations
from typing import Dict, List, Optional, Tuple

from .models import LeagueConfig, Player
from .projections import compute_points, replacement_levels
from .scoring import fantasy_points


def compute_dollar_values(
    config: LeagueConfig,
    players: List[Player],
    budget_per_team: int = 200,
) -> Dict[str, float]:
    """Assign a dollar value to each player based on VOR share of total league budget.

    The approach:
      1. Compute VOR for every player (only positive-VOR players have value).
      2. Determine total roster spots that matter (starters only — bench is $1 each).
      3. Reserve $1 per bench spot, distribute the rest proportional to VOR.
    """
    pts_map = compute_points(players, config.scoring)
    repl = replacement_levels(players, config.scoring, config.teams, config.roster)

    # Compute VOR for each player
    vors: Dict[str, float] = {}
    for p in players:
        pts = pts_map.get(p.key(), 0.0)
        rep = repl.get(p.position, 0.0)
        vor = pts - rep
        if vor > 0:
            vors[p.key()] = vor

    if not vors:
        return {}

    total_vor = sum(vors.values())

    # Total league budget
    total_budget = budget_per_team * config.teams

    # Reserve $1 per roster spot for bench/minimum bids
    bench_slots = int(config.roster.get("BN", 0)) + int(config.roster.get("IR", 0))
    total_roster = sum(int(v) for v in config.roster.values())
    reserved = config.teams * total_roster  # $1 min per slot
    distributable = max(total_budget - reserved, 0)

    # Distribute proportional to VOR
    values: Dict[str, float] = {}
    for key, vor in vors.items():
        raw_val = (vor / total_vor) * distributable + 1.0  # +$1 base
        values[key] = round(raw_val, 1)

    return values


class AuctionTracker:
    """Track budgets and nominations in an auction draft."""

    def __init__(
        self,
        config: LeagueConfig,
        budget_per_team: int = 200,
    ):
        self.config = config
        self.budget_per_team = budget_per_team
        self.budgets: Dict[str, int] = {}
        for i in range(config.teams):
            self.budgets[f"Team {i+1}"] = budget_per_team
        self.won: Dict[str, List[Tuple[str, int]]] = {}  # team -> [(player_key, price)]

    def set_my_team(self, name: str) -> None:
        if name not in self.budgets:
            self.budgets[name] = self.budget_per_team
        self.my_team = name

    def record_win(self, team: str, player_key: str, price: int) -> bool:
        """Record that `team` won `player_key` for `price`."""
        if team not in self.budgets:
            return False
        if self.budgets[team] < price:
            return False
        self.budgets[team] -= price
        self.won.setdefault(team, []).append((player_key, price))
        return True

    def remaining_budget(self, team: str) -> int:
        return self.budgets.get(team, 0)

    def max_bid(self, team: str) -> int:
        """Max a team can bid, reserving $1 per remaining roster slot."""
        total_slots = sum(int(v) for v in self.config.roster.values())
        filled = len(self.won.get(team, []))
        remaining_slots = max(total_slots - filled - 1, 0)  # -1 for current nomination
        return max(self.budgets.get(team, 0) - remaining_slots, 1)

    def suggest_auction(
        self,
        players: List[Player],
        my_roster: Dict[str, List[Player]],
    ) -> List[Tuple[Player, float, float]]:
        """Return players sorted by value minus estimated cost.

        Returns: [(player, dollar_value, surplus)]
        where surplus = dollar_value - adp-based estimated price.
        """
        values = compute_dollar_values(self.config, players, self.budget_per_team)

        results: List[Tuple[Player, float, float]] = []
        for p in players:
            val = values.get(p.key(), 1.0)
            # Use ADP as a rough proxy for market price if available
            est_price = p.adp if p.adp and p.adp > 0 else val
            surplus = val - est_price
            results.append((p, val, surplus))

        results.sort(key=lambda t: t[2], reverse=True)
        return results
