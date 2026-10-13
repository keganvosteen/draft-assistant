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
* **macOS** — the login Keychain via the ``security`` tool. The file beside the
  draft state is then only a marker naming the Keychain item that holds it.
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
import re
import subprocess
import sys
import threading
import uuid
from typing import Optional

KEYCHAIN_SERVICE = "DraftAssistant"

# Marks a file this module wrote, and records which backend sealed it, so a
# file written under one backend is never mistaken for another's format.
_MAGIC = "draft-assistant-secret-v1"
_guard = threading.Lock()
_locks = {}
_session = {}
# Stores whose plaintext file this run removed for want of a keystore to move
# it into. See plaintext_removed().
_plaintext_removed = set()


def _identity(path: str, account: str) -> tuple:
    return os.path.normcase(os.path.realpath(os.path.abspath(os.fspath(path)))), account


def locked(path: str, account: str):
    """Serialize a credential transaction across request-handler instances."""
    identity = _identity(path, account)
    with _guard:
        return _locks.setdefault(identity, threading.RLock())


def _keychain_account(path: str, account: str) -> str:
    """The Keychain item name 0.7.4 derived from where the store file sat.

    Nothing is created under this name any more: tying the item to the path
    meant that moving the data directory lost the credential and orphaned the
    item. It survives only so forget() can still clear a 0.7.4 item out from
    under the path it was written for.
    """
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
        # Has to spell out the restart and the deleted file: this line is all
        # the UI shows, and "memory only" alone said neither.
        "none": ("This platform has no supported keystore, so credentials are kept in "
                 "memory only and must be re-entered after the app restarts; any "
                 "unencrypted copy an earlier version left on disk is deleted."),
    }[backend()]


def plaintext_removed(path: str, account: str) -> bool:
    """True when this run deleted *path*'s plaintext file and holds it in memory.

    Lets a caller tell the user once, in the UI, what the stderr notice told
    whoever started the process: these credentials will not survive a restart.
    """
    return _identity(path, account) in _plaintext_removed


def _report_plaintext_removed(path: str, account: str) -> None:
    # Without a keystore the first read of a legacy file — a status poll is
    # enough — moves it into memory and deletes it. Doing that quietly meant
    # saved credentials simply vanished at the next restart.
    _plaintext_removed.add(_identity(path, account))
    try:
        print(
            f"WARNING: removed the unencrypted credential file {os.path.abspath(path)}. "
            "This platform has no supported keystore, so those credentials are now held "
            "only in memory and must be re-entered after the app restarts.",
            file=sys.stderr,
        )
    except (OSError, ValueError):
        # A closed or broken stderr must not fail the read that got here. By
        # now the file is gone and its credentials are in memory, so raising
        # only turned the first status poll into an error; describe() still
        # tells the UI what this line could not.
        pass


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

# ``security -i`` reads its commands from stdin, one line at a time, into a
# 4096-byte buffer. It does not reject a longer line: it runs the first 4095
# bytes as the command — storing a truncated secret — and then reads the rest
# as the *next* command. Stay well short of that so a line is never split.
_KEYCHAIN_LINE_LIMIT = 4000
# Bounds the stdin attempt only, so a hang nobody foresaw there degrades to
# the argv write instead of freezing every credential save.
_KEYCHAIN_STDIN_TIMEOUT = 30
# The account sits on that line unquoted. Anything the tool's tokenizer could
# take for whitespace, a quote or an escape sends the write to argv instead.
_KEYCHAIN_PLAIN_ACCOUNT = re.compile(r"[A-Za-z0-9._:-]+")
# A per-store item id: the uuid4 hex minted by save(), or the SHA-256 hex
# that 0.7.4 derived from the store's path.
_KEYCHAIN_ITEM_ID = re.compile(r"[0-9a-f]{32}(?:[0-9a-f]{32})?")
# How the last Keychain write reached ``security``: "stdin-hex", "stdin-quoted"
# or "argv". Never holds secret material; the native smoke check asserts on it.
_keychain_transport: Optional[str] = None


