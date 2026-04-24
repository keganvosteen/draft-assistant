# Fantasy Football Draft Assistant

A Python draft assistant with two user interfaces (terminal and desktop GUI), multi-league profiles, draft-aware Monte Carlo scoring, historical trend analysis, and free public-data ingestion.

---

## Quick Start

**Requirements:** Python 3.10+. Core app has no external dependencies.

```bash
# Launch terminal UI (default, works everywhere)
python -m draft_assistant

# Launch Tkinter desktop UI
python -m draft_assistant ui

# Target a specific league profile
python -m draft_assistant --profile home draft
```

The terminal UI walks you through league setup on first run (teams, scoring format, roster, draft position), seeds sample player data, and drops you into a live draft board with commands like `pick <name>`, `my <name>`, `undo`, `log`, `auction`.

The desktop UI opens a Tkinter window with a draft board, roster panel, and a league switcher.

---

## How Suggestions Are Scored

Recommendations combine two scoring approaches:

### Base: Monte Carlo Draft-Aware VOR
- **Lineup gain** — how much the player improves your starter + bench value relative to your current roster.
- **Scarcity** — simulates opponent picks via ADP until your next snake-draft slot, estimates the drop-off in available value at each position.
- **VOR** — classic projected points above positional replacement level.
- **ADP discount** — small adjustment when a player is projected to be available after your next pick.

### Layer: Gradient Need + Historical Adjustment
On top of the base score, we apply:
- **Gradient position need** — multiplier scales smoothly from 0.60 (position fully filled) to ~1.25 (position empty), factoring in draft progress.
- **FLEX awareness** — RB/WR/TE overflow fills FLEX slots first, then need kicks in for additional picks.
- **Bye-week stacking penalty** — small subtraction when a player shares a bye week with someone already on your roster.
- **Age curves + historical blending** — projections are blended 60/40 with a weighted multi-year trend (when `age` and `historical_stats` are available), then scaled by positional age curves (RBs decline faster than WRs or QBs).
- **Team-change haircut** — players who switched NFL teams get a small projection discount.
- **Confidence score** — 0–1 rating shown in the UI reflecting data richness (seasons of history, injury flags, team stability).

---

## Interactive Terminal Commands

Inside `python -m draft_assistant draft`:

| Command | What it does |
|---------|-------------|
| `pick <name>` | Record someone else's pick (fuzzy name matching) |
| `my <name>` | Record YOUR pick |
| `pick <name> -p RB` | Disambiguate by position |
| `undo` / `undo 3` | Undo last pick(s) |
| `board` | Refresh the recommendation board |
| `log` | Show the full draft log |
| `roster` | Show your roster and needs |
| `auction` / `auction 300` | Show auction dollar values |
| `save` | Save draft state to disk |
| `help` | Show all commands |
| `quit` | Save and exit |

---

## Standalone CLI Commands

All commands accept `--profile <name>` to target a specific league:

| Command | Description |
|---------|-------------|
| `ui` | Launch Tkinter desktop UI |
| `draft` | Launch interactive terminal UI (default) |
| `init` | Initialize a profile with config + sample data |
| `suggest [-n N] [--draft-slot N] [--sims N]` | Show top N ranked suggestions |
| `pick "<name>"` | Record another team's pick |
| `mypick "<name>"` | Record your pick |
| `undo [-n N]` | Undo last N picks |
| `roster` | Show your roster + needs |
| `log [--csv path]` | Draft pick log, optional CSV export |
| `save` / `load` | Persist / restore draft state |
| `fetch` | Refresh from configured provider |
| `auction [--budget N] [-n N]` | Auction dollar values |
| `collect-all` | nflverse + Sleeper + FFC ADP collector (requires `nfl_data_py`) |
| `collect` | Sleeper-only historical stats collector |
| `pull-free-data` | No-dep collector (direct GitHub release CSVs + ESPN optional) |
| `pull-fftoday` | FFToday HTML scraper |
| `import-fpros` | Import FantasyPros CSVs |
| `consensus --sources a.json b.json` | Merge multiple projection files |

---

## Multi-League Profiles

Keep multiple league setups in one install.

- Default profile uses root files (`league.config.yaml`, `draft_state.json`, `data/projections.json`).
- Named profiles store config/state under `.draft_assistant_profiles/<name>/`, sharing the populated `data/projections.json`.
- In the desktop UI: use the `League` dropdown + `New League` buttons.
- In the terminal UI: run `python -m draft_assistant --profile <name>`.
- In any CLI command: add `--profile <name>`.

