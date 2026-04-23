Fantasy Football Draft Assistant (UI-First)

Overview

- Offline-first Python desktop app that ranks players using Value Over Replacement (VOR) based on your league settings (teams, roster sizes, and scoring).
- Tracks live draft picks and your roster with real-time suggestions in a local UI.
- Pluggable data providers with a built-in Sleeper provider stub and a local JSON projections loader (sample provided).

Quick Start

1) Create a Python 3.10+ environment.
2) Run: `python -m draft_assistant` (or `python -m draft_assistant.cli`) to open the desktop UI.
3) In the UI, click `Seed Sample Data` if you need starter projections.
4) Use `Settings` to set teams, roster slots, and scoring.
5) Use `League Pick`, `My Pick`, and `Undo` to track the draft; suggestions update automatically.

CLI Commands (Optional)

- `python -m draft_assistant.cli ui` — launch desktop UI explicitly.
- `python -m draft_assistant.cli --profile home ui` — launch UI on a specific league profile.
- `python -m draft_assistant.cli init` — generate config and sample state.
- `python -m draft_assistant.cli fetch` — fetch player data (providers configurable; local sample by default).
- `python -m draft_assistant.cli suggest [-n 12] [--draft-slot 5] [--sims 250]` — show draft-aware suggestions in terminal.
- `python -m draft_assistant.cli pick "Bijan Robinson"` — record a league pick.
- `python -m draft_assistant.cli mypick "CeeDee Lamb"` — record your pick.
- `python -m draft_assistant.cli roster` — show your roster and needs.
- `python -m draft_assistant.cli undo` — undo last pick.
- `python -m draft_assistant.cli save` / `load` — persist or restore draft state.
- `python -m draft_assistant.cli import-fpros --offense <offense.csv> --k <k.csv> --dst <dst.csv>` — import FantasyPros CSVs into `data/projections.json`.
- `python -m draft_assistant.cli pull-fftoday --season 2024 --out data/projections.json --csv data/projections.csv` — fetch free FFToday projections (experimental) and export JSON/CSV.
- `python -m draft_assistant.cli pull-free-data --season 2026 --stats-season 2025 --out data/projections.json --csv data/projections.csv` — merge free public sources into the app data file.
- Add `--profile <name>` to any CLI command to target a specific league profile.

Multi-League Profiles

- The app now supports multiple league profiles in one install.
- In the UI: use `League` dropdown + `New League` + `Switch`.
- On CLI: `--profile <name>` switches league settings and draft state for that command.
- Default profile uses root files (`league.config.yaml`, `draft_state.json`, `data/projections.json`).
- Named profile settings and picks are stored under `.draft_assistant_profiles/<profile>/`; all profiles share the populated `data/projections.json` player pool.

Configuration

Edit league settings in the UI `Settings` dialog, or edit profile config files directly:

- teams: number of teams in your league.
- roster: starters per position (QB/RB/WR/TE/FLEX/K/DST/BN etc.).
- scoring: points per stat (supports PPR and typical scoring settings).
- draft: snake draft slot plus Monte Carlo settings (`slot`, `monte_carlo_sims`, `adp_noise`).
- provider: where to fetch data from (`local_json` by default; `sleeper` stub included).

Draft-Aware VOR

- Suggestions now use a dynamic roster optimizer, not a fixed lineup assumption.
- The optimizer fills required roster slots from your league settings, then assigns RB/WR/TE players into however many FLEX slots your league uses.
- Score combines lineup surplus over replacement, positional VOR, ADP-based Monte Carlo scarcity before your next snake-draft pick, and a small bye-week tiebreaker.
- Configure your snake slot and simulation count in the UI Settings dialog or with CLI overrides such as `--draft-slot 5 --sims 250`.

Data Providers

- Local JSON: loads from `data/projections.json` (provided sample for demo).
- Sleeper (stub): fetch players and ADP; you can extend to include projections you trust.

Pulling Free Data Sources

- Run: `python -m draft_assistant.cli pull-free-data --season 2026 --stats-season 2025 --out data/projections.json --csv data/projections.csv`
- Sources pulled automatically when available:
  - Sleeper players and season projections.
  - Fantasy Football Calculator ADP, matched to your league team count and scoring format.
  - nflverse players metadata and prior-season regular stats from GitHub release CSVs.
  - FFToday projections, unless `--skip-fftoday` is passed.
- Optional: pass `--espn-league-id <id>` to attempt ESPN's undocumented public league endpoint.
- Manual/free-with-export sources such as FantasyPros CSVs are still handled by `import-fpros`.

Importing Projections (FantasyPros)

- Download CSVs from FantasyPros (ensure you have rights/subscription if required):
  - Offense (QB/RB/WR/TE): visit position pages under Projections and use the CSV export.
  - Kicker and DST: export their respective projection CSVs as well.
- Run importer:
  - `python -m draft_assistant.cli import-fpros --offense path/to/offense.csv --k path/to/k.csv --dst path/to/dst.csv --out data/projections.json`
- Notes:
  - Offense maps PASS/RUSH/REC stats; missing 2pt stats default to 0.
  - K maps PAT and FG by range; misses computed only if attempts are available.
  - DST maps sacks/INT/FR/safeties; TDs are treated as INT return TDs if only a total is provided. Points/Yards-allowed tier projections are typically not provided and are left as 0.

Notes

- Network fetches are optional. The UI and CLI both work offline with local data.
- VOR baseline accounts for league size, roster slots, and FLEX allocation across RB/WR/TE.
- State persists to `draft_state.json` in the working directory.

Extending

- Add a provider in `draft_assistant/providers/` implementing `Provider`.
- Plug it in via `league.config.yaml` (provider.type and options).
Pulling Free Projections (FFToday)

- Run: `python -m draft_assistant.cli pull-fftoday --season 2024 --out data/projections.json --csv data/projections.csv`
- Notes:
  - This uses basic HTML parsing and may break if site structure changes.
  - The DST points/yards-allowed tiers are not provided and remain 0.
  - Use responsibly per the website’s terms.
