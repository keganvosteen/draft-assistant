"""Durable league and roster state, independent of the installed app version.

Browser storage is a migration source and cache. This file is the authoritative
copy once saved; an old tab must provide its revision before replacing it.
"""
from __future__ import annotations

import errno
import json
import math
import os
import re
import tempfile
import threading
import time
from contextlib import contextmanager
from pathlib import Path

from . import paths

SCHEMA_VERSION = 1
MAX_BYTES = 8 * 1024 * 1024
MAX_LEAGUES = 50
MAX_PICKS_PER_LEAGUE = 2048
BACKUP_COUNT = 10
LOCK_TIMEOUT_SECONDS = 5.0
_LOCK = threading.RLock()
_CREDENTIAL_KEYS = {"espns2", "swid", "accesstoken", "refreshtoken", "clientsecret", "token"}


class WorkspaceValidationError(ValueError):
    """The proposed state is invalid; the current state has not changed."""


class WorkspaceVersionError(WorkspaceValidationError):
    """A newer app wrote this state; this app must not downgrade it."""


class WorkspaceConflictError(RuntimeError):
    def __init__(self, revision: int):
        self.revision = revision
        super().__init__("Your leagues changed in another window. Reload to use the latest saved version.")


class WorkspaceStorageError(RuntimeError):
    """Saved data could not be read or safely replaced."""


def _empty() -> dict:
    return {"exists": False, "revision": 0, "schemaVersion": SCHEMA_VERSION,
            "leagues": [], "picks": {}, "preferences": {}}


def _validate_json(value, depth: int = 0) -> None:
    if depth > 64:
        raise WorkspaceValidationError("Workspace metadata is nested too deeply.")
    if isinstance(value, dict):
        for key, child in value.items():
            if not isinstance(key, str):
                raise WorkspaceValidationError("Workspace object keys must be strings.")
            if key.lower().replace("_", "").replace("-", "") in _CREDENTIAL_KEYS:
                raise WorkspaceValidationError("Keep provider credentials out of saved league data; enter them in the session access fields.")
            _validate_json(child, depth + 1)
    elif isinstance(value, list):
        for child in value:
            _validate_json(child, depth + 1)
    elif isinstance(value, float) and not math.isfinite(value):
        raise WorkspaceValidationError("Workspace numbers must be finite.")
    elif value is not None and not isinstance(value, (str, bool, int, float)):
        raise WorkspaceValidationError("Workspace metadata must contain JSON values.")


def validate_workspace(value) -> None:
    """Validate a migration or save payload without reading or changing disk."""
    if not isinstance(value, dict):
        raise WorkspaceValidationError("Workspace must be an object.")
    version = value.get("schemaVersion")
    if type(version) is not int or version < 1:
        raise WorkspaceValidationError("Workspace schemaVersion must be a positive integer.")
    if version > SCHEMA_VERSION:
        raise WorkspaceVersionError("This data was saved by a newer app. Update the app to open it; your saved data has been left unchanged.")
    revision = value.get("revision")
    if type(revision) is not int or revision < 0:
        raise WorkspaceValidationError("Workspace revision must be a nonnegative integer.")
    leagues, picks = value.get("leagues"), value.get("picks")
    if not isinstance(leagues, list) or len(leagues) > MAX_LEAGUES:
        raise WorkspaceValidationError(f"Workspace leagues must be a list of at most {MAX_LEAGUES} leagues.")
    ids = set()
    for league in leagues:
        league_id = league.get("id") if isinstance(league, dict) else None
        if not isinstance(league_id, str) or not league_id.strip() or len(league_id) > 256:
            raise WorkspaceValidationError("Each league must have a nonempty string id of at most 256 characters.")
        if league_id in ids:
            raise WorkspaceValidationError("League ids must be unique.")
        ids.add(league_id)
    if not isinstance(picks, dict) or any(key not in ids for key in picks):
        raise WorkspaceValidationError("Workspace picks must be an object keyed by saved league ids.")
    if not isinstance(value.get("preferences", {}), dict):
        raise WorkspaceValidationError("Workspace preferences must be an object.")
    for rows in picks.values():
        if (not isinstance(rows, list) or len(rows) > MAX_PICKS_PER_LEAGUE
                or not all(isinstance(pick, dict) for pick in rows)):
            raise WorkspaceValidationError(f"Each league's picks must be a list of at most {MAX_PICKS_PER_LEAGUE} pick objects.")
    _validate_json(value)


def _json_object(pairs) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON object key")
        result[key] = value
    return result


