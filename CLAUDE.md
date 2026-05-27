# Fantasy Football Draft Assistant

## Local Development

- **Owner's local path (Windows):** `D:\Vibe Projects\GitHub\draft-assistant`
- **Cloud dev environment:** `/home/user/draft-assistant`
- **Primary branch:** `claude/fantasy-draft-recommender-NxX9l`

## Running

- Terminal UI: `python -m draft_assistant`
- Desktop UI: `python -m draft_assistant ui`
- Web UI: `python -m draft_assistant web`
- Tests: `python -m unittest discover tests -v`

## Key Details

- Python 3.10+, no external dependencies for core app
- 98 tests in `tests/`
- Web UI uses React via CDN (no build step), Python stdlib HTTP server
- Player data lives in `data/projections.json`
- League config in `league.config.yaml`
- Named profiles under `.draft_assistant_profiles/<name>/`
