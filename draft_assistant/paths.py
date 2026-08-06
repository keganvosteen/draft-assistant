"""Where the app reads bundled resources and writes mutable state.

Run from a source checkout, everything stays CWD-relative — the historical
behaviour, and what the tests and the CLI docs assume.

Run from an installed build, that breaks: the app lives in ``C:\\Program Files``
or inside a signed (read-only) ``.app`` bundle, so config, draft state and the
player board have to move to a per-user directory. ``resolve()`` is the seam:
it returns the same relative path in a checkout and an absolute per-user path
when frozen.
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

APP_NAME = "DraftAssistant"

#: Files seeded into a fresh user data directory from the bundled read-only copy.
_SEEDED = ("data/projections.json", "league.config.yaml")


def is_frozen() -> bool:
    """True when running from a PyInstaller build rather than a checkout."""
    return bool(getattr(sys, "frozen", False))


def resource_dir() -> Path:
    """Read-only files shipped with the app (player board, default config).

    PyInstaller unpacks ``--add-data`` payloads into ``sys._MEIPASS``; in a
    checkout the equivalent root is the repo directory.
    """
    if is_frozen():
        bundled = getattr(sys, "_MEIPASS", None)
        if bundled:
            return Path(bundled)
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def user_data_dir() -> Path:
    """Per-user, always-writable directory for config, state and the board."""
    override = os.environ.get("DRAFT_ASSISTANT_HOME")
    if override:
        return Path(override).expanduser()
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share")
    return Path(base) / APP_NAME


def mutable_root() -> Path | None:
    """Root for writable state, or None to keep using CWD-relative paths.

    None is the source-checkout case. Returning a real path here is what makes
    an installed build work, so an explicit ``DRAFT_ASSISTANT_HOME`` opts in
    too — that is how the packaged smoke test points a build at a temp dir.
    """
    if is_frozen() or os.environ.get("DRAFT_ASSISTANT_HOME"):
        return user_data_dir()
    return None


def resolve(relative: str) -> str:
    """Map a repo-relative path to wherever this install keeps mutable state."""
    root = mutable_root()
    if root is None:
        return relative
    return os.fspath(root / relative)


def seed_user_data() -> None:
    """Copy bundled defaults into the user data directory on first run.

    Only fills in what is missing, so an upgrade never clobbers a league config
    or a draft in progress.
    """
    root = mutable_root()
    if root is None:
        return
    source_root = resource_dir()
    for relative in _SEEDED:
        target = root / relative
        if target.exists():
            continue
        source = source_root / relative
        if not source.is_file():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
