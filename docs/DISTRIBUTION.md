# Building and distributing Draft Assistant

Two installable builds come out of one PyInstaller spec:

| Platform | Output | Built by |
| --- | --- | --- |
| Windows | `dist/installers/DraftAssistant-Setup-<version>.exe` | `packaging/windows/build.ps1` |
| macOS | `dist/installers/DraftAssistant-<version>-<arch>.dmg` | `packaging/macos/build.sh` |

Both bundle their own Python — testers install nothing else.

---

## Where an installed build keeps its data

This is the one thing that differs from running out of a checkout. An installed
app cannot write next to its executable (`C:\Program Files`, or a signed `.app`
bundle), so [`draft_assistant/paths.py`](../draft_assistant/paths.py) redirects
all mutable state:

| | Source checkout | Installed build |
| --- | --- | --- |
| Config, draft state, player board | current directory | `%LOCALAPPDATA%\DraftAssistant` (Windows) <br> `~/Library/Application Support/DraftAssistant` (macOS) |

On first run the app copies the bundled `data/projections.json` and
`league.config.yaml` into that directory. Upgrades never overwrite them, so a
reinstall keeps a draft in progress.

Set `DRAFT_ASSISTANT_HOME` to point any build at a different directory — that
is how the smoke tests get a clean slate.

---

## Building on Windows

```powershell
powershell -ExecutionPolicy Bypass -File packaging\windows\build.ps1
```

Needs Inno Setup 6:

```powershell
winget install -e --id JRSoftware.InnoSetup
```

Pass `-SkipInstaller` to build only the unpacked app in
`dist/pyinstaller/DraftAssistant` — faster when iterating.

The script creates `.venv-build`, installs PyInstaller and pywebview,
regenerates the icons, builds, and then **smoke-tests the result** by launching
it against a throwaway data directory and checking that it serves the UI. A
bundle missing a data file or a hidden import fails there rather than on a
tester's machine.

The installer is per-user by default (`%LOCALAPPDATA%\Programs`), so testers get
no UAC prompt. They can choose an all-users install if they want one.

## Building on macOS

```bash
chmod +x packaging/macos/build.sh packaging/macos/smoke_test.sh
./packaging/macos/build.sh
```

Same shape: venv, icons, PyInstaller, smoke test, then `hdiutil` packs the
`.app` plus an `/Applications` symlink into a drag-to-install `.dmg`.

The build produces a binary for the machine's own architecture. An Apple
Silicon build will not run on an Intel Mac. Either build on both, let CI do it
(the workflow builds each), or set `DRAFT_ASSISTANT_TARGET_ARCH=universal2`
**with a universal2 build Python** — the python.org installers are universal,
Homebrew and `actions/setup-python` are not.

## Building both via CI

[`.github/workflows/release.yml`](../.github/workflows/release.yml) runs the
tests, then builds the Windows installer and both macOS DMGs.

- **Manual run** (Actions tab → Build installers → Run workflow): artifacts are
  attached to the run. This is how to get a Mac build without owning a Mac.
- **Tag push**: also publishes a GitHub Release with all three files attached.

```bash
git tag v1.0.0 && git push origin v1.0.0
```

Bump `__version__` in [`draft_assistant/__init__.py`](../draft_assistant/__init__.py)
first — the spec, the installer and the bundle all read it from there.

---

## Code signing

Unsigned builds work, but both operating systems warn about them. Worth knowing
what each costs before deciding.

### Windows

SmartScreen shows *"Windows protected your PC"*; testers click **More info →
Run anyway**. Signing needs an OV or EV code-signing certificate (roughly
$200–600/year from a CA). An OV certificate still accumulates SmartScreen
reputation for a while before the warning disappears; an EV certificate skips
that. **For a handful of friends, not worth buying.**

### macOS

Unsigned is rougher here. macOS says *"Apple could not verify..."* and the old
right-click → Open trick no longer works on recent macOS — testers must go to
**System Settings → Privacy & Security** and click **Open Anyway** after the
first blocked launch. It works, it just needs instructions
([docs/FOR_TESTERS.md](FOR_TESTERS.md) has them).

Signing needs the **Apple Developer Program, $99/year**. With it:

```bash
export DRAFT_ASSISTANT_CODESIGN_IDENTITY="Developer ID Application: Your Name (TEAMID)"
export NOTARY_PROFILE="draft-assistant"     # created once, see below
./packaging/macos/build.sh
```

The one-time notary credential setup:

```bash
xcrun notarytool store-credentials draft-assistant \
    --apple-id you@example.com \
    --team-id TEAMID \
    --password <app-specific-password>
```

With both set, the build signs under the hardened runtime, notarizes, and
staples the ticket — testers then get no warning at all. **This is the single
biggest quality-of-life upgrade for Mac testers**, and the $99 also covers the
App Store path.

For the Mac App Store specifically, see [MAC_APP_STORE.md](MAC_APP_STORE.md) —
it is a materially different build, not a flag on this one.
