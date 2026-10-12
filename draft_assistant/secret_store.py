"""At-rest protection for provider credentials, using the OS keystore.

The app holds two kinds of secret: ESPN session cookies (``espn_s2`` and
``SWID``, which authenticate the *whole* ESPN account, not just fantasy) and
Yahoo OAuth tokens. Both used to sit in a plain file next to the draft state,
where any other process running as the user — or anything that reads a synced
folder — could lift them.

There is no AES in the standard library and this app ships no dependencies, so
rather than hand-rolling a cipher each platform's own keystore does the work:

* **Windows** — DPAPI (``CryptProtectData``) via ctypes. Keyed to the logged-in
  Windows account, so the file is useless on another machine or to another user.
* **macOS** — the login Keychain via the ``security`` tool.
* **Anything else** — refuse to persist and keep profile-scoped secrets in
  memory for the session rather than silently writing them out in the clear.

``backend()`` names which one is in play so the UI can say where a credential
lives and how it is protected.
"""
from __future__ import annotations

import base64
import copy
import hashlib
import json
import os
import subprocess
import sys
import threading
from typing import Optional

KEYCHAIN_SERVICE = "DraftAssistant"

# Marks a file this module wrote, and records which backend sealed it, so a
# file written under one backend is never mistaken for another's format.
_MAGIC = "draft-assistant-secret-v1"
_guard = threading.Lock()
_locks = {}
_session = {}


def _identity(path: str, account: str) -> tuple:
    return os.path.normcase(os.path.realpath(os.path.abspath(os.fspath(path)))), account


def locked(path: str, account: str):
    """Serialize a credential transaction across request-handler instances."""
    identity = _identity(path, account)
    with _guard:
        return _locks.setdefault(identity, threading.RLock())


def _keychain_account(path: str, account: str) -> str:
    identity = json.dumps(_identity(path, account), ensure_ascii=True).encode("utf-8")
    return f"{account}:{hashlib.sha256(identity).hexdigest()}"


def backend() -> str:
    """Which keystore protects secrets here: 'dpapi', 'keychain' or 'none'."""
    if sys.platform == "win32":
        return "dpapi"
    if sys.platform == "darwin":
        return "keychain"
    return "none"


def available() -> bool:
    return backend() != "none"


def describe() -> str:
    """One line for the UI about where a saved credential lives."""
    return {
        "dpapi": "Encrypted with Windows DPAPI — readable only by your Windows account on this PC.",
        "keychain": "Stored in your macOS login Keychain.",
        "none": "This platform has no supported keystore, so credentials are kept in memory only.",
    }[backend()]


# ── Windows DPAPI ────────────────────────────────────────────────────────────

def _dpapi(data: bytes, protect: bool) -> bytes:
    import ctypes
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD),
                    ("pbData", ctypes.POINTER(ctypes.c_char))]

    buffer = ctypes.create_string_buffer(data, len(data))
    blob_in = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))
    blob_out = Blob()
    crypt32 = ctypes.windll.crypt32
    call = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    # (pDataIn, description, entropy, reserved, prompt, flags, pDataOut)
    ok = call(ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out))
    if not ok:
        raise OSError(f"DPAPI {'protect' if protect else 'unprotect'} failed")
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(blob_out.pbData)


# ── macOS Keychain ───────────────────────────────────────────────────────────

def _keychain_write(account: str, secret: str) -> None:
    try:
        subprocess.run(
            ["security", "add-generic-password", "-U",
             "-s", KEYCHAIN_SERVICE, "-a", account, "-w", secret],
            check=True, capture_output=True,
        )
    except subprocess.CalledProcessError:
        # CalledProcessError includes argv, which contains the secret. Never
        # allow it to reach an HTTP error response or a diagnostic log.
        raise OSError("Could not save credentials in the macOS Keychain") from None


def _keychain_read(account: str) -> Optional[str]:
    result = subprocess.run(
        ["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-a", account, "-w"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def _keychain_delete(account: str) -> None:
    subprocess.run(
        ["security", "delete-generic-password", "-s", KEYCHAIN_SERVICE, "-a", account],
        capture_output=True,
    )


# ── public API ───────────────────────────────────────────────────────────────

def save(path: str, account: str, data: dict) -> bool:
    """Store credentials; False means they are kept in memory for this run.

    The caller passes both a path and an account name because the two backends
    keep the payload in different places: DPAPI seals it into the file, while
    the Keychain holds it and the file is only a marker.
    """
    from .storage import atomic_write_json

    with locked(path, account):
        if not data:
            forget(path, account)
            return True
        kind = backend()
        if kind == "none":
            _session[_identity(path, account)] = copy.deepcopy(data)
            # Consume a legacy plaintext file only after preserving its data
            # in this session. Do not remove an encrypted file from another OS.
            if os.path.exists(path) and not is_sealed(path):
                os.remove(path)
            return False
        payload = json.dumps(data).encode("utf-8")
        if kind == "dpapi":
            sealed = base64.b64encode(_dpapi(payload, protect=True)).decode("ascii")
            body = {"magic": _MAGIC, "backend": kind, "account": account, "sealed": sealed}
        else:
            scoped_account = _keychain_account(path, account)
            _keychain_write(scoped_account, payload.decode("utf-8"))
            body = {"magic": _MAGIC, "backend": kind, "account": scoped_account}
        atomic_write_json(path, body)
        _session.pop(_identity(path, account), None)
        try:  # The file is encrypted or contains only a Keychain marker.
            os.chmod(path, 0o600)
        except OSError:
            pass
        return True


def load(path: str, account: str) -> dict:
    """Read credentials, migrating legacy plaintext/shared Keychain markers.

    A legacy shared Keychain item is copied, never deleted: other profiles
    may still refer to it. A failed migration leaves the original untouched.
    """
    with locked(path, account):
        if backend() == "none" and _identity(path, account) in _session:
            return copy.deepcopy(_session[_identity(path, account)])
        return _load(path, account)


def _load(path: str, account: str) -> dict:
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as handle:
            body = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(body, dict):
        return {}
    # Migrate on read, including status-only requests, so an unused refresh
    # token does not leave plaintext behind indefinitely after upgrading.
    if body.get("magic") != _MAGIC:
        save(path, account, body)
        return body
    if body.get("backend") != backend():
        return {}
    try:
        if body["backend"] == "dpapi":
            if body.get("account") != account:
                return {}
            raw = _dpapi(base64.b64decode(body["sealed"]), protect=False)
        elif body["backend"] == "keychain":
            stored_account = body.get("account") or account
            if stored_account not in {account, _keychain_account(path, account)}:
                return {}
            secret = _keychain_read(stored_account)
            if not secret:
                return {}
            raw = secret.encode("utf-8")
        else:
            return {}
        loaded = json.loads(raw)
    except (OSError, KeyError, ValueError):
        return {}
    if not isinstance(loaded, dict):
        return {}
    if body["backend"] == "keychain" and stored_account == account:
        save(path, account, loaded)
    return loaded


def is_sealed(path: str) -> bool:
    """True when *path* holds a keystore-protected payload, not plaintext."""
    try:
        with open(path, encoding="utf-8") as handle:
            body = json.load(handle)
        return isinstance(body, dict) and body.get("magic") == _MAGIC
    except (OSError, json.JSONDecodeError):
        return False


def forget(path: str, account: str) -> None:
    """Remove this profile's credentials without touching shared legacy items."""
    with locked(path, account):
        _session.pop(_identity(path, account), None)
        if backend() == "keychain":
            _keychain_delete(_keychain_account(path, account))
        try:
            os.remove(path)
        except FileNotFoundError:
            pass
