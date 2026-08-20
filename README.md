# Fantasy Football Draft Assistant

A local-first Python draft assistant with terminal, Tkinter, browser, and pywebview interfaces; multi-league profiles; rest-of-draft simulation; news-aware weekly/ROS waiver scanning; auction values; and public-data ingestion.

---

## Quick Start

**Requirements:** Python 3.10+. Core app has no external dependencies.

```bash
# Editable install with the `draft-assistant` command
python -m pip install -e .

# Launch terminal UI (default, works everywhere)
python -m draft_assistant

# Launch web UI (browser-based — recommended for live drafts)
python -m draft_assistant web

# Launch Tkinter desktop UI
python -m draft_assistant ui

# Optional native webview shell
python -m pip install -e ".[desktop]"
python -m draft_assistant app

# Target a specific league profile
python -m draft_assistant --profile home draft
```

The terminal UI walks you through league setup on first run (teams, scoring format, roster, draft position), seeds sample player data, and drops you into a live draft board with commands like `pick <name>`, `my <name>`, `undo`, `log`, `auction`.

The web UI starts a loopback-only HTTP server (default `http://127.0.0.1:8080`) and opens your browser. Add `--port N` or `--no-open` to customize. It is organised around the league:

- **Leagues** — every league you have set up, with a card each.
- **League hub** — one league's home. From here you choose a destination and edit settings, sync rosters, or pull data.
- **Draft room** — draft day: the impact/VORP board, server-backed rollout recommendations, player availability and opportunity signals, opponent-run and value-at-risk alerts, the pick ticker, live Sleeper draft sync, and auction values.
- **Waiver wire** — the in-season screen: free agents ranked by what they add to your actual starting lineup, with the drop each add implies, on either a **this-week** or **rest-of-season** horizon. News signals (injury, depth-chart, snap-share, trending adds) feed both. Completely separate from the draft room.


The desktop UI opens a Tkinter window with a draft board, roster panel, and a league switcher.

---

## Installable Builds

Ship a real installer that bundles its own Python, offline web assets, player data, and license notices — testers install nothing else.

```powershell
# Windows -> dist\installers\DraftAssistant-Setup-<version>.exe
powershell -ExecutionPolicy Bypass -File packaging\windows\build.ps1
```

```bash
# macOS -> dist/installers/DraftAssistant-<version>-<arch>.dmg
./packaging/macos/build.sh
```

Or push a tag and let CI build both: `git tag v0.4.0 && git push origin v0.4.0`.

Both builds run the projection-quality release gate first, so a degraded
single-source or position-incomplete board cannot be shipped accidentally, and
then smoke-test the packaged app before wrapping it.

The packaged app opens in a native window (falling back to the browser if the
system webview is unavailable) and keeps config, draft state and the player
board in a per-user data directory rather than next to the executable, so it
survives being installed somewhere read-only.

- [docs/DISTRIBUTION.md](docs/DISTRIBUTION.md) — building, CI, and code signing
- [docs/FOR_TESTERS.md](docs/FOR_TESTERS.md) — send this to whoever is testing
- [docs/MAC_APP_STORE.md](docs/MAC_APP_STORE.md) — what an App Store release would take

---

## How Suggestions Are Scored

`draft_assistant/rollout.py` is the single recommendation engine for every UI. For each leading candidate it simulates the rest of the snake draft using noisy ADP opponent orders and the exact league teams, draft slot, roster shape, typed flex eligibility, and scoring rules. Your simulated picks maximize the final legal roster; required kicker and defense slots are enforced.

The displayed **impact** is:

```text
expected final-roster season points after drafting this player
minus expected final-roster season points under the default greedy pick
minus the small configured bye-week tiebreaker
```

This captures opportunity cost: a lower-scoring player can be the better pick when their position will collapse before your later selections. Candidates are never reserved through intervening opponent picks, and recommendations are computed only on your actual turn. The board also shows league-scored projection, VORP, immediate lineup gain, and simulated availability at the following pick.

Before scoring, published stat projections can be blended with recent history using position-specific weights, year-over-year age curves, and a team-change adjustment. Imported ESPN, Sleeper, and Yahoo scoring maps are retained in full, including kicker, defense, and uncommon categories.

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
| `collect-all` | The free pull plus `nfl_data_py` and Sleeper's stats archive (superset of `pull-free-data`) |
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

