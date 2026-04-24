"""Fetch ADP data from the Fantasy Football Calculator free API.

Endpoint: https://fantasyfootballcalculator.com/api/v1/adp/{format}?teams={n}&year={year}
Formats: standard, ppr, half-ppr, 2qb, dynasty, rookie
No API key required. Attribution requested.
"""
from __future__ import annotations

import json
from typing import Dict, Optional
from urllib.request import urlopen, Request
from urllib.error import URLError

FFC_ADP_URL = "https://fantasyfootballcalculator.com/api/v1/adp/{fmt}?teams={teams}&year={year}"


def _fetch_json(url: str) -> Optional[dict]:
    try:
        req = Request(url, headers={
            "User-Agent": "DraftAssistant/1.0",
            "Accept": "application/json",
        })
        with urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (URLError, OSError, json.JSONDecodeError) as e:
        print(f"  Warning: FFC ADP fetch failed: {e}")
        return None


def fetch_adp(
    year: int = 2025,
    scoring: str = "ppr",
    teams: int = 12,
) -> Dict[str, float]:
    """Fetch ADP data from Fantasy Football Calculator.

    Args:
        year: Draft season year.
        scoring: Scoring format — "ppr", "half-ppr", "standard", "2qb".
        teams: League size (8, 10, 12, 14).

    Returns:
        Dict mapping "PlayerName|Position" keys to ADP float values.
    """
    fmt_map = {"ppr": "ppr", "half": "half-ppr", "half-ppr": "half-ppr",
               "standard": "standard", "2qb": "2qb"}
    fmt = fmt_map.get(scoring, "ppr")

    url = FFC_ADP_URL.format(fmt=fmt, teams=teams, year=year)
    print(f"Fetching ADP from Fantasy Football Calculator ({fmt}, {teams} teams, {year})...")

    data = _fetch_json(url)
    if not data:
        return {}

    players = data.get("players", [])
    if not players:
        print("  No ADP data returned.")
        return {}

    adp_map: Dict[str, float] = {}
    pos_normalize = {"DEF": "DST", "PK": "K"}

    for entry in players:
        name = entry.get("name", "").strip()
        pos = entry.get("position", "").upper()
        adp_val = entry.get("adp")

        if not name or adp_val is None:
            continue

        pos = pos_normalize.get(pos, pos)
        key = f"{name}|{pos}"
        adp_map[key] = float(adp_val)

    print(f"  Loaded ADP for {len(adp_map)} players.")
    return adp_map
