from __future__ import annotations

import os
import socket
import sys
from pathlib import Path

from draft_assistant.cli import launch_web_ui
from draft_assistant.profiles import DEFAULT_PROFILE


def _app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def main() -> None:
    # Profile/config/data paths are intentionally relative. In a packaged build,
    # start from the executable folder so the portable package owns its state.
    os.chdir(_app_dir())
    no_open = "--no-open" in sys.argv or os.environ.get("DRAFT_ASSISTANT_NO_OPEN") == "1"
    port = int(os.environ.get("DRAFT_ASSISTANT_PORT") or _find_free_port())
    launch_web_ui(profile=DEFAULT_PROFILE, port=port, no_open=no_open)


if __name__ == "__main__":
    main()
