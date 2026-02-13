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

Replacement level is the projected points of the last starter drafted at each position (accounting for FLEX allocation across RB/WR/TE). A position-need multiplier is then applied:

- **+10% boost** if you still need a starter at that position
- **−30% penalty** if that position is already filled

Final ranking sorts by adjusted score, then raw VOR, then total points as tiebreakers.

---

## Quick Start

**Requirements:** Python 3.10+, no external dependencies.

```bash
# 1. Initialize config and seed sample player data
python -m draft_assistant.cli init

# 2. View top draft suggestions
python -m draft_assistant.cli suggest

# 3. Record picks as the draft progresses
python -m draft_assistant.cli pick "Bijan Robinson"      # someone else drafted him
python -m draft_assistant.cli mypick "CeeDee Lamb"       # you drafted Lamb

# 4. Check your roster and remaining needs
python -m draft_assistant.cli roster

# 5. Get updated suggestions (pool and needs have changed)
python -m draft_assistant.cli suggest
```

---

## Commands

| Command | Description |
|---------|-------------|
| `init` | Generate `league.config.yaml` and seed sample data |
| `fetch` | Refresh player data from the configured provider |
| `suggest [-n N]` | Show top N ranked suggestions (default 12) |
| `pick "<name>"` | Record another team's pick |
| `mypick "<name>"` | Record your pick |
| `undo` | Undo the last pick |
| `roster` | Show your current roster and position needs |
| `save` / `load` | Persist or restore draft state to `draft_state.json` |
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

### Sleeper API

Set `provider.type: sleeper` in config. Fetches player metadata and ADP but **not** projections — combine with another source for projection data.

---

## Project Structure

```
draft_assistant/
├── cli.py              # CLI entry point and command dispatch
├── config.py           # YAML config loading
├── models.py           # Player, LeagueConfig, DraftState dataclasses
├── draft.py            # DraftTracker — pick recording, roster tracking
├── scoring.py          # Fantasy point calculation from stat projections
├── projections.py      # VOR computation and replacement level calculation
├── suggest.py          # Suggestion engine with position-need weighting
├── storage.py          # JSON persistence for draft state and players
├── sample_data.py      # Built-in sample players for demo
├── export.py           # CSV export
├── importers/
│   ├── fantasypros.py  # FantasyPros CSV parser
│   └── fftoday.py      # FFToday HTML scraper
└── providers/
    ├── base.py         # Provider interface + LocalJsonProvider
    └── sleeper.py      # Sleeper.app API provider
```

---

## Extending

Add a custom data provider by implementing the `Provider` interface in `draft_assistant/providers/` and registering it in the `build_provider()` factory. Then set `provider.type` in your config.

---

## Known Limitations and Recommended Improvements

The current implementation is a solid foundation with clean architecture, but there are meaningful gaps between what it does today and the goal of being a smart, historically-informed draft recommender. The issues below are ordered roughly by impact.

### 1. Projections Are Static and Single-Source

**Current behavior:** The app consumes a flat projection file — one number per stat per player. These projections typically come from a single source (FantasyPros, FFToday) and represent a single season forecast.

**Why it matters:** Single-source projections have wide error bars. A player's projection is only as good as the model behind it, and all models have blind spots.

**Recommended improvements:**
- Support importing from multiple projection sources and computing a consensus (weighted average or median) across them.
- Add a confidence/variance field per player so the suggestion engine can factor in projection certainty — a high-floor player may be preferable to a high-ceiling but volatile one depending on draft position.

### 2. No Historical Trend Analysis

**Current behavior:** Projections are consumed as-is with no consideration of historical performance, age curves, career trajectory, or year-over-year trends.

**Why it matters:** This is the core gap relative to the stated goal. A 30-year-old running back with declining yards-per-carry is a different proposition than a 24-year-old with identical raw projections. Context like team changes, coaching hires, offensive line quality, and target share trends all affect whether a projection is likely to be met, exceeded, or missed.

**Recommended improvements:**
- Store multi-year historical stats per player (at minimum 2–3 prior seasons).
- Implement age-adjusted projections using known positional aging curves (RBs decline earlier than WRs/QBs).
- Track situation changes: new team (via trade/free agency), new offensive coordinator, changes in surrounding cast (e.g., a WR1 leaving opens targets for the WR2).
- Weight recent seasons more heavily but flag players whose projection diverges significantly from their historical trend line.
- Consider adding a simple regression model or lookup table for common factors (age × position → expected decline %).