## Connecting a Platform League (web UI)

The league editor can import a real league instead of typing one in — teams, roster slots, scoring, and your league-mates' names.

| Platform | What it needs | What you get |
|---|---|---|
| **Sleeper** | Your username (or a league id) — no login | Settings + names **in draft-slot order** with your own seat, plus **live draft sync** |
| ESPN | The league id, league must be public | Settings + names in platform order |
| Yahoo | A free developer app + OAuth authorization | Settings + names in platform order |

**Sleeper live draft sync.** Sleeper publishes the draft itself, so the board can mirror it as it happens: import the league, then hit **Go Live** in the draft room. It polls every 5s and replaces the board's picks with the real ones — actual pick numbers and seats, so recommendations track the true state of the draft without anyone typing picks in. Picks for players missing from your board are kept as placeholders so the clock stays right, and it stops on its own when the draft completes.

Outside of a draft, **Sync** on a league card pulls current rosters (all three platforms) — useful in-season for the free-agent scan.

The Free Agent Finder ranks the same available pool two ways: **This Week**
uses weekly projections plus hard availability statuses, while **Rest of Season**
subtracts current-season production from the season baseline. Sleeper trends,
depth charts, and snap context explain movement and break ties; they never apply
opaque projection multipliers. Dynamic context is cached separately from the
projection board, so repeated refreshes cannot compound an adjustment.

---

## Data Sources

### Option 1: `pull-free-data` (no extra dependencies)

Reads directly from nflverse GitHub release CSVs, Sleeper API, and Fantasy Football Calculator.

```bash
python -m draft_assistant pull-free-data --season 2026 --stats-season 2025
```

### Option 2: `collect-all` (a superset of Option 1)

Runs the free pull above and *then* layers `nfl_data_py` (age, draft capital, injury
history, derived bye weeks) and Sleeper's season-stats archive on top. Enrichment only
ever adds, so this path can never return a smaller board than the free pull — it takes
the same `--stats-season`, `--skip-fftoday`, and `--espn-league-id` options.

```bash
# Use Python 3.10 or 3.11 for this optional collector.
pip install -r requirements-data.txt
python -m draft_assistant collect-all --season 2026 --scoring ppr --teams 12
```

`nfl_data_py` is optional: without it, `collect-all` still returns the full free-source
board and simply reports the enrichment step as skipped.

Both paths populate players with projections, ADP, age, experience, historical stats, bye week, provenance, and team when their upstream sources provide them. `collect-all` fills injury history, previous team, and draft capital more deeply. Free-data pulls report a warning when only one projection source succeeded; packaging and CI enforce stronger bundled-board coverage thresholds.

### Other importers

- `import-fpros --offense offense.csv --k k.csv --dst dst.csv` — FantasyPros CSV exports
- `pull-fftoday --season 2024` — FFToday HTML scraping (experimental)
- `consensus --sources a.json b.json --method median` — merge multiple projection files

---

## Backtesting

Install the optional analytics dependencies, then evaluate archived preseason
sources against completed seasons:

```bash
python -m pip install -e ".[backtest]"
python -m draft_assistant.backtest
```

Evaluation populations are selected from preseason ranks rather than hindsight
top scorers, cache files include the full scoring configuration, and blend
calibration prints leave-one-season-out validation. Historical Sleeper numbers
are marked contaminated because that endpoint reflects in-season updates; they
are shown for reference, not treated as a clean preseason source.

---

## Configuration

Edit `league.config.yaml` (or use the setup wizards):

