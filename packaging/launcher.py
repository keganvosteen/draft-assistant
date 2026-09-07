"""Entry point for the packaged Windows/macOS builds.

Prefers a native window (pywebview). If the webview backend is missing or
fails to start, falls back to serving the same UI and opening the default
browser, so a bad WebView2/WKWebView install degrades instead of dead-ending.

Unlike the old portable build this never chdir()s to the executable folder:
paths.py routes mutable state to the per-user data directory instead, which is
what lets the app be installed somewhere read-only.
"""
from __future__ import annotations

import os
import socket
import sys
import traceback

from draft_assistant.paths import seed_user_data
from draft_assistant.profiles import DEFAULT_PROFILE


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _run_native(profile: str) -> bool:
    """Return True if the native window ran; False to fall back to a browser."""
    try:
        import webview  # noqa: F401
    except ImportError:
        return False
    try:
        from draft_assistant.desktop import run_desktop

        run_desktop(profile=profile)
        return True
    except Exception:
        # A missing WebView2 runtime surfaces here rather than at import.
        traceback.print_exc()
        return False


def _run_browser(profile: str) -> None:
    from draft_assistant.cli import launch_web_ui

    no_open = "--no-open" in sys.argv or os.environ.get("DRAFT_ASSISTANT_NO_OPEN") == "1"
    port = int(os.environ.get("DRAFT_ASSISTANT_PORT") or _find_free_port())
    launch_web_ui(profile=profile, port=port, no_open=no_open)


def main() -> None:
    seed_user_data()
    profile = os.environ.get("DRAFT_ASSISTANT_PROFILE") or DEFAULT_PROFILE

    if "--browser" not in sys.argv and _run_native(profile):
        return
    _run_browser(profile)


if __name__ == "__main__":
    main()
