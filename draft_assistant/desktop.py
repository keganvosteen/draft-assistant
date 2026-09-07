"""Launch Draft Assistant as a native desktop window via pywebview."""
from __future__ import annotations

import threading
import webbrowser
from functools import partial
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from .profiles import DEFAULT_PROFILE, ensure_profile, load_profile_config
from .paths import resolve
from .providers.base import build_provider
from .sample_data import sample_players
from .storage import save_players
from .web.server import DraftAPIHandler


def _ensure_data(profile: str) -> None:
    paths = ensure_profile(profile)
    config = load_profile_config(paths)
    provider = build_provider(config.provider)
    if not provider.fetch_players():
        save_players(sample_players(), paths.projections_path)


class DesktopAPI:
    """Exposed to JS as window.pywebview.api.*"""

    def __init__(self):
        self._window = None
        self._close_requested = False
        self._allow_close = False
        self._close_lock = threading.Lock()

    def request_close(self):
        """Keep the window alive until its pending league save is acknowledged."""
        with self._close_lock:
            if self._allow_close:
                return None
            if self._close_requested:
                return False
            self._close_requested = True
        pending = False
        try:
            pending = self._window.evaluate_js("Boolean(window.__fdaHasPendingWrites?.())")
            if not pending:
                self._close_requested = False
                return None
            self._window.evaluate_js("""void window.__fdaFlushForClose()
                .then(() => window.pywebview.api.close_after_save())
                .catch(() => window.pywebview.api.close_save_failed());""")
        except Exception:
            self._close_requested = False
            # An uninitialized/failed page has no active frontend edits.
            if not pending:
                return None
        return False

    def close_after_save(self) -> bool:
        if not self._close_requested or not self._window:
            return False
        # A new edit can arrive after flush resolves but before this callback.
        if self._window.evaluate_js("Boolean(window.__fdaHasPendingWrites?.())"):
            self._close_requested = False
            return False
        self._allow_close = True
        self._window.destroy()
        return True

    def close_save_failed(self) -> bool:
        if not self._close_requested or not self._window:
            return False
        self._close_requested = False
        self._allow_close = False
        self._window.evaluate_js("""void window.toast?.(
            'The app stayed open because changes could not be saved. Retry saving or export a backup.',
            'error', 10000);""")
        return False

    def open_file_dialog(self, title="Select CSV", file_types=("CSV files (*.csv)",)):
        if not self._window:
            return None
        result = self._window.create_file_dialog(
            0,  # webview.OPEN_DIALOG
            allow_multiple=False,
            file_types=file_types,
        )
        if result and len(result) > 0:
            return str(result[0])
        return None

    def open_external_url(self, url: str) -> bool:
        """Open project HTTPS release links and Yahoo OAuth in the system browser."""
        parsed = urlsplit(str(url or ""))
        if parsed.scheme != "https":
            return False
        is_release = (
            parsed.hostname == "github.com"
            and parsed.path.startswith("/keganvosteen/draft-assistant/releases/")
        )
        is_yahoo = (
            (parsed.hostname in ("api.login.yahoo.com", "login.yahoo.com") and parsed.path.startswith("/oauth2/"))
            or (parsed.hostname == "sports.yahoo.com" and parsed.path.startswith("/developer"))
            or (parsed.hostname == "developer.yahoo.com")
        )
        if not (is_release or is_yahoo):
            return False
        return bool(webbrowser.open(url))


def run_desktop(profile: str = DEFAULT_PROFILE, debug: bool = False) -> None:
    try:
        import webview
    except ImportError:
        print("pywebview is required for desktop mode.")
        print("Install it with:  pip install -r requirements-desktop.txt")
        raise SystemExit(1)

    _ensure_data(profile)

    handler = partial(DraftAPIHandler, profile=profile)
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    api = DesktopAPI()
    url = f"http://127.0.0.1:{port}"
    window = webview.create_window(
        "Draft Assistant",
        url,
        width=1280,
        height=800,
        min_size=(900, 600),
        js_api=api,
    )
    api._window = window
    window.events.closing += api.request_close
    # League state is saved separately by /api/workspace. Keep browser caches
    # and pending-write recovery across upgrades too, outside the program files.
    browser_data = Path(resolve("webview")).resolve()
    browser_data.mkdir(parents=True, exist_ok=True)
    webview.settings["ALLOW_DOWNLOADS"] = True  # User-requested JSON/CSV exports.
    try:
        webview.start(debug=debug, private_mode=False, storage_path=str(browser_data))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