def _read(path: Path) -> tuple[dict, bytes | None]:
    try:
        with path.open("rb") as stream:
            raw = stream.read(MAX_BYTES + 1)
    except FileNotFoundError:
        return _empty(), None
    except OSError as exc:
        raise WorkspaceStorageError("Could not read saved leagues. The saved file has been left unchanged.") from exc
    try:
        if len(raw) > MAX_BYTES:
            raise ValueError("Saved workspace is too large")
        state = json.loads(raw, object_pairs_hook=_json_object)
        validate_workspace(state)
        if state.get("exists") is not True or state["revision"] < 1:
            raise ValueError("Invalid saved workspace revision")
        state.setdefault("preferences", {})
    except WorkspaceVersionError:
        raise
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise WorkspaceStorageError("Saved league data could not be read. It has been left unchanged; restore a workspace backup before continuing.") from exc
    return state, raw


def load_workspace() -> dict:
    """Read a fresh snapshot without seeding, repairing, or changing any file."""
    with _LOCK:
        return _read(Path(paths.resolve("workspace-state.json")))[0]


def _atomic_write(path: Path, raw: bytes) -> None:
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="wb", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _try_lock(stream) -> None:
    if os.name == "nt":
        import msvcrt
        stream.seek(0)
        msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock(stream) -> None:
    if os.name == "nt":
        import msvcrt
        stream.seek(0)
        msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl
        fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


@contextmanager
def _file_lock(path: Path):
    # Lock a stable sibling, since os.replace swaps the workspace's file handle.
    # Keeping the lock file also prevents two processes locking different files
    # after one writer removes a lock file the other writer has already opened.
    with path.with_suffix(".lock").open("a+b") as stream:
        # Windows byte locks also prohibit another process from reading the
        # locked byte, so inspect the file size without reading its contents.
        if os.fstat(stream.fileno()).st_size == 0:
            stream.write(b"\0")
            stream.flush()
        deadline = time.monotonic() + LOCK_TIMEOUT_SECONDS
        while True:
            try:
                _try_lock(stream)
                break
            except OSError as exc:
                if exc.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                    raise
                if time.monotonic() >= deadline:
                    raise WorkspaceStorageError("Another app window is saving your leagues. Wait a moment and try again; your saved data has been left unchanged.") from exc
                time.sleep(0.025)
        try:
            yield
        finally:
            try:
                _unlock(stream)
            except OSError:
                # Closing the handle also releases the lock. Do not report a
                # failed save after an already committed atomic replacement.
                pass


def _backup(path: Path, revision: int, raw: bytes) -> None:
    directory = path.parent / "backups"
    directory.mkdir(parents=True, exist_ok=True)
    backup = directory / f"workspace-state.{revision}.json"
    if backup.exists():
        if backup.read_bytes() != raw:
            raise OSError("A different backup already uses this workspace revision")
    else:
        _atomic_write(backup, raw)


def _prune_backups(path: Path) -> None:
    # Revision 1 holds the initial browser migration and is never aged out.
    try:
        candidates = []
        for backup in (path.parent / "backups").glob("workspace-state.*.json"):
            match = re.fullmatch(r"workspace-state\.(\d+)\.json", backup.name)
            if match and int(match[1]) != 1:
                candidates.append((int(match[1]), backup))
        for _, backup in sorted(candidates, reverse=True)[BACKUP_COUNT:]:
            backup.unlink()
    except OSError:
        # Retention housekeeping cannot turn a successful save into a failure.
        pass


def save_workspace(value: dict) -> dict:
    """Atomically replace a matching revision, retaining prior valid versions."""
    validate_workspace(value)
    state = {"exists": True, "schemaVersion": SCHEMA_VERSION,
             "revision": value["revision"] + 1, "leagues": value["leagues"],
             "picks": value["picks"], "preferences": value.get("preferences", {})}
    try:
        raw = json.dumps(state, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise WorkspaceValidationError("Workspace metadata must contain valid JSON text.") from exc
    if len(raw) > MAX_BYTES:
        raise WorkspaceValidationError("Saved league data must be smaller than 8 MiB.")
    with _LOCK:
        path = Path(paths.resolve("workspace-state.json"))
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with _file_lock(path):
                current, previous = _read(path)
                if value["revision"] != current["revision"]:
                    raise WorkspaceConflictError(current["revision"])
                if previous is not None:
                    _backup(path, current["revision"], previous)
                _atomic_write(path, raw)
                _prune_backups(path)
        except OSError as exc:
            raise WorkspaceStorageError("Could not save leagues. The previous saved version has been kept; check available disk space and folder access.") from exc
    # Return exactly what was persisted, with no mutable references to callers.
    return json.loads(raw)
