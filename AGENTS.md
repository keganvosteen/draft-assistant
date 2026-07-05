# Fantasy Football Draft Assistant

## Local Development

- **Owner's local path (Windows):** `C:\Users\kegan\Documents\draft-assistant`
- **Cloud dev environment:** `/home/user/draft-assistant`
- **Primary branch:** `Codex/fantasy-draft-recommender-NxX9l`

## Running

- Terminal UI: `python -m draft_assistant`
- Desktop UI (Tkinter): `python -m draft_assistant ui`
- Web UI (browser): `python -m draft_assistant web`
- Desktop App (pywebview): `python -m draft_assistant app` (requires `pip install -r requirements-desktop.txt`)
- Tests: `python -m unittest discover tests -v`

## Key Details

- Python 3.10+, no external dependencies for core app
- 139 tests in `tests/`
- Web UI uses vendored React + in-browser Babel (no build step, works offline), Python stdlib HTTP server
- Player data lives in `data/projections.json`
- League config in `league.config.yaml`
- Named profiles under `.draft_assistant_profiles/<name>/`

## Recommendation engine

- **One engine, all UIs:** `draft_assistant/rollout.py` (`rollout_values`) ranks the board by a rest-of-draft Monte Carlo rollout — each player's score is the expected effect of drafting them now on your **total season points**, accounting for who survives to your later picks (positional opportunity cost). `suggest.py` delegates to it.
- **Web/desktop app** call it over HTTP via **`POST /api/suggest`** (`web/server.py::_handle_suggest`); `draft-screen.jsx` renders the result. The old client-side `scoring-engine.js` is retired (not loaded); `opponent-model.js` is kept for the Opponents panel only.
- Servers are `ThreadingHTTPServer` (the rollout takes ~1.5–2s; a single-threaded server froze the UI).
- Everything is config-driven (teams/roster/scoring per league). Tunables live in `config.draft`: `rollout_sims`, `rollout_candidates`, `adp_noise`.
