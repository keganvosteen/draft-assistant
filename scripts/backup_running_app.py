"""Rescue legacy league data from an existing session that supports page reload.

Standard older native desktop windows disable Ctrl+R, F5, context menus, and
developer tools. This bridge cannot reload or rescue those windows. Keep them
open and follow docs/UPGRADING.md instead; restarting loses the private session.

Run from this checkout with --index pointing at the installed static/index.html,
--origin the *running* app's http://127.0.0.1:PORT origin, and --data-dir its
per-user DraftAssistant directory. Refresh that same window when prompted.

The temporary script reads only three Draft Assistant storage keys. A localhost
receiver saves a portable recovery file and creates workspace-state.json only
when that file is absent. The installed index is restored on success, timeout,
Ctrl+C, or an error; the original is also retained in the recovery directory.
Never close or restart a legacy private WebView before receiving confirmation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import signal
import sys
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlsplit

# Running `python scripts/backup_running_app.py` otherwise only adds scripts/.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from draft_assistant.workspace_state import (
    MAX_BYTES, SCHEMA_VERSION, WorkspaceConflictError, WorkspaceStorageError,
    WorkspaceVersionError, save_workspace, validate_workspace,
)


def local_origin(value: str) -> str:
    parsed = urlsplit(value)
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("The app origin must include a valid port.") from exc
    if (parsed.scheme != "http" or parsed.hostname != "127.0.0.1"
            or parsed.username or parsed.password or parsed.path or parsed.query
            or parsed.fragment or not port or not 1024 <= port <= 65535):
        raise ValueError("Use the running app's exact http://127.0.0.1:PORT origin, without a trailing slash.")
    return f"http://127.0.0.1:{port}"


def encode(value: dict) -> bytes:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")


def write_new(path: Path, content: bytes) -> None:
    """Exclusive creation: an existing recovery or workspace is never replaced."""
    with path.open("xb") as stream:
        try:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        except BaseException:
            stream.close()
            path.unlink(missing_ok=True)
            raise


def replace_bytes(path: Path, content: bytes) -> None:
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".draft-backup-", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


@contextmanager
def temporary_bridge(index: Path, script_url: str, backup: Path):
    if index.name != "index.html" or index.is_symlink() or not index.is_file():
        raise ValueError("--index must name the installed app's regular static/index.html file.")
    original = index.read_bytes()
    if b"draft-assistant-legacy-backup" in original:
        raise ValueError("An earlier backup bridge is still installed. Restore its original index first.")
    marker = b"<head>"
    if original.count(marker) != 1 or b"Draft Assistant" not in original:
        raise ValueError("The selected index does not match the Draft Assistant page.")
    # Runs before the old app can initialize defaults or change its storage.
    tag = f'\n<script data-draft-assistant-legacy-backup src="{script_url}"></script>'.encode("ascii")
    patched = original.replace(marker, marker + tag, 1)
    write_new(backup, original)
    try:
        replace_bytes(index, patched)
        yield
    finally:
        current = index.read_bytes()
        if current == patched:
            replace_bytes(index, original)
        elif current != original:
            raise RuntimeError(f"The installed index changed during backup. It was not overwritten. Original: {backup}")


def workspace_from_legacy(value: dict) -> dict:
    if not isinstance(value, dict) or set(value) != {"fda_leagues", "fda_picks", "fda_tweaks"}:
        raise ValueError("The backup must contain exactly the three Draft Assistant storage keys.")
    state = {"schemaVersion": SCHEMA_VERSION, "revision": 0,
             "leagues": value["fda_leagues"], "picks": value["fda_picks"],
             "preferences": {"tweaks": value["fda_tweaks"]}}
    validate_workspace(state)
    if not state["leagues"]:
        raise ValueError("No saved leagues were found. Keep the old app open; an empty backup cannot confirm recovery.")
    if not isinstance(value["fda_tweaks"], dict):
        raise ValueError("The saved engine preferences are invalid.")
    return state


class Recovery:
    def __init__(self, data_dir: Path, recovery_path: Path):
        self.data_dir = data_dir
        self.recovery_path = recovery_path
        self.result: dict | None = None

    def capture(self, value: dict) -> dict:
        if self.result is not None:
            return self.result
        state = workspace_from_legacy(value)
        raw = encode(state)
        if len(raw) > MAX_BYTES:
            raise ValueError("The workspace exceeds the supported backup size.")
        write_new(self.recovery_path, raw)
        # Verify the exact bytes written without printing any league contents.
        digest = hashlib.sha256(raw).hexdigest()
        if hashlib.sha256(self.recovery_path.read_bytes()).hexdigest() != digest:
            raise OSError("The recovery file could not be verified.")
        previous_home = os.environ.get("DRAFT_ASSISTANT_HOME")
        os.environ["DRAFT_ASSISTANT_HOME"] = str(self.data_dir)
        try:
            # The shared cross-process lock and revision 0 comparison prevent
            # another app window's existing workspace from being replaced.
            save_workspace(state)
            created = True
        except (WorkspaceConflictError, WorkspaceStorageError, WorkspaceVersionError):
            created = False
        finally:
            if previous_home is None:
                os.environ.pop("DRAFT_ASSISTANT_HOME", None)
            else:
                os.environ["DRAFT_ASSISTANT_HOME"] = previous_home
        self.result = {"leagueCount": len(state["leagues"]),
                       "pickCount": sum(len(rows) for rows in state["picks"].values()),
                       "sha256": digest, "recoveryFile": str(self.recovery_path),
                       "workspaceCreated": created}
        return self.result


def backup_script(origin: str, receiver: str, nonce: str) -> bytes:
    return ("""(() => {
  'use strict';
  if (window.location.origin !== ORIGIN) return;
  const notice = (message, ok) => {
    const show = () => {
      const box = document.createElement('div');
      box.setAttribute('role', 'status');
      box.textContent = message;
      Object.assign(box.style, {position:'fixed', zIndex:'2147483647', top:'0', left:'0', right:'0',
        padding:'16px', background:ok ? '#d1fae5' : '#fee2e2', color:'#111827', font:'16px system-ui'});
      document.body.appendChild(box);
    };
    document.body ? show() : document.addEventListener('DOMContentLoaded', show, {once:true});
  };
  let data;
  try {
    data = {
      fda_leagues: JSON.parse(localStorage.getItem('fda_leagues') || '[]'),
      fda_picks: JSON.parse(localStorage.getItem('fda_picks') || '{}'),
      fda_tweaks: JSON.parse(localStorage.getItem('fda_tweaks') || '{}')
    };
    if (!Array.isArray(data.fda_leagues) || !data.fda_leagues.length) throw new Error();
  } catch {
    notice('Backup could not read saved leagues. Keep this app window open.', false);
    return;
  }
  fetch(ENDPOINT, {method:'POST', credentials:'omit', headers:{'Content-Type':'application/json'},
      body:JSON.stringify(data)})
    .then(async response => {
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || 'Backup failed.');
      notice('Backup verified: ' + result.leagueCount + ' league(s) saved. ' +
        (result.workspaceCreated ? 'Your saved data is ready for the update.' :
         'A recovery file was saved. Keep this window open until that file is imported into the updated app.'), true);
    }).catch(() => notice('Backup was not confirmed. Keep this app window open and check the backup command.', false));
})();
""".replace("ORIGIN", json.dumps(origin)).replace("ENDPOINT", json.dumps(f"{receiver}/{nonce}/capture"))).encode("utf-8")


def receiver_handler(origin: str, nonce: str, recovery: Recovery):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def reply(self, status: int, content: bytes = b"", content_type: str = "application/json"):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-store")
            if self.headers.get("Origin") == origin:
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Vary", "Origin")
            self.end_headers()
            self.wfile.write(content)

        def permitted(self) -> bool:
            expected_host = f"127.0.0.1:{self.server.server_port}"
            return self.headers.get("Host") == expected_host and self.headers.get("Origin") == origin

        def do_GET(self):
            referer = self.headers.get("Referer", "")
            parsed = urlsplit(referer)
            if (self.headers.get("Host") != f"127.0.0.1:{self.server.server_port}"
                    or f"{parsed.scheme}://{parsed.netloc}" != origin
                    or self.path != f"/{nonce}/backup.js"):
                self.reply(403)
                return
            receiver = f"http://127.0.0.1:{self.server.server_port}"
            self.reply(200, backup_script(origin, receiver, nonce), "application/javascript; charset=utf-8")

        def do_OPTIONS(self):
            if (not self.permitted() or self.path != f"/{nonce}/capture"
                    or self.headers.get("Access-Control-Request-Method") != "POST"):
                self.reply(403)
                return
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Allow-Methods", "POST")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Content-Length", "0")
            self.end_headers()

        def do_POST(self):
            if not self.permitted() or self.path != f"/{nonce}/capture":
                self.reply(403)
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= MAX_BYTES or self.headers.get_content_type() != "application/json":
                    raise ValueError("Invalid backup request size or content type.")
                self.connection.settimeout(10)
                raw = self.rfile.read(length)
                if len(raw) != length:
                    raise ValueError("The backup request was incomplete.")
                value = json.loads(raw)
                result = recovery.capture(value)
            except (ValueError, UnicodeError, RecursionError) as exc:
                self.reply(400, encode({"error": str(exc)}))
                return
            except OSError:
                self.reply(500, encode({"error": "The backup could not be saved. Keep the old app open."}))
                return
            self.reply(200, encode(result))
    return Handler


class BackupServer(HTTPServer):
    def get_request(self):
        connection, address = super().get_request()
        # A partial local request must not keep the temporary patch installed
        # indefinitely while the main loop is trying to reach its deadline.
        connection.settimeout(10)
        return connection, address


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--origin", type=local_origin, required=True)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--timeout", type=int, default=600, help="Seconds to await a refresh (1-600).")
    args = parser.parse_args()
    if not 1 <= args.timeout <= 600:
        parser.error("--timeout must be between 1 and 600 seconds")
    data_dir = args.data_dir.resolve()
    recovery_dir = data_dir / "backups" / "legacy-recovery"
    recovery_dir.mkdir(parents=True, exist_ok=True)
    label = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + secrets.token_hex(4)
    recovery = Recovery(data_dir, recovery_dir / f"workspace-{label}.json")
    nonce = secrets.token_urlsafe(24)
    # SIGTERM uses the same finally cleanup as Ctrl+C rather than leaving a patch.
    def interrupted(*_):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, interrupted)
    try:
        with BackupServer(("127.0.0.1", 0), receiver_handler(args.origin, nonce, recovery)) as server:
            server.timeout = 1
            script_url = f"http://127.0.0.1:{server.server_port}/{nonce}/backup.js"
            backup = recovery_dir / f"original-index-{label}.html"
            with temporary_bridge(args.index.resolve(), script_url, backup):
                print("Reload the same existing Draft Assistant window using its supported reload control.", flush=True)
                print("Standard older native windows disable reload; do not restart them. See docs/UPGRADING.md.", flush=True)
                print(f"Waiting up to {args.timeout} seconds for a verified local backup.", flush=True)
                deadline = time.monotonic() + args.timeout
                while recovery.result is None and time.monotonic() < deadline:
                    server.handle_request()
                if recovery.result is None:
                    print("No backup received. The original app page has been restored; keep the old window open.", flush=True)
                    return 2
                print(json.dumps(recovery.result), flush=True)
        print("Original installed app page restored. Backup complete.", flush=True)
        return 0
    except KeyboardInterrupt:
        print("Backup interrupted. Keep the old app window open.", file=sys.stderr)
        return 130
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"Backup stopped: {exc} Keep the old app window open.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