---

## Data Sources

### Option 1: `pull-free-data` (no extra dependencies)

Reads directly from nflverse GitHub release CSVs, Sleeper API, and Fantasy Football Calculator.

```bash
python -m draft_assistant pull-free-data --season 2026 --stats-season 2025
```

### Option 2: `collect-all` (richer, requires pip install)

Uses `nfl_data_py` for historical stats + injuries + derived bye weeks, combined with Sleeper projections and FFC ADP.

```bash
pip install -r requirements-data.txt
python -m draft_assistant collect-all --season 2026 --scoring ppr --teams 12
```

Both paths populate each player with: projections, ADP, age, experience, historical stats, bye week, team, injury history, and previous team (for team-change detection).

### Other importers

- `import-fpros --offense offense.csv --k k.csv --dst dst.csv` — FantasyPros CSV exports
- `pull-fftoday --season 2024` — FFToday HTML scraping (experimental)
- `consensus --sources a.json b.json --method median` — merge multiple projection files

---

## Configuration

Edit `league.config.yaml` (or use the setup wizards):

```json
{
  "teams": 12,
  "roster": {"QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 2, "K": 1, "DST": 1, "BN": 7},
  "scoring": {"pass_yd": 0.04, "pass_td": 4, "rec": 0.5, "rec_yd": 0.1, ...},
  "draft": {"slot": 5, "monte_carlo_sims": 250, "adp_noise": 8.0},
  "provider": {"type": "local_json", "options": {"path": "data/projections.json"}}
}
```

---

## Project Structure

```
draft_assistant/
├── __main__.py            # python -m draft_assistant entry point
├── cli.py                 # CLI argument parser and command dispatch
├── ui.py                  # Terminal UI (readline + ANSI + setup wizard)
├── ui_desktop.py          # Tkinter desktop UI
├── profiles.py            # Multi-league profile management
├── config.py              # League config load/save
├── models.py              # Player, LeagueConfig, DraftState dataclasses
├── draft.py               # DraftTracker with fuzzy matching + multi-step undo
├── draft_value.py         # Monte Carlo draft-aware VOR scoring
├── suggest.py             # Gradient need + bye penalty + historical layer
├── projections.py         # VOR and replacement-level computation
├── scoring.py             # Fantasy points from stat projections
├── historical.py          # Age curves, trend blending, confidence scoring
├── auction.py             # Auction dollar values + budget tracker
├── consensus.py           # Multi-source projection merging
├── fuzzy.py               # Levenshtein name matching
├── storage.py             # JSON persistence
├── export.py              # CSV export
├── sample_data.py         # Built-in sample players
├── collectors/            # Richer data collectors (require nfl_data_py)
│   ├── nflverse.py
│   ├── ffc_adp.py
│   ├── sleeper_historical.py
│   └── combined.py
├── importers/             # CSV + HTML importers, no-dep collectors
│   ├── free_sources.py    # GitHub CSV + Sleeper + FFC + ESPN
│   ├── fantasypros.py
│   └── fftoday.py
└── providers/             # Runtime player sources
    ├── base.py
    └── sleeper.py

tests/                     # 98 tests
├── test_scoring.py
├── test_projections.py
├── test_suggest.py
├── test_historical.py
├── test_draft.py
├── test_draft_value.py    # Monte Carlo math, snake picks
├── test_profiles.py       # Profile system
├── test_fuzzy.py
├── test_auction.py
├── test_nflverse_collector.py
└── test_combined_collector.py
```

---

## Running Tests

```bash
python -m unittest discover tests -v
```

98 tests cover scoring, VOR/replacement levels, gradient needs, FLEX, bye-week penalty, Monte Carlo snake-pick math, historical adjustments + age curves, fuzzy matching, draft tracking (pick/undo/log), auction values, data collectors, and profile management.

---

## Notes

- Network fetches are optional. Both UIs and the CLI work offline with the built-in sample data.
- Draft state persists to `draft_state.json` (or `.draft_assistant_profiles/<name>/draft_state.json` for non-default profiles).
- For Pro Football Reference and sites that block scraping, prefer the `collect-all` + `pull-free-data` paths which use public API endpoints and GitHub-hosted datasets.