### 3. Position Need Logic Is Binary

**Current behavior:** The need multiplier is either +10% (need) or −30% (filled). There is no gradient — needing 2 RBs is treated the same as needing 1, and the penalty for a filled position is the same whether you have 2 of them or 5.

**Why it matters:** In a real draft, the urgency to fill a position increases as the draft progresses and eligible players thin out. Drafting your RB2 is less urgent than your RB1, and adding bench depth at a position you've already started is different from having zero starters there.

**Recommended improvements:**
- Scale the need multiplier by how many slots remain unfilled at that position (e.g., needing 2 RBs → larger boost than needing 1).
- Factor in draft round context — if you're in round 10 of 15 and still have no TE, the TE boost should be much higher.
- Consider remaining supply: if there are only 3 startable TEs left and you need one, that's more urgent than 3 remaining when 15 are available.
- Account for bench slots — once starters are filled, bench depth at thin positions still has value.

### 4. No Bye Week or Schedule Awareness

**Current behavior:** Bye weeks are stored on the Player model but never used in recommendations.

**Why it matters:** Drafting 3 starters who all share a bye week creates a week where your lineup is severely weakened. Similarly, players with favorable early-season schedules may outperform their season-long projection during the fantasy-relevant weeks.

**Recommended improvements:**
- Penalize picks that create bye week stacking (multiple starters sharing the same bye).
- Optionally factor in strength of schedule, especially for playoff weeks (weeks 14–17).

### 5. No Auction Draft Support

**Current behavior:** The app assumes a snake/linear draft format. There is no concept of budget, player pricing, or value-over-cost.

**Why it matters:** A large portion of competitive fantasy leagues use auction drafts, where the key question is not "who is the best available?" but "who provides the most value relative to their price?"

**Recommended improvements:**
- Add an auction mode that tracks remaining budget per team.
- Compute a dollar value per player based on VOR distribution and total league budget.
- Suggest players where projected value exceeds expected cost (bargains).

### 6. FLEX Handling Could Be Smarter

**Current behavior:** FLEX is handled at the replacement level calculation by merging RB/WR/TE pools, but the need calculation in `suggest.py` ignores FLEX entirely (`# Flex doesn't show in position-specific needs`).

**Why it matters:** If your RB and WR starters are filled but you have open FLEX slots, the app applies the 30% penalty to all RB/WR/TE candidates even though they'd fill a real lineup spot. This undervalues good RB/WR/TE players when FLEX slots are open.

**Recommended improvements:**
- Track FLEX slots as fillable positions in the need calculation.
- When RB/WR/TE starter slots are full but FLEX is open, apply the need boost (not the filled penalty) to eligible players.

### 7. No Test Suite

**Current behavior:** There are no automated tests.

**Why it matters:** The scoring, VOR, replacement level, and need calculations are the core of the app. Without tests, refactoring or adding features risks silently breaking the ranking logic.

**Recommended improvements:**
- Add unit tests for `scoring.py` (verify point calculations against known examples).
- Add unit tests for `projections.py` (verify replacement levels with a small known player set).
- Add integration tests for `suggest.py` (verify that need boosts and penalties apply correctly).
- Test the importers with fixture CSV/HTML files.

### 8. No Weather, Matchup, or Environmental Factors

**Current behavior:** None of these are considered.

**Why it matters:** For the stated goal of predicting output based on factors beyond raw stats, weather (outdoor stadium, cold/rain games), altitude (Denver), and divisional matchup history all have measurable effects on player output.

**Recommended improvements:**
- This is a stretch goal — start with the historical trend analysis (#2) and schedule awareness (#4) before layering on environmental data.
- If pursued, integrate a weather API for game-day conditions and adjust projections for outdoor games in late-season cold weather.

### 9. Pick Resolution Could Be More Robust

**Current behavior:** Player matching uses substring search and prefers skill positions when ambiguous. There's no fuzzy matching for misspellings.

**Recommended improvements:**
- Add fuzzy string matching (e.g., Levenshtein distance) so "Mcafrey" still matches "Christian McCaffrey."
- Support player ID-based picking as an alternative to name-based.

### 10. No Undo History or Draft Log Export

**Current behavior:** Only the last pick can be undone. There's no exportable draft log.

**Recommended improvements:**
- Support multi-step undo.
- Add a `log` command that prints the full pick history with round/pick numbers.
- Support exporting the draft log to CSV for post-draft analysis.
