# -*- mode: python ; coding: utf-8 -*-
"""Shared PyInstaller spec for the Windows and macOS builds.

Build with:  pyinstaller packaging/DraftAssistant.spec --noconfirm --clean

One spec for both platforms so the two installers can never drift on which
files get bundled. Platform differences (icon format, console flag, .app
bundle) are branched below.
"""
import os
import sys
from pathlib import Path

ROOT = Path(SPECPATH).resolve().parent
ICONS = ROOT / "packaging" / "icons"

sys.path.insert(0, str(ROOT))
from draft_assistant import __version__ as APP_VERSION  # noqa: E402

IS_WINDOWS = sys.platform == "win32"
IS_MACOS = sys.platform == "darwin"

BUNDLE_ID = "com.keganvosteen.draftassistant"

# Defaults to the build machine's own architecture. "universal2" only works if
# the *build* Python is itself a universal2 binary (python.org installers are;
# Homebrew and actions/setup-python are not), so it stays opt-in.
TARGET_ARCH = os.environ.get("DRAFT_ASSISTANT_TARGET_ARCH") or None

CODESIGN_IDENTITY = os.environ.get("DRAFT_ASSISTANT_CODESIGN_IDENTITY") or None
ENTITLEMENTS = os.environ.get("DRAFT_ASSISTANT_ENTITLEMENTS") or None

# Read-only payload. paths.py copies the seeded files out of here into the
# per-user data directory on first run, so these never get written in place.
datas = [
    (str(ROOT / "draft_assistant" / "web" / "static"), "draft_assistant/web/static"),
    (str(ROOT / "data" / "projections.json"), "data"),
    (str(ROOT / "league.config.yaml"), "."),
]

hiddenimports = []
if IS_WINDOWS:
    # pywebview's Edge WebView2 backend is resolved dynamically.
    hiddenimports += ["webview.platforms.edgechromium", "clr_loader", "pythonnet"]
elif IS_MACOS:
    hiddenimports += ["webview.platforms.cocoa"]

# The packaged app ships the web UI only; the Tkinter UI (`draft-assistant ui`)
# stays a source-checkout feature. Dropping tcl/tk saves ~10 MB per build.
excludes = [
    "tkinter",
    "unittest",
    "pydoc_data",
    "test",
]

a = Analysis(
    [str(ROOT / "packaging" / "launcher.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="DraftAssistant",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    # No console: the packaged app opens a native window (or the browser).
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=TARGET_ARCH if IS_MACOS else None,
    codesign_identity=CODESIGN_IDENTITY if IS_MACOS else None,
    entitlements_file=ENTITLEMENTS if IS_MACOS else None,
    icon=str(ICONS / ("DraftAssistant.ico" if IS_WINDOWS else "DraftAssistant.icns")),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="DraftAssistant",
)

if IS_MACOS:
    app = BUNDLE(
        coll,
        name="Draft Assistant.app",
        icon=str(ICONS / "DraftAssistant.icns"),
        bundle_identifier=BUNDLE_ID,
        version=APP_VERSION,
        info_plist={
            "CFBundleName": "Draft Assistant",
            "CFBundleDisplayName": "Draft Assistant",
            "CFBundleShortVersionString": APP_VERSION,
            "CFBundleVersion": APP_VERSION,
            "LSMinimumSystemVersion": "11.0",
            "LSApplicationCategoryType": "public.app-category.sports",
            "NSHighResolutionCapable": True,
            # No document types and no background modes — this is a plain
            # foreground app that talks to 127.0.0.1 and a few fantasy APIs.
            "NSHumanReadableCopyright": "Copyright (c) 2026 Kegan Vosteen",
        },
    )
