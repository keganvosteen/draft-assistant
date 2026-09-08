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
* **Anything else** — refuse to persist. Returning "unavailable" makes the
  caller keep secrets in memory for the session rather than silently writing
  them out in the clear.

``backend()`` names which one is in play so the UI can say where a credential
lives and how it is protected.
"""
from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
from typing import Optional

KEYCHAIN_SERVICE = "DraftAssistant"

# Marks a file this module wrote, and records which backend sealed it, so a
# file written under one backend is never mistaken for another's format.
_MAGIC = "draft-assistant-secret-v1"


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
    subprocess.run(
        ["security", "add-generic-password", "-U",
         "-s", KEYCHAIN_SERVICE, "-a", account, "-w", secret],
        check=True, capture_output=True,
    )


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
    """Persist *data* for *account*. False when no keystore is available.

    The caller passes both a path and an account name because the two backends
    keep the payload in different places: DPAPI seals it into the file, while
    the Keychain holds it and the file is only a marker.
    """
    if not data:
        forget(path, account)
        return True
    kind = backend()
    if kind == "none":
        return False
    payload = json.dumps(data).encode("utf-8")
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    if kind == "dpapi":
        sealed = base64.b64encode(_dpapi(payload, protect=True)).decode("ascii")
        body = {"magic": _MAGIC, "backend": kind, "account": account, "sealed": sealed}
    else:
        _keychain_write(account, payload.decode("utf-8"))
        body = {"magic": _MAGIC, "backend": kind, "account": account}
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(body, handle, indent=2)
    os.replace(tmp, path)
    try:  # Owner-only, for the keystore-less case and defence in depth.
        os.chmod(path, 0o600)
    except OSError:
        pass
    return True


def load(path: str, account: str) -> dict:
    """Read back what save() wrote. Empty dict when absent or unreadable."""
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as handle:
            body = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(body, dict):
        return {}
    # A file written before this module existed is a bare plaintext dict; read
    # it so an upgrade keeps working, and let the caller re-save it sealed.
    if body.get("magic") != _MAGIC:
        return body
    if body.get("backend") != backend():
        return {}
    try:
        if body["backend"] == "dpapi":
            raw = _dpapi(base64.b64decode(body["sealed"]), protect=False)
        else:
            secret = _keychain_read(body.get("account") or account)
            if not secret:
                return {}
            raw = secret.encode("utf-8")
        loaded = json.loads(raw)
        return loaded if isinstance(loaded, dict) else {}
    except (OSError, KeyError, ValueError):
        return {}


def is_sealed(path: str) -> bool:
    """True when *path* holds a keystore-protected payload, not plaintext."""
    try:
        with open(path, encoding="utf-8") as handle:
            body = json.load(handle)
        return isinstance(body, dict) and body.get("magic") == _MAGIC
    except (OSError, json.JSONDecodeError):
        return False


def forget(path: str, account: str) -> None:
    """Remove a stored credential from both the file and the keystore."""
    if backend() == "keychain":
        _keychain_delete(account)
    try:
        os.remove(path)
    except OSError:
        pass
