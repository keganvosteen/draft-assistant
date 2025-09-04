Fantasy Football Draft Assistant (CLI)

Overview

- Offline-first Python CLI that ranks players using Value Over Replacement (VOR) based on your league settings (teams, roster sizes, and scoring).
- Tracks live draft picks and your roster; updates suggestions in real time.
- Pluggable data providers with a built-in Sleeper provider stub and a local JSON projections loader (sample provided).

Quick Start

1) Create a Python 3.10+ environment.
2) Run: `python -m draft_assistant.cli init` to generate `league.config.yaml` and seed local sample data.
3) Run: `python -m draft_assistant.cli suggest` to view top suggested picks based on sample data.
4) Use `pick` / `mypick` to track your draft; suggestions update automatically.

Key Commands

- `python -m draft_assistant.cli init` — generate config and sample state.
- `python -m draft_assistant.cli fetch` — fetch player data (providers configurable; local sample by default).
- `python -m draft_assistant.cli suggest [-n 12]` — show top suggestions.
- `python -m draft_assistant.cli pick "Bijan Robinson"` — record a league pick.
- `python -m draft_assistant.cli mypick "CeeDee Lamb"` — record your pick.
- `python -m draft_assistant.cli roster` — show your roster and needs.
- `python -m draft_assistant.cli undo` — undo last pick.
- `python -m draft_assistant.cli save` / `load` — persist or restore draft state.
- `python -m draft_assistant.cli import-fpros --offense <offense.csv> --k <k.csv> --dst <dst.csv>` — import FantasyPros CSVs into `data/projections.json`.
- `python -m draft_assistant.cli pull-fftoday --season 2024 --out data/projections.json --csv data/projections.csv` — fetch free FFToday projections (experimental) and export JSON/CSV.

Configuration

Edit `league.config.yaml` to match your league:

- teams: number of teams in your league.
- roster: starters per position (QB/RB/WR/TE/FLEX/K/DST/BN etc.).
- scoring: points per stat (supports PPR and typical scoring settings).
- provider: where to fetch data from (`local_json` by default; `sleeper` stub included).

Data Providers

- Local JSON: loads from `data/projections.json` (provided sample for demo).
- Sleeper (stub): fetch players and ADP; you can extend to include projections you trust.

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

- Network fetches are optional. The CLI works offline with the sample data.
- VOR baseline accounts for FLEX allocation across RB/WR/TE.
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
