# Fantasy Football Draft Assistant

## Shell

- **Default to the PowerShell tool for all commands.** The Bash tool often fails on this Windows machine — do not use it unless the owner says otherwise.

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
- Web UI uses hashed, license-inventoried vendored React + in-browser Babel (no build step), with no runtime CDN dependency.
- Player data lives in `data/projections.json` (tracked)
- League config in `league.config.json`
- Named profiles under `.draft_assistant_profiles/<name>/` — gitignored, as is `draft_state.json`

## Packaging

- **One spec, both platforms:** `packaging/DraftAssistant.spec` drives the Windows installer (`packaging/windows/build.ps1` → Inno Setup) and the macOS `.dmg` (`packaging/macos/build.sh`). CI builds all three artifacts via `.github/workflows/release.yml`. Version comes from `draft_assistant.__version__` — bump it there only.
- **Paths are the load-bearing part.** `paths.py::resolve()` returns the plain relative path in a source checkout and an absolute per-user path (`%LOCALAPPDATA%\DraftAssistant`, `~/Library/Application Support/DraftAssistant`) when frozen. An installed app cannot write beside its executable, so **anything that persists state must route through `resolve()`** — hardcoding a relative path works in dev and silently breaks the installed build. `DRAFT_ASSISTANT_HOME` overrides it.
- Tests assert the dev-mode paths verbatim (`tests/test_profiles.py`) and chdir into temp dirs, so `resolve()` must stay a no-op unless frozen.
- Both build scripts smoke-test the bundle (launch it, hit `/api/state`, check seeding) before packaging. That is what catches a missing `--add-data` file or hidden import.
- The packaged app ships the **web UI only** — `tkinter` is deliberately excluded from the bundle, so `draft-assistant ui` stays a source-checkout feature.

## Web UI structure

