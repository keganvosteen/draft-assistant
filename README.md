# Fantasy Football Draft Assistant (CLI)

A Python CLI tool that helps you make smarter fantasy football draft picks in real time. It ranks available players using **Value Over Replacement (VOR)** adjusted for your roster needs, tracks every pick in your draft as it happens, and updates recommendations on the fly.

---

## How It Works

1. **Configure your league** — team count, roster slots, scoring rules (PPR, standard, custom).
2. **Load player projections** — from a local JSON file, FantasyPros CSVs, FFToday scraper, or the Sleeper API.
3. **Start your draft** — run `suggest` to see ranked recommendations, then record each pick (`pick` for others, `mypick` for yours).
4. **Get updated recommendations** — after every pick the engine recalculates VOR, factors in your roster needs, and re-ranks the remaining player pool.

### Ranking Algorithm

Players are scored using **VOR (Value Over Replacement)**:

```
VOR = Player_Projected_Points − Replacement_Level_Points_at_Position
```

Replacement level is the projected points of the last starter drafted at each position (accounting for FLEX allocation across RB/WR/TE). The score is then adjusted by several factors:

- **Gradient position need** — the multiplier scales with how many slots remain unfilled at that position. Needing 2 RBs produces a stronger boost than needing 1. Urgency also increases as the draft progresses.
- **FLEX awareness** — when your RB/WR/TE starter slots are full but FLEX slots remain open, those players still get a need boost instead of a penalty.
- **Bye week penalty** — drafting a player who shares a bye week with your existing starters incurs a small penalty to avoid bye-week stacking.
- **Historical adjustment** — when player age and historical stats are available, projections are blended with multi-year trends and adjusted by positional age curves (e.g., RBs decline faster than WRs or QBs).
- **Team change penalty** — players who switched teams get a small projection haircut reflecting the typical first-year adjustment cost.
- **Confidence score** — each player gets a 0–1 confidence rating based on data richness (historical seasons, age, injury history, team stability). Shown in the suggest output when meaningful.

---

## Quick Start

**Requirements:** Python 3.10+, no external dependencies.

```bash
# Option A: Launch the interactive draft UI (recommended)
python -m draft_assistant.cli draft

# Option B: Run with no arguments — same thing
python -m draft_assistant.cli
```

That's it. The interactive UI walks you through league setup (teams, scoring format, roster slots, your draft position) and then drops you into a live draft board where you type commands to record picks and get real-time recommendations.

### Interactive Commands (inside the draft UI)

| Command | What it does |
|---------|-------------|
| `pick <name>` | Record someone else's pick |
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

Player names support **fuzzy matching** — typing "Achan" finds "De'Von Achane", "Bijan" finds "Bijan Robinson", etc.

### Advanced: Individual CLI Commands

You can also run commands one at a time from the shell (useful for scripting or quick lookups):

```bash
python -m draft_assistant.cli init              # Initialize config + sample data
python -m draft_assistant.cli suggest -n 15     # Show top 15 suggestions
python -m draft_assistant.cli pick "Bijan"      # Record a pick
python -m draft_assistant.cli mypick "Lamb"     # Record your pick
python -m draft_assistant.cli roster            # Show roster + needs
python -m draft_assistant.cli auction --budget 200
```

---

## Commands

| Command | Description |
|---------|-------------|
| `draft` | **Launch the interactive draft UI** (also the default with no args) |
| `init` | Generate `league.config.yaml` and seed sample data |
| `fetch` | Refresh player data from the configured provider |
| `suggest [-n N]` | Show top N ranked suggestions (default 12) |
| `pick "<name>"` | Record another team's pick (supports fuzzy matching) |
| `mypick "<name>"` | Record your pick |
| `undo [-n N]` | Undo the last N picks (default 1) |
| `roster` | Show your roster and position needs (including FLEX) |
| `log [--csv path]` | Show full draft log with round/pick numbers; optionally export to CSV |
| `save` / `load` | Persist or restore draft state to `draft_state.json` |
| `collect-all` | **Collect from all sources: nflverse + Sleeper + FFC ADP** |
| `collect` | Fetch enriched player data from Sleeper API only |
| `consensus` | Merge multiple projection sources into a single consensus file |
| `auction` | Show auction dollar values for all players |
| `import-fpros` | Import FantasyPros CSV projections |
| `pull-fftoday` | Scrape FFToday projections (experimental) |

