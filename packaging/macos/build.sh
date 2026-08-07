#!/usr/bin/env bash
#
# Builds Draft Assistant.app and a distributable .dmg on macOS.
#
#   ./packaging/macos/build.sh
#
# Output: dist/installers/DraftAssistant-<version>-<arch>.dmg
#
# Signing is optional and driven by environment variables. With none set the
# build is ad-hoc signed, which runs fine locally but shows a Gatekeeper
# warning after being downloaded (see docs/DISTRIBUTION.md).
#
#   DRAFT_ASSISTANT_CODESIGN_IDENTITY   e.g. "Developer ID Application: Name (TEAMID)"
#   DRAFT_ASSISTANT_TARGET_ARCH         set to "universal2" if the build Python is universal
#   NOTARY_PROFILE                      notarytool keychain profile; enables notarize+staple
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

BUILD_VENV="$ROOT/.venv-build"
PY="$BUILD_VENV/bin/python"
PYI_DIST="$ROOT/dist/pyinstaller"
APP="$PYI_DIST/Draft Assistant.app"
INSTALLER_DIR="$ROOT/dist/installers"
ARCH="$(uname -m)"

VERSION="$(python3 -c 'import draft_assistant; print(draft_assistant.__version__)')"
echo "Building Draft Assistant $VERSION (macOS, $ARCH)"

# --- build venv -----------------------------------------------------------
if [ ! -x "$PY" ]; then
    echo "Creating build venv..."
    python3 -m venv "$BUILD_VENV"
fi
"$PY" -m pip install --upgrade pip --quiet
"$PY" -m pip install -r requirements-build.txt --quiet
# pyobjc-* are pywebview's Cocoa backend; without them the native window falls
# back to the browser.
"$PY" -m pip install -r requirements-desktop.txt pyobjc-core pyobjc-framework-Cocoa pyobjc-framework-WebKit --quiet

# --- release gate ---------------------------------------------------------
# Refuse to ship a silently degraded board (for example, a single-source pull
# with no byes/history or an entire position with empty projections).
"$PY" scripts/check_projection_quality.py data/projections.json

# --- icons ----------------------------------------------------------------
"$PY" packaging/make_icons.py

# --- PyInstaller ----------------------------------------------------------
rm -rf "$APP" "$PYI_DIST/DraftAssistant"
if [ -n "${DRAFT_ASSISTANT_CODESIGN_IDENTITY:-}" ]; then
    export DRAFT_ASSISTANT_ENTITLEMENTS="$ROOT/packaging/macos/entitlements.plist"
fi
"$PY" -m PyInstaller packaging/DraftAssistant.spec \
    --noconfirm --clean \
    --distpath "$PYI_DIST" \
    --workpath "$ROOT/build/pyinstaller"

[ -d "$APP" ] || { echo "ERROR: PyInstaller did not produce $APP" >&2; exit 1; }

# --- signing --------------------------------------------------------------
# PyInstaller signs the inner Mach-O files; the outer bundle still needs a
# seal, and it must come last or it gets invalidated.
if [ -n "${DRAFT_ASSISTANT_CODESIGN_IDENTITY:-}" ]; then
    echo "Signing with: $DRAFT_ASSISTANT_CODESIGN_IDENTITY"
    codesign --force --deep --options runtime --timestamp \
        --entitlements "$ROOT/packaging/macos/entitlements.plist" \
        --sign "$DRAFT_ASSISTANT_CODESIGN_IDENTITY" \
        "$APP"
    codesign --verify --deep --strict --verbose=2 "$APP"
else
    echo "No signing identity set - applying an ad-hoc signature."
    # Required on Apple Silicon: an unsigned bundle will not launch at all.
    codesign --force --deep --sign - "$APP"
fi

# --- smoke test -----------------------------------------------------------
echo "Smoke-testing the packaged app..."
"$ROOT/packaging/macos/smoke_test.sh" "$APP"

# --- dmg ------------------------------------------------------------------
mkdir -p "$INSTALLER_DIR"
DMG="$INSTALLER_DIR/DraftAssistant-$VERSION-$ARCH.dmg"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

cp -R "$APP" "$STAGE/"
ln -s /Applications "$STAGE/Applications"   # drag-to-install target

rm -f "$DMG"
hdiutil create \
    -volname "Draft Assistant" \
    -srcfolder "$STAGE" \
    -fs HFS+ \
    -format UDZO \
    -ov \
    "$DMG" >/dev/null

if [ -n "${DRAFT_ASSISTANT_CODESIGN_IDENTITY:-}" ]; then
    codesign --force --sign "$DRAFT_ASSISTANT_CODESIGN_IDENTITY" "$DMG"
fi

# --- notarization ---------------------------------------------------------
if [ -n "${NOTARY_PROFILE:-}" ]; then
    echo "Submitting to Apple notary service (this takes a few minutes)..."
    xcrun notarytool submit "$DMG" --keychain-profile "$NOTARY_PROFILE" --wait
    xcrun stapler staple "$DMG"
    echo "Notarized and stapled."
else
    echo
    echo "NOT notarized. Testers will see 'Apple could not verify...' on first"
    echo "launch and must allow it in System Settings > Privacy & Security."
    echo "See docs/DISTRIBUTION.md."
fi

echo
echo "Disk image created:"
echo "  $DMG"