```json
{
  "teams": 12,
  "roster": {"QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 2, "K": 1, "DST": 1, "BN": 7},
  "scoring": {"pass_yd": 0.04, "pass_td": 4, "rec": 0.5, "rec_yd": 0.1, ...},
  "draft": {"slot": 5, "rollout_sims": 48, "rollout_candidates": 16, "adp_noise": 8.0},
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
├── web/                   # Browser web UI (HTTP server + React frontend)
│   └── static/            # ui-kit, app shell, league hub, draft room, waiver wire
│   ├── server.py          # Stdlib HTTP server + JSON API
│   └── static/            # index.html, scoring engine, React components
├── profiles.py            # Multi-league profile management
├── config.py              # League config load/save
├── models.py              # Player, LeagueConfig, DraftState dataclasses
├── draft.py               # DraftTracker with fuzzy matching + multi-step undo
├── rollout.py             # Rest-of-draft Monte Carlo recommendation engine
├── draft_value.py         # Lineup optimizer, typed flex, snake-pick utilities
├── suggest.py             # Compatibility entry point for recommendations
├── projections.py         # VOR and replacement-level computation
├── scoring.py             # Fantasy points from stat projections
├── historical.py          # Age curves, trend blending, confidence scoring
├── auction.py             # Auction dollar values + budget tracker
├── free_agents.py         # Weekly + ROS waiver/free-agent recommendations
├── context.py             # Cached Sleeper/nflverse player update signals
├── update_checker.py      # Packaged-app GitHub Release notice
├── consensus.py           # Multi-source projection merging
├── fuzzy.py               # Levenshtein name matching
├── storage.py             # JSON persistence
├── data_quality.py        # Release gate for the bundled projection board
├── platform_sync.py       # Stable provider-id roster/draft synchronization
├── export.py              # CSV export
├── sample_data.py         # Built-in sample players
├── collectors/            # Richer data collectors (require nfl_data_py)
│   ├── nflverse.py
│   ├── ffc_adp.py
│   ├── sleeper_historical.py
│   └── combined.py
├── importers/             # CSV + HTML importers, no-dep collectors
│   ├── free_sources.py    # GitHub CSV + Sleeper + FFC + ESPN
│   ├── sleeper.py         # Sleeper league import + live draft sync
│   ├── yahoo.py           # Yahoo OAuth league import
│   ├── fantasypros.py
│   └── fftoday.py
└── providers/             # Runtime player sources
    ├── base.py
    └── sleeper.py

tests/                     # Unit and local HTTP integration tests
├── test_scoring.py
├── test_projections.py
├── test_suggest.py
├── test_historical.py
├── test_draft.py
├── test_draft_value.py    # Lineup optimization, snake picks
├── test_web_server.py     # Same-origin guard, request limits
├── test_profiles.py       # Profile system
├── test_fuzzy.py
├── test_auction.py
├── test_free_agents.py    # Free-agent add/drop recommendations
├── test_context.py        # Signal persistence, joins, expiry + adjustments
├── test_update_checker.py # Platform release selection + version checks
├── test_config.py         # Config robustness + round trip
├── test_storage.py        # Atomic persistence
├── test_free_sources.py   # Free-data collector field mapping
├── test_platform_sync.py  # Roster → pick matching
├── test_sleeper_league.py # Sleeper import, roster + live draft sync
├── test_nflverse_collector.py
└── test_combined_collector.py
```

---

## Running Tests

```bash
python -m unittest discover tests -v
```

The test suite covers scoring, VOR/replacement levels, typed flex, bye-week penalties, snake-pick math, rollout timing and roster completion, stable-id migration, imported scoring, dual-horizon free-agent add/drop recommendations, conservative availability rules, update checks, historical adjustments, platform sync, auction validation, collectors, atomic persistence, and the local API's origin/input controls.

---

## Notes

- Network fetches are optional. All UIs and the CLI work offline; React and Babel assets are vendored, hashed, and license-inventoried, and the UI makes no font/CDN request.
- Draft state persists to `draft_state.json` (or `.draft_assistant_profiles/<name>/draft_state.json` for non-default profiles).
- Draft picks persist stable provider ids. Older `name|POS` state is migrated automatically, and malformed state is preserved as a `.corrupt` backup before defaults are recovered.
- The web API binds to loopback, rejects cross-origin and non-JSON mutation requests, bounds expensive inputs, and limits concurrent data jobs.
- For Pro Football Reference and sites that block scraping, prefer the `collect-all` + `pull-free-data` paths which use public API endpoints and GitHub-hosted datasets.
- Project-original code is all-rights-reserved; vendored component terms are listed in `THIRD_PARTY_NOTICES.md`.