- **Navigation is league-first:** leagues list → **league hub** → either the **draft room** or the **waiver wire**. The two destinations are siblings, never nested: the draft room has no waiver-wire entry point and the waiver wire has no draft controls. `App` in `app-components.jsx` owns the route (`{screen, leagueId}`); there is no router.
- **Script load order matters** (`static/index.html`). Each Babel script gets its own scope, so every file publishes what later files need with `Object.assign(window, …)`. `ui-kit.jsx` is first and owns the design tokens (`T`) plus every shared primitive — `Btn`, `Badge`, `PosBadge`, `Field`/`Input`/`Select`/`SegmentedControl`, `Modal`, `Drawer`, `Menu`, `AppBar`, `EmptyState`, `Note`, `toast`, `confirmDialog`, `useLayout`. Build new UI out of those; don't re-derive a one-off button.
- `static/styles.css` owns what inline styles cannot: the font stack, `:focus-visible` rings, hover/active states, scrollbars, animations, tables, and the menu/toast/dialog CSS. Its custom properties and `T` are mirrors of each other — change both together.
- **No `window.confirm`/`alert`.** Destructive actions go through `confirmDialog(...)` (a promise of a boolean) and outcomes report through `toast(msg, 'ok'|'error'|'info')`.
- `useLayout()` is the single breakpoint vocabulary (`isMobile` < 760, `isTablet`, `isDesktop` ≥ 1140). The draft room's phone header only fits four controls — panels move into the More menu there.
- **News context in the UI:** `/api/players` and `/api/suggest` attach `availability` and `signals` per player, and `/api/free-agents` returns `weeklyRecommendations` + `rosRecommendations` with `points`, `urgency`, and `weeklyProjectionOrigin`. Render availability through `AvailabilityChip` (it abbreviates the feed's spelled-out statuses) and always filter signal lists through `playerNewsSignals()` — raw lists contain `source_updated` entries, which are bookkeeping about the feed and say nothing about the player.
- **A player with no NFL team is the load-bearing "cannot score" signal.** Sleeper reports a released veteran as `status: "Active"` with `injury_status: "Questionable"` and **`team: null`** — status alone cannot tell them apart from a healthy starter, which is how Joe Mixon and Tyreek Hill stayed draftable months after leaving their rosters. `_refresh_sleeper_players` turns a falsy `team` into a `roster_status: "Free Agent"` signal (except `DEF`/`DST`, which legitimately have none); `"free agent"` was already in `INELIGIBLE_ROSTER_STATUSES`, so that one emitter is what makes `is_candidate_eligible` drop them. Never give `roster_status` an `expires` — Mixon's only flag was a 48h injury designation, and once it lapsed he looked perfectly healthy.
- **The eligibility gate fails open**, so absence of signals means eligible. That is backwards for someone out of the league, who generates no news at all — which is why the draft room now shows `contextStale`/`contextFailedSources` from `/api/suggest` and the startup refresh reports failures through `toast` instead of swallowing them.
- **A stale history is evidence, not a gap.** `historical.py::history_recency_factor` discounts a player whose stats stop before the last completed season, shifting the blend toward the published projection. Don't try to fix this inside `_historical_trend`: it returns a *weighted average*, so scaling every season's weight cancels out and changes nothing.
- `rosterTotal()` (in `shared-utils.js`) is the draftable roster size: it skips `IR`, which is a roster slot but never a draft round. Counting it inflated "N slots" and drew a phantom extra round on the pick ticker.
- **A rejection that replies before reading the body must still drain it.** The server is HTTP/1.0, so it closes after every response — and closing a socket with received-but-unread bytes buffered is an *abortive* close on Windows. The RST makes the client discard the reply it had not read yet, so the 403/413/415 answers went missing on ~3% of requests and made the suite intermittently red. `DraftAPIHandler.finish` drains first (`_linger_close`), gated on `_body_drained`, which only `_read_body` sets. Any new early rejection added ahead of `_read_body` inherits that for free — but don't "simplify" it by draining the claimed `Content-Length`, which is exactly the unbounded allocation the 413 check exists to prevent. `TestEarlyRejectionsCloseCleanly` loops each path 100× because one request usually passes even when this is broken.

## Platform leagues

- **Import + roster sync:** ESPN (`importers/free_sources.py`, public leagues), Yahoo (`importers/yahoo.py`, OAuth), Sleeper (`importers/sleeper.py`, public API — no auth). All three land on `POST /api/sync-league`, which maps provider rosters to board players via `platform_sync.py`.
- **Matching** is by stable `Player.id` or provider metadata first, then name+position fuzzy. Sleeper rosters carry only ids, which is why id-only matching must keep working — don't reintroduce a name/position guard before the provider lookup in `_PlayerMatcher.match`.
- **Sleeper live draft sync** (`POST /api/sleeper/draft`) is the only real-draft feed: Sleeper publishes actual pick numbers and seats, so `synced_draft_to_picks` returns true picks and `draft-screen.jsx` polls it every 5s behind the "Go Live" button. **Every pick must survive to the output list.** The UI reads the next pick as `picks.length + 1`, so dropping one shifts the clock for the rest of the draft. Both an unmatched player *and* a second pick that resolves to an already-taken board player become placeholders — never `continue`.

## Data pulls

- **Full Collect is a superset of Free Sources, not an alternative.** `collectors/combined.py::collect_all_result` runs `pull_free_data` first — that is the player pool — then `_absorb`s `nfl_data_py` and Sleeper's season-stats archive onto it. It used to be a separate, narrower pipeline (nflverse rosters ∪ Sleeper only), which is how "Full" came back ~450 players *smaller* than "Free" on the same board. Enrichment must only ever add: never rebuild the pool from an enrichment source.
- Both `/api/pull-free-data` and `/api/collect-all` take the same request body and both must route their save through `update_players` + `merge_historical_into`. Calling `save_players` directly drops every stats season an earlier pull banked — the CLI did exactly that until `cmd_pull_free_data` was fixed, silently replacing a 2023/24/25 board with 2025 only. An explicit `--out` is an export and still writes verbatim.
- **ESPN needs no league id.** `_espn_player_url` falls back to `leaguedefaults/3`; a league only decides how stats are *scored*, so the raw `statSourceId=1` lines are identical either way. That is also what makes ESPN gradeable — a personal league 401s for seasons before it existed, the default reaches back to 2019 (2023 excepted: ESPN serves a ~86-player stub, see `backtest.ESPN_SPARSE_SEASONS`).
- **`SOURCE_WEIGHTS` is earned, not assumed.** `backtest.calibrate_source_weights` blends stat lines across six seasons and three scorings, compares only players *both* sources projected, and leave-one-season-out validates against an even split. Only RB and TE justified a tilt; QB and WR got *worse* when weighted. Don't read a raw source-vs-source table as a weighting argument — ESPN looks far better at WR there purely because it projects ~59 receivers to FFToday's ~38, and coverage already pays off by ESPN being in the pool. Sleeper stays neutral because its archive is revised in-season and cannot be graded at all.
- `_align_names` renames a near-miss enrichment record onto the pool's spelling before merging, so "Deandre Swift" enriches "D'Andre Swift" instead of landing beside it. Merge keys come from `free_sources._merge_key` (team code for DST, compact normalized name otherwise) — keep both sides on that one function.
- `free_sources._merge_player` is the single gap-fill merge. Anything added to `Player` needs a line there or it silently vanishes whenever two sources describe the same player.
- **Scraped sources share `importers/_scrape.py`** — the nested-table parser (fantasy sites still use layout tables, and a single-buffer parser scrambles them), the retrying fetch, and the number/name helpers. `fftoday.py` keeps a thin `_fetch_once` of its own purely so tests can patch its fetcher; the retry itself lives in `_scrape`. Match columns by header text like `cbs.py` does where the site allows it — FFToday's fixed offsets exist only because it labels passing and rushing yards identically.
- **Only CBS was scrapeable, and that was checked, not assumed.** FantasyPros server-renders 10 players per position and serves the rest from `/api/`, `/ajax/`, `/json/` — all three robots-disallowed, so there is no permitted way to get a full table. NFL.com's projections page is a client-side app with zero `<tr>`. CBS ships whole tables on a robots-allowed path (it disallows `sortcol`/`sortdir`, so keep those out of the URL). Re-check robots before adding another site.
- A scraped source that returns **zero rows** has usually been redesigned rather than gone down, so `fetch_all_cbs` raises on an empty parse and the single-source warning names a site that returned nothing — silence is the failure mode to design against.

## Recommendation engine

- **One engine, all UIs:** `draft_assistant/rollout.py` (`rollout_values`) ranks the board by a rest-of-draft Monte Carlo rollout — each player's score is the expected effect of drafting them now on your **total season points**, accounting for who survives to your later picks (positional opportunity cost). `suggest.py` delegates to it.
- **Web/desktop app** call it over HTTP via **`POST /api/suggest`** (`web/server.py::_handle_suggest`); `draft-screen.jsx` renders the result. The old client-side `scoring-engine.js` is retired (not loaded); `opponent-model.js` is kept for the Opponents panel only.
- Servers are `ThreadingHTTPServer` (the rollout takes ~1.5s; a single-threaded server froze the UI).
- Only the leading `rollout_candidates` players (default 16) get a full rollout. Keep the sim pool decoupled from `top_n` — tying them together made every extra board row cost a full set of simulations.
- The remaining requested rows come back with `simulated: false` and **`impact: null`**, and the board shows them as `—`. Don't be tempted to surface the prelim score there instead: a simulated impact compares two *completed* rosters, while a prelim row only knows what the player adds to the roster as it stands, so the two differ by roughly the value of every remaining pick (~1800 pts in a 17-round league). There is no cheap rescaling — closing that gap is what the simulation does.
- **Replacement level is priced off *remaining* league demand.** `replacement_levels(..., occupied_players=...)` subtracts already-drafted players from league-wide starter slots; without it the baseline sank deeper every round and inflated VOR. Two consequences worth knowing: once a position's starter demand is satisfied its replacement becomes the best available player (so VOR stops discriminating there — normal from roughly round 8 on), and **every drafted player must reach that argument**. Callers resolve picks against the board, so an unmatched `name|POS` pick would be filtered out — `rollout.py::_unmatched_board_players` re-synthesizes those from `state.picks`, mirroring what `_unmatched_roster_players` does for your own roster.
- Everything is config-driven (teams/roster/scoring per league). Tunables live in `config.draft`: `rollout_sims`, `rollout_candidates`, `adp_noise`.