def _keychain_stdin_command(account: str, secret: str) -> Optional[tuple]:
    """One ``security -i`` line that stores *secret*, as ``(transport, line)``.

    None means no line is safe to send and the write has to use argv.
    """
    if not secret or not _KEYCHAIN_PLAIN_ACCOUNT.fullmatch(account):
        return None
    try:
        # -X takes the password as hex, which the tokenizer cannot misread.
        forms = [("stdin-hex", "-X " + secret.encode("utf-8").hex())]
    except UnicodeError:
        return None
    # Hex doubles the length, so a secret too long for it is single-quoted
    # instead: inside quotes the tokenizer lets a backslash escape the next
    # character and ends the argument only at the opening quote character.
    # Printable ASCII only — all json.dumps emits — so no byte can end the
    # line early.
    if secret.isascii() and secret.isprintable():
        escaped = secret.replace("\\", "\\\\").replace("'", "\\'")
        forms.append(("stdin-quoted", f"-w '{escaped}'"))
    for transport, password in forms:
        # -U goes last on purpose. Should some build's buffer be shorter than
        # the limit assumes, the half that runs has no -U and fails as a
        # duplicate instead of overwriting a good item with a truncated one,
        # and the leftover arrives with an option attached rather than as a
        # bare word (commands match by prefix: a stray "c" is create-keychain).
        line = f"add-generic-password -s {KEYCHAIN_SERVICE} -a {account} {password} -U\n"
        if len(line) <= _KEYCHAIN_LINE_LIMIT:
            return transport, line.encode("ascii")
    return None


