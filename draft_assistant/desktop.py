"""Launch Draft Assistant as a native desktop window via pywebview."""
from __future__ import annotations

import socket
import threading
from functools import partial
from http.server import ThreadingHTTPServer

from .profiles import DEFAULT_PROFILE, ensure_profile, load_profile_config
from .providers.base import build_provider
from .sample_data import sample_players
from .storage import save_players
from .web.server import DraftAPIHandler


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


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


def run_desktop(profile: str = DEFAULT_PROFILE, debug: bool = False) -> None:
    try:
        import webview
    except ImportError:
        print("pywebview is required for desktop mode.")
        print("Install it with:  pip install -r requirements-desktop.txt")
        raise SystemExit(1)

    _ensure_data(profile)

    port = _find_free_port()
    handler = partial(DraftAPIHandler, profile=profile)
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
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
    webview.start(debug=debug)
    server.shutdown()