All commands are run via `python -m draft_assistant.cli <command>`.

---

## Configuration

Edit `league.config.yaml` to match your league settings:

```yaml
teams: 10
roster:
  QB: 1
  RB: 2
  WR: 2
  TE: 1
  FLEX: 2       # RB/WR/TE eligible
  K: 1
  DST: 1
  BN: 7
  IR: 1

scoring:
  pass_yd: 0.04    # 1 point per 25 yards
  pass_td: 4
  pass_int: -2
  rush_yd: 0.1     # 1 point per 10 yards
  rush_td: 6
  rec: 0.5         # PPR (set to 0 for standard, 1 for full PPR)
  rec_yd: 0.1
  rec_td: 6
  fumbles: -2
  # ... kicker and DST stats also supported

provider:
  type: local_json
  options:
    path: data/projections.json
```

---

## Data Sources

### Collect All (recommended)

The `collect-all` command pulls from three free sources and merges them into a single enriched dataset:

```bash
# Install the data dependency first
pip install nfl_data_py pandas

# Collect everything: nflverse historical stats + Sleeper projections + FFC ADP
python -m draft_assistant.cli collect-all --season 2026

# Customize for your league
python -m draft_assistant.cli collect-all --season 2026 --scoring half-ppr --teams 10

# Offline mode (nflverse only, no Sleeper/ADP API calls)
python -m draft_assistant.cli collect-all --season 2026 --skip-sleeper --skip-adp
```

This gives every player: multi-year historical stats, age, draft capital, injury history, bye weeks, team-change detection, current projections, and ADP — all from free, public data.

You can also choose "Collect real data" during the interactive setup wizard (`python -m draft_assistant.cli draft`).

