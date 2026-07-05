"""Scoring helpers shared by the web API and frontend parity tests."""
from __future__ import annotations

STANDARD_SCORING = {
    "pass_yd": 0.04,
    "pass_td": 4,
    "pass_int": -2,
    "rush_yd": 0.1,
    "rush_td": 6,
    "rec_yd": 0.1,
    "rec_td": 6,
    "fumbles": -2,
}

_PRESET_REC = {"standard": 0.0, "ppr": 1.0, "half-ppr": 0.5}


def scoring_for_league(league: dict, base_scoring: dict) -> dict:
    """Overlay the web LeagueSetup scoring choice onto base scoring."""
    stype = league.get("scoringType")
    if not stype:
        return base_scoring
    scoring = dict(base_scoring)
    if stype in _PRESET_REC:
        scoring["rec"] = _PRESET_REC[stype]
        return scoring
    if stype == "custom":
        cs = league.get("customScoring") or {}

        def per_yd(denom):
            denom = float(denom or 0)
            return (1.0 / denom) if denom else 0.0

        two_pt = float(cs.get("twoPt", 0) or 0)
        scoring.update({
            "pass_yd": per_yd(cs.get("passYds")),
            "pass_td": float(cs.get("passTD", 0) or 0),
            "pass_int": float(cs.get("passInt", 0) or 0),
            "rush_yd": per_yd(cs.get("rushYds")),
            "rush_td": float(cs.get("rushTD", 0) or 0),
            "rec_yd": per_yd(cs.get("recYds")),
            "rec_td": float(cs.get("recTD", 0) or 0),
            "rec": float(cs.get("reception", 0) or 0),
            "pass_2pt": two_pt,
            "rush_2pt": two_pt,
            "rec_2pt": two_pt,
            "fum_ret_td": float(cs.get("fumRetTD", 0) or 0),
            "fumbles_total": float(cs.get("fumble", 0) or 0),
            "fumbles": (
                float(cs["fumbleLost"])
                if cs.get("fumbleLost") is not None
                else scoring.get("fumbles", -2.0)
            ),
        })
        if cs.get("sackTaken"):
            scoring["sack_taken"] = float(cs["sackTaken"])
        return scoring
    return base_scoring
