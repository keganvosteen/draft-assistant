# Fantasy Football Draft Assistant

## Shell

- **Default to the PowerShell tool for all commands.** The Bash tool often fails on this Windows machine — do not use it unless the owner says otherwise.

## Local Development

- **Owner's local path (Windows):** `C:\Users\kegan\Documents\draft-assistant`
- **Cloud dev environment:** `/home/user/draft-assistant`
- **Primary branch:** `claude/fantasy-draft-recommender-NxX9l`

## Running

- Terminal UI: `python -m draft_assistant`
- Desktop UI (Tkinter): `python -m draft_assistant ui`
- Web UI (browser): `python -m draft_assistant web`
- Desktop App (pywebview): `python -m draft_assistant app` (requires `pip install -r requirements-desktop.txt`)
- Tests: `python -m unittest discover tests -v`

## Key Details

- Python 3.10+, no external dependencies for core app
- 212 tests in `tests/`
- Web UI uses vendored React + in-browser Babel (no build step), Python stdlib HTTP server. Works offline apart from the optional Google Fonts link in `index.html`, which falls back to system fonts.
- Player data lives in `data/projections.json` (tracked)
- League config in `league.config.yaml`
- Named profiles under `.draft_assistant_profiles/<name>/` — gitignored, as is `draft_state.json`

## Packaging

- **One spec, both platforms:** `packaging/DraftAssistant.spec` drives the Windows installer (`packaging/windows/build.ps1` → Inno Setup) and the macOS `.dmg` (`packaging/macos/build.sh`). CI builds all three artifacts via `.github/workflows/release.yml`. Version comes from `draft_assistant.__version__` — bump it there only.
- **Paths are the load-bearing part.** `paths.py::resolve()` returns the plain relative path in a source checkout and an absolute per-user path (`%LOCALAPPDATA%\DraftAssistant`, `~/Library/Application Support/DraftAssistant`) when frozen. An installed app cannot write beside its executable, so **anything that persists state must route through `resolve()`** — hardcoding a relative path works in dev and silently breaks the installed build. `DRAFT_ASSISTANT_HOME` overrides it.
- Tests assert the dev-mode paths verbatim (`tests/test_profiles.py`) and chdir into temp dirs, so `resolve()` must stay a no-op unless frozen.
- Both build scripts smoke-test the bundle (launch it, hit `/api/state`, check seeding) before packaging. That is what catches a missing `--add-data` file or hidden import.
- The packaged app ships the **web UI only** — `tkinter` is deliberately excluded from the bundle, so `draft-assistant ui` stays a source-checkout feature.

## Platform leagues

- **Import + roster sync:** ESPN (`importers/free_sources.py`, public leagues), Yahoo (`importers/yahoo.py`, OAuth), Sleeper (`importers/sleeper.py`, public API — no auth). All three land on `POST /api/sync-league`, which maps provider rosters to board players via `platform_sync.py`.
- **Matching** is by provider id first (`metadata.espn_id` / `metadata.sleeper_id`), then name+position fuzzy. Sleeper rosters carry only ids, which is why id-only matching must keep working — don't reintroduce a name/position guard before the provider lookup in `_PlayerMatcher.match`.
- **Sleeper live draft sync** (`POST /api/sleeper/draft`) is the only real-draft feed: Sleeper publishes actual pick numbers and seats, so `synced_draft_to_picks` returns true picks and `draft-screen.jsx` polls it every 5s behind the "Go Live" button. **Every pick must survive to the output list.** The UI reads the next pick as `picks.length + 1`, so dropping one shifts the clock for the rest of the draft. Both an unmatched player *and* a second pick that resolves to an already-taken board player become placeholders — never `continue`.

## Recommendation engine

- **One engine, all UIs:** `draft_assistant/rollout.py` (`rollout_values`) ranks the board by a rest-of-draft Monte Carlo rollout — each player's score is the expected effect of drafting them now on your **total season points**, accounting for who survives to your later picks (positional opportunity cost). `suggest.py` delegates to it.
- **Web/desktop app** call it over HTTP via **`POST /api/suggest`** (`web/server.py::_handle_suggest`); `draft-screen.jsx` renders the result. The old client-side `scoring-engine.js` is retired (not loaded); `opponent-model.js` is kept for the Opponents panel only.
- Servers are `ThreadingHTTPServer` (the rollout takes ~1.5s; a single-threaded server froze the UI).
- Only the leading `rollout_candidates` players (default 16) get a full rollout. Keep the sim pool decoupled from `top_n` — tying them together made every extra board row cost a full set of simulations.
- The remaining requested rows come back with `simulated: false` and **`impact: null`**, and the board shows them as `—`. Don't be tempted to surface the prelim score there instead: a simulated impact compares two *completed* rosters, while a prelim row only knows what the player adds to the roster as it stands, so the two differ by roughly the value of every remaining pick (~1800 pts in a 17-round league). There is no cheap rescaling — closing that gap is what the simulation does.
- Everything is config-driven (teams/roster/scoring per league). Tunables live in `config.draft`: `rollout_sims`, `rollout_candidates`, `adp_noise`.