**Sources used:**
| Source | Data | Requires |
|--------|------|----------|
| [nflverse](https://github.com/nflverse/nflverse-data) via `nfl_data_py` | Historical stats, rosters, injuries, bye weeks | `pip install nfl_data_py pandas` |
| [Sleeper API](https://docs.sleeper.com/) | Current-season projections, player metadata | Internet (free, no key) |
| [Fantasy Football Calculator](https://fantasyfootballcalculator.com/api/v1/adp/) | ADP by format | Internet (free, no key) |

### Local JSON (default)

The `init` command seeds `data/projections.json` with sample players. Replace this file with your own projections or use an importer below.

### FantasyPros CSV Import

```bash
python -m draft_assistant.cli import-fpros \
  --offense path/to/offense.csv \
  --k path/to/kicker.csv \
  --dst path/to/dst.csv \
  --out data/projections.json
```

- Offense CSV covers QB/RB/WR/TE stats (passing, rushing, receiving).
- Kicker CSV maps PAT and FG by yardage range; misses computed from attempts if available.
- DST CSV maps sacks, INTs, fumble recoveries, safeties, and TDs.
- Missing 2-point conversion stats default to 0. Points/yards-allowed tiers for DST are not typically provided and remain 0.

### FFToday Scraper (experimental)

```bash
python -m draft_assistant.cli pull-fftoday \
  --season 2024 \
  --out data/projections.json \
  --csv data/projections.csv
```

Uses basic HTML parsing — may break if the site structure changes. DST points/yards-allowed tiers are not provided.

### Sleeper API (metadata + historical stats)

Set `provider.type: sleeper` in config for basic metadata and ADP. For the full enriched dataset with historical stats, use the `collect` command:

```bash
# Fetch player metadata, 3 years of historical stats, and current projections
python -m draft_assistant.cli collect --season 2025 --history 3

# Customize output path
python -m draft_assistant.cli collect --season 2025 --out data/enriched.json
```

This populates each player with age, experience, historical per-season stats, injury status, and team-change flags — all of which feed into the historical adjustment and confidence scoring.

### Multi-Source Consensus

Combine projections from multiple sources to reduce single-source bias:

```bash
# Import from two sources into separate files first
python -m draft_assistant.cli import-fpros --offense fpros.csv --out data/fpros.json
python -m draft_assistant.cli pull-fftoday --season 2025 --out data/fftoday.json

# Merge into consensus (median by default, or mean)
python -m draft_assistant.cli consensus --sources data/fpros.json data/fftoday.json --out data/projections.json
python -m draft_assistant.cli consensus --sources data/fpros.json data/fftoday.json --method mean
```

The consensus engine matches players by name+position across sources and merges their stat projections. Metadata (age, historical stats, ADP) is taken from whichever source has the richest data.

---

## Project Structure

```
draft_assistant/
├── cli.py              # CLI entry point and command dispatch
├── ui.py               # Interactive terminal UI (setup wizard + live draft board)
├── config.py           # YAML config loading
├── models.py           # Player, LeagueConfig, DraftState dataclasses
├── draft.py            # DraftTracker — pick recording, roster tracking, fuzzy matching
├── scoring.py          # Fantasy point calculation from stat projections
├── projections.py      # VOR computation and replacement level calculation
├── suggest.py          # Suggestion engine — gradient needs, FLEX, bye weeks
├── historical.py       # Age curves, historical trend blending, confidence scoring
├── consensus.py        # Multi-source projection merging (median/mean)
├── auction.py          # Auction draft dollar values and budget tracking
├── fuzzy.py            # Levenshtein distance fuzzy string matching
├── storage.py          # JSON persistence (supports extended player fields)
├── sample_data.py      # Built-in sample players for demo
├── export.py           # CSV export
├── collectors/
│   ├── combined.py            # Orchestrates all data sources into one dataset
│   ├── nflverse.py            # Historical stats, rosters, injuries via nfl_data_py
│   ├── ffc_adp.py             # ADP from Fantasy Football Calculator API
│   └── sleeper_historical.py  # Projections + metadata from Sleeper API
├── importers/
│   ├── fantasypros.py  # FantasyPros CSV parser
│   └── fftoday.py      # FFToday HTML scraper
└── providers/
    ├── base.py         # Provider interface + LocalJsonProvider
    └── sleeper.py      # Sleeper.app API provider

tests/
├── test_scoring.py     # Fantasy point calculation tests
├── test_projections.py # VOR and replacement level tests
├── test_suggest.py     # Suggestion engine tests (FLEX, gradient needs, bye weeks)
├── test_historical.py  # Age curve and historical adjustment tests
├── test_draft.py       # Pick recording, fuzzy matching, undo, draft log tests
├── test_fuzzy.py       # Levenshtein distance tests
├── test_auction.py     # Auction dollar value and budget tests
├── test_nflverse_collector.py  # nflverse data collector tests
└── test_combined_collector.py  # Combined collector and name matching tests
```

---

## Extending

Add a custom data provider by implementing the `Provider` interface in `draft_assistant/providers/` and registering it in the `build_provider()` factory. Then set `provider.type` in your config.

---

## Auction Drafts

For auction leagues, use the `auction` command to see dollar values derived from VOR:

```bash
python -m draft_assistant.cli auction --budget 200 -n 50
```

This distributes the total league budget proportional to each player's VOR, reserving $1 per roster slot as a minimum bid. The `AuctionTracker` class (in `auction.py`) also supports tracking per-team budgets and max-bid calculations during a live auction.

---

## Running Tests

```bash
python -m unittest discover tests -v
```

80 tests cover scoring, VOR/replacement levels, the suggestion engine (gradient needs, FLEX, bye weeks), historical adjustments, age curves, fuzzy matching, draft tracking, and auction values.

---

## Remaining Opportunities

The following are areas that could still be improved:

- **Weather/matchup/environmental factors** — stadium type, altitude, cold-weather games, and divisional matchup data could further refine projections. This is a stretch goal best pursued after the current features are battle-tested in a real draft.
- **Strength of schedule** — weighting projections toward playoff-week matchups (weeks 14–17) rather than treating all weeks equally.
- **Remaining positional supply** — the need multiplier currently scales by how many of *your* slots are unfilled, but doesn't account for how many startable players remain in the pool. If only 3 TEs are left and you need one, urgency should be higher than if 15 remain.
- **Coaching/scheme change tracking** — the `previous_team` field captures player team changes, but coaching staff and scheme changes (new OC, run-heavy vs. pass-heavy) aren't tracked yet.
- **Web UI** — the interactive terminal UI works well but a browser-based draft board could be even faster for live drafts.