def _keychain_run(command: list, stdin: Optional[bytes] = None,
                  timeout: Optional[float] = None) -> bool:
    """Run ``security`` and report only whether it exited cleanly.

    Everything subprocess can raise here carries the secret: CalledProcessError
    and TimeoutExpired keep argv (which holds it on the fallback write) and
    their tracebacks hold the stdin payload. ``raise ... from None`` would not
    be enough — the original still hangs off ``__context__`` — so the outcome
    is collapsed to a bool and the caller raises outside any handler.
    """
    try:
        result = subprocess.run(command, input=stdin, capture_output=True, timeout=timeout)
    except (OSError, ValueError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def _keychain_holds(account: str, secret: str) -> bool:
    # ``find-generic-password -w`` prints hex for anything that is not
    # printable ASCII, so such a secret never matches and takes the fallback.
    try:
        return _keychain_read(account) == secret
    except (OSError, ValueError, subprocess.SubprocessError):
        return False


def _keychain_write(account: str, secret: str) -> None:
    """Store *secret*, keeping it off the command line whenever it fits a line.

    argv is readable by every local process for as long as the call runs, and
    an hourly token refresh repeats the call. Feeding ``security -i`` through
    stdin leaves nothing in argv but ``-i``.
    """
    global _keychain_transport
    _keychain_transport = None
    command = _keychain_stdin_command(account, secret)
    if command is not None:
        transport, line = command
        # The exit status is only that of the last command the tool happened
        # to read, so the write counts only once the item reads back intact.
        if (_keychain_run(["security", "-i"], line, _KEYCHAIN_STDIN_TIMEOUT)
                and _keychain_holds(account, secret)):
            _keychain_transport = transport
            return
    # What every write did before the stdin path existed, which is what makes
    # that path never worse than this one. -U overwrites whatever a failed
    # attempt above left behind.
    if not _keychain_run(["security", "add-generic-password", "-U",
                          "-s", KEYCHAIN_SERVICE, "-a", account, "-w", secret]):
        raise OSError("Could not save credentials in the macOS Keychain")
    _keychain_transport = "argv"


def _keychain_read(account: str) -> Optional[str]:
    result = subprocess.run(
        ["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-a", account, "-w"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def _keychain_delete(account: str) -> None:
    result = subprocess.run(
        ["security", "delete-generic-password", "-s", KEYCHAIN_SERVICE, "-a", account],
        capture_output=True,
    )
    # A delete that failed used to pass for one that worked, and forget() went
    # on to remove the marker. That was survivable while the item's name could
    # be recomputed from the path; a random id lives nowhere but that marker.
    # "No such item" exits non-zero as well, so the status cannot tell the two
    # apart — ask whether the item is still there.
    if result.returncode != 0 and _keychain_has(account):
        raise OSError("Could not remove credentials from the macOS Keychain")


def _keychain_has(account: str) -> bool:
    # Without -w this prints the item's attributes and never its password.
    result = subprocess.run(
        ["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-a", account],
        capture_output=True,
    )
    return result.returncode == 0


def _read_body(path: str, strict: bool = False) -> Optional[dict]:
    """The store file's JSON object, or None if it is missing or not one.

    *strict* raises OSError for a file that is there but cannot be read just
    now, instead of passing it off as missing. See _marker_item().
    """
    try:
        with open(path, encoding="utf-8") as handle:
            body = json.load(handle)
    except (FileNotFoundError, NotADirectoryError):
        return None
    except OSError:
        if strict:
            raise
        return None
    except (ValueError, RecursionError):
        # RecursionError is how json gives up on a deeply nested file. 0.7.4's
        # save() and forget() never parsed the file at all, so letting it
        # through left a store that could be neither replaced nor forgotten.
        return None
    return body if isinstance(body, dict) else None


def _keychain_item(body: Optional[dict], account: str) -> Optional[str]:
    """The per-store Keychain item a marker assigns to *account*, if any.

    The marker is the only record of which item is a store's, so it is also
    the only thing trusted to say so: a marker sealed by another backend, one
    naming another provider's item, or the bare provider name (the item 0.7.3
    and earlier shared between every profile) all answer None.
    """
    if not body or body.get("magic") != _MAGIC or body.get("backend") != "keychain":
        return None
    stored = body.get("account")
    prefix = account + ":"
    if (isinstance(stored, str) and stored.startswith(prefix)
            and _KEYCHAIN_ITEM_ID.fullmatch(stored[len(prefix):])):
        return stored
    return None


def _marker_item(path: str, account: str) -> Optional[str]:
    """_keychain_item() for save() and forget(), which go on to replace or
    remove the marker.

    The marker is the only record of a per-store item, so one that is there
    but cannot be read just now — too many open files, a permissions slip, a
    synced folder that is offline — has to stop them. Taking it for absent had
    save() mint a second item and forget() delete the file, and either way the
    item it named stayed in the Keychain where nothing could find it again.
    0.7.4 could not lose one like that: it recomputed the name from the path.
    """
    try:
        body = _read_body(path, strict=True)
    except OSError as error:
        reason = error.strerror or type(error).__name__
    else:
        return _keychain_item(body, account)
    raise OSError(
        f"Could not read the credential marker {os.path.abspath(path)} ({reason}). It is the "
        "only record of this profile's Keychain item, so nothing was changed; try again."
    )


def _keychain_save(path: str, account: str, secret: str) -> None:
    from .storage import atomic_write_json

    # Reuse the id the marker already holds. A random id that lives in the
    # marker travels with the directory, where 0.7.4's path-derived name lost
    # the credential — and orphaned the item — as soon as the directory moved.
    item = _marker_item(path, account)
    minted = item is None
    if minted:
        item = f"{account}:{uuid.uuid4().hex}"
    try:
        _keychain_write(item, secret)
        atomic_write_json(path, {"magic": _MAGIC, "backend": "keychain", "account": item})
    except BaseException:
        # Nothing else records a freshly minted id, so without its marker the
        # item could never be found again — not by load, not by forget.
        if minted:
            try:
                _keychain_delete(item)
            except OSError:
                pass
        raise


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
                _report_plaintext_removed(path, account)
            return False
        payload = json.dumps(data).encode("utf-8")
        if kind == "dpapi":
            sealed = base64.b64encode(_dpapi(payload, protect=True)).decode("ascii")
            atomic_write_json(path, {"magic": _MAGIC, "backend": kind,
                                     "account": account, "sealed": sealed})
        else:
            _keychain_save(path, account, payload.decode("utf-8"))
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
    body = _read_body(path)
    if body is None:
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
            # Either the legacy shared item, or whichever per-store item the
            # marker names — wherever the file sits now. Comparing against a
            # name recomputed from the path is what rejected a moved store.
            if stored_account != account and stored_account != _keychain_item(body, account):
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
        _plaintext_removed.discard(_identity(path, account))
        if backend() == "keychain":
            # The marker says which item is this store's, so a moved or
            # restored directory still forgets the right one. A *copied*
            # directory cannot be told from a moved one — both markers name
            # the same item — so forgetting through either copy removes the
            # credential for both, and the other reads as empty until it is
            # authorized again. Forgetting must never leave the secret behind.
            #
            # For the same reason the name 0.7.4 derived from this path goes
            # too: an item left under it by a store whose marker has since
            # been lost could be found no other way. The price mirrors the
            # copy: a 0.7.4 store that was *moved away* still reads that item
            # through its own marker, so forgetting whatever now lives at its
            # old path sends it back to authorize again as well.
            item = _marker_item(path, account)
            legacy = _keychain_account(path, account)
            if item:
                _keychain_delete(item)
            if legacy != item:
                _keychain_delete(legacy)
        # Last, and only once the items are gone: a delete that fails raises,
        # and until it succeeds the marker is all that says which item to
        # come back for.
        try:
            os.remove(path)
        except FileNotFoundError:
            pass
