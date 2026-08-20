# Fantasy Football Draft Assistant

## Local Development

- **Primary branch:** `master`

## Running

- Terminal UI: `python -m draft_assistant`
- Desktop UI (Tkinter): `python -m draft_assistant ui`
- Web UI (browser): `python -m draft_assistant web`
- Desktop App (pywebview): `python -m draft_assistant app` (requires `pip install -r requirements-desktop.txt`)
- Tests: `python -m unittest discover tests -v`

## Key Details

- Python 3.10+, no external dependencies for core app
- 240+ tests in `tests/`
- Web UI uses vendored React + in-browser Babel (no build step, works offline), Python stdlib HTTP server
- Player data lives in `data/projections.json`
- League config in `league.config.yaml`
- Named profiles under `.draft_assistant_profiles/<name>/`

## Web UI structure

- **Navigation is league-first:** leagues list → **league hub** → either the **draft room** or the **waiver wire**. The two destinations are siblings, never nested: the draft room has no waiver-wire entry point and the waiver wire has no draft controls. `App` in `app-components.jsx` owns the route (`{screen, leagueId}`); there is no router.
- **Script load order matters** (`static/index.html`). Each Babel script gets its own scope, so every file publishes what later files need with `Object.assign(window, …)`. `ui-kit.jsx` is first and owns the design tokens (`T`) plus every shared primitive — `Btn`, `Badge`, `PosBadge`, `Field`/`Input`/`Select`/`SegmentedControl`, `Modal`, `Drawer`, `Menu`, `AppBar`, `EmptyState`, `Note`, `toast`, `confirmDialog`, `useLayout`. Build new UI out of those; don't re-derive a one-off button.
- `static/styles.css` owns what inline styles cannot: the font stack, `:focus-visible` rings, hover/active states, scrollbars, animations, tables, and the menu/toast/dialog CSS. Its custom properties and `T` are mirrors of each other — change both together.
- **No `window.confirm`/`alert`.** Destructive actions go through `confirmDialog(...)` (a promise of a boolean) and outcomes report through `toast(msg, 'ok'|'error'|'info')`.
- `useLayout()` is the single breakpoint vocabulary (`isMobile` < 760, `isTablet`, `isDesktop` ≥ 1140). The draft room's phone header only fits four controls — panels move into the More menu there.
- **News context in the UI:** `/api/players` and `/api/suggest` attach `availability` and `signals` per player, and `/api/free-agents` returns `weeklyRecommendations` + `rosRecommendations` with `points`, `urgency`, and `weeklyProjectionOrigin`. Render availability through `AvailabilityChip` (it abbreviates the feed's spelled-out statuses) and always filter signal lists through `playerNewsSignals()` — raw lists contain `source_updated` entries, which are bookkeeping about the feed and say nothing about the player.
- `rosterTotal()` (in `shared-utils.js`) is the draftable roster size: it skips `IR`, which is a roster slot but never a draft round. Counting it inflated "N slots" and drew a phantom extra round on the pick ticker.

## Recommendation engine

- **One engine, all UIs:** `draft_assistant/rollout.py` (`rollout_values`) ranks the board by a rest-of-draft Monte Carlo rollout — each player's score is the expected effect of drafting them now on your **total season points**, accounting for who survives to your later picks (positional opportunity cost). `suggest.py` delegates to it.
- **Web/desktop app** call it over HTTP via **`POST /api/suggest`** (`web/server.py::_handle_suggest`); `draft-screen.jsx` renders the result. The old client-side `scoring-engine.js` is retired (not loaded); `opponent-model.js` is kept for the Opponents panel only.
- Servers are `ThreadingHTTPServer` (the rollout takes ~1.5–2s; a single-threaded server froze the UI).
- Everything is config-driven (teams/roster/scoring per league). Tunables live in `config.draft`: `rollout_sims`, `rollout_candidates`, `adp_noise`.
