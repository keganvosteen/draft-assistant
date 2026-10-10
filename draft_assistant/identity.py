"""Resolve persisted player identities across provider failures and refreshes."""
from __future__ import annotations

from typing import Iterable

from .models import Player


def player_aliases(player: Player) -> set[str]:
    metadata = player.metadata or {}
    aliases = {player.key(), player.legacy_key()}
    saved = metadata.get("identity_aliases", [])
    if isinstance(saved, list):
        aliases.update(value for value in saved if isinstance(value, str) and value)
    for field, providers in (
        ("sleeper_id", ("sleeper",)), ("espn_id", ("espn",)),
        ("yahoo_id", ("yahoo",)), ("yahoo_player_id", ("yahoo",)),
        ("ffc_player_id", ("ffc",)), ("gsis_id", ("gsis", "nflverse")),
    ):
        value = metadata.get(field)
        if value not in (None, ""):
            aliases.update(f"{provider}:{value}" for provider in providers)
    return aliases


def player_indexes(players: Iterable[Player]) -> tuple[dict[str, Player], dict[str, str]]:
    """Canonical IDs win; an ambiguous secondary alias never guesses ownership."""
    players = list(players)
    canonical = {player.key(): player for player in players}
    owners: dict[str, set[str]] = {}
    for player in players:
        for alias in player_aliases(player):
            owners.setdefault(alias, set()).add(player.key())
    aliases = {
        alias: next(iter(keys)) for alias, keys in owners.items()
        if len(keys) == 1 and alias not in canonical
    }
    return canonical, aliases


def retain_aliases(player: Player, previous: Player) -> None:
    """Retain every known identity without copying stale stats or context."""
    player.metadata = dict(player.metadata or {})
    player.metadata["identity_aliases"] = sorted(player_aliases(player) | player_aliases(previous))
