# Updating without losing leagues

The installer replaces the program. Your league data belongs to a separate
per-user folder and is never bundled into a release:

- Windows: `%LOCALAPPDATA%\DraftAssistant`
- macOS: `~/Library/Application Support/DraftAssistant`
- Source checkout: the working directory, unless `DRAFT_ASSISTANT_HOME` is set.

Starting with 0.6.0, `workspace-state.json` contains all leagues, scoring, draft
order, picks and roster ownership, keeper metadata, and engine preferences.
Player projections and news remain in `data/`; existing configuration and
provider files keep their established paths. The installer keeps its original
application ID and does not delete this data directory, including on uninstall.

## Routine updates from 0.6.0 onward

1. Wait until saving finishes. If the app shows a save error, retry or export a
   backup before closing.
2. Optionally choose **Backups → Export all leagues** for a portable copy.
3. Close the app, then run the newer installer over the existing installation.
4. Open the app. The same leagues and rosters load for draft or waiver-wire use.

Every write is atomic and checked against the current revision. Separate app
windows cannot silently overwrite a newer save. The first migration and ten
recent prior versions remain in `backups/`. A future or unreadable schema stops
loading instead of replacing it with defaults. To restore a corrupt disk file,
close the app, retain that file under a different name, and copy a known-good
`backups/workspace-state.<revision>.json` to `workspace-state.json`.

The native window waits for an active save before closing and stays open on a
save failure. If another window saved a newer revision, export your unsaved copy
and choose **Backups → Reload saved disk version** to resolve the conflict.

Session ESPN access cookies are deliberately absent from exports and disk league
state; re-enter them when needed. A league backup does not include the separately
refreshable player dataset or Yahoo authorization files.

## One-time upgrade from an older native desktop version

Versions through 0.5.0 stored the multi-league UI only in browser localStorage.
The native wrapper used a new address and private browser session on each
launch. Keeping the installer data directory alone therefore did not preserve
that UI state. **Do not close an old window containing the only saved league
until its backup is verified.**

An open older native app can be rescued locally with
`scripts/backup_running_app.py`. It temporarily adds a backup script to the
installed page, then the user refreshes the **same existing window** with Ctrl+R.
It reads only the app's league, pick, and engine-preference keys. A temporary
localhost receiver saves a verified JSON file under `backups/legacy-recovery/`
and creates `workspace-state.json` only when none exists. It never replaces an
existing workspace. The installed page is restored after success, timeout, or
interruption. No data leaves the computer.

Run from the source checkout, substituting the actual installed page and the
running app's exact localhost port:

```powershell
python scripts/backup_running_app.py --index "$env:LOCALAPPDATA\Programs\Draft Assistant\_internal\draft_assistant\web\static\index.html" --origin http://127.0.0.1:PORT --data-dir "$env:LOCALAPPDATA\DraftAssistant"
```

Confirm the expected `leagueCount` and `workspaceCreated: true` before replacing
the installed app. If only a recovery file was created, import it through the
new app's Backups panel before discarding the old session. An empty capture is
an error, never a successful migration.

For an older browser-mode installation, serve the new app at the same localhost
address once to migrate its existing localStorage. Thereafter the disk workspace
loads independently of the address or browser profile. Keep the same data folder
when changing how you launch the app.
