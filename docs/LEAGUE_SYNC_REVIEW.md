# League import, draft sync, and code review

Reviewed against release 0.5.0 (`a43a2b6`) on 2026-09-06. Changes are on
`codex/league-draft-sync` in a separate worktree. The original checkout was an
older browser prototype; its existing player-data changes were preserved.

The screenshot's HTTP 401 was reproduced for the reported ESPN league in the
updated browser app. ESPN denies unauthenticated access to that league. The
import form now accepts the season, a league ID or ESPN URL, and optional
`espn_s2` / `SWID` cookies. Credentials are held only in page memory and are not
included in saved league objects or API responses. A successful authenticated
import of the user's private league still needs the user's ESPN session.

| Area | Change and practical effect |
| --- | --- |
| Multiple leagues | Separate IDs and access state, plus a startup race fix that prevents a delayed default league from replacing leagues added during loading. |
| ESPN order | Read `draftSettings.pickOrder`, preserve provider team IDs alongside names, and expose whether ESPN actually published an order. |
| Order refresh | Preserve the selected team and remap recorded ownership by stable team ID; require selection when identity cannot be resolved. |
| Live Sleeper | Poll every five seconds, prevent overlapping requests, abort on stop/unmount, retain failed-sync state, and stop on completion. |
| ESPN history | Read actual completed draft picks, including players since dropped from rosters, instead of manufacturing draft order from current rosters. |
| Draft integrity | Reject incomplete/duplicate pick-number sequences, preserve unknown players as placeholders, and retain traded-pick ownership. |
| Unsupported schedules | Explicitly flag nonstandard formats; pause recommendations when synced ownership reveals traded picks rather than applying an incorrect standard snake schedule. |
| Roster sync | Map by provider team IDs even when team names collide. Label roster snapshots so they cannot drive the draft clock. |
| Profile defaults | Deep-copy nested defaults so provider options cannot leak between fresh configurations. |
| Manual picks | Blank queries do nothing, retrying an exact already-drafted name cannot pick someone else, and closer fuzzy matches outrank less accurate matches. |
| Valuation | Select bench players by their actual bench contribution; exclude IR from auction draftable slots and budget reservation. |
| Packaging | Include CSS in wheels and check every asset referenced by the installed page, using isolated imports so the checkout cannot mask missing files. |

The test review removed one exactly duplicated ESPN test method, which Python
silently shadowed, and one weak FLEX test already covered by a stronger
regression. It replaced broad “positive number”/“returns something” assertions
with expected scoring and ordering outcomes. Unused helpers, constants, and
imports were removed. An AST scan of all 35 Python test files found no remaining
duplicate definitions.

Validation: 409 Python tests; JavaScript/JSX syntax; league identity and session
credential behavior; vendor integrity; projection quality; compileall; clean
diff checks; and a wheel installed in an isolated virtual environment with all
referenced browser assets present. Browser checks reproduced the private
league error, imported a public ESPN league as a second league without changing
the first, displayed the provider's published draft order, and synced all 220
completed picks (retaining 14 players absent from the current player board).
Completed/unsupported drafts suppress round recommendations and disable pick
controls while preserving player search and history review. Live-poll and
failure behavior are covered by provider-shaped fixtures; no live user draft or
private credentials were available for an end-to-end private-league test.

ESPN live picks remain a platform-integration limitation. Its league API does
not reliably expose in-progress draft picks. The app offers completed history
sync and the existing paste/manual workflow during the draft. See the
[ESPN API maintainer discussion](https://github.com/cwendt94/espn-api/issues/558)
and [Sleeper's documented draft endpoints](https://docs.sleeper.com/).

Update preservation was subsequently implemented for 0.6.0: a versioned disk
workspace, atomic saves, cross-process revision checks, retained backups,
portable export/restore, and persistent desktop browser storage. A one-time
rescue script supports existing sessions that can reload. Standard older native
windows disable reload, so their settings and draft state require recovery
while the old window stays open. See [the upgrade guide](UPGRADING.md).

Browser verification migrated the existing two-league test profile to disk,
opened a separate app address with the same two leagues and 220 picks, then
saved a league edit in one window and verified it after reloading the other.

The remaining improvements relevant to these leagues are:

1. **Keeper reservations.** Preserve keeper metadata now; explicit round costs
   and occupied draft slots still need scheduling support before the engine can
   model them. Pick trading, third-round reversal, and IDP are outside the user's
   requested scope.
2. **A separately tested ESPN live connector.** A user-authorized browser
   integration would need to read the distinct ESPN draft-room feed. Merely
   polling the completed-results endpoint cannot provide live tracking.

The source version is 0.6.0. Replacing a legacy native executable must wait for
a verified league backup; merging source changes does not replace that running app.
