"""Small, read-only GitHub Release checker for packaged desktop builds."""
from __future__ import annotations

import json
import re
import sys
import threading
import time
from typing import Callable, Optional
from urllib.request import Request, urlopen

from .paths import is_frozen


LATEST_RELEASE_URL = (
    "https://api.github.com/repos/keganvosteen/draft-assistant/releases/latest"
)
CACHE_SECONDS = 6 * 60 * 60
_VERSION_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")
_cache_lock = threading.Lock()
_cache: dict[tuple[str, str, bool], tuple[float, dict]] = {}


def parse_stable_version(value: object) -> Optional[tuple[int, int, int]]:
    match = _VERSION_RE.fullmatch(str(value or "").strip())
    return tuple(int(part) for part in match.groups()) if match else None


def _platform_asset(assets: object, platform: str) -> Optional[dict]:
    if not isinstance(assets, list):
        return None
    suffix = ".exe" if platform == "win32" else ".dmg" if platform == "darwin" else None
    if suffix is None:
        return None
    candidates = [
        asset for asset in assets
        if isinstance(asset, dict)
        and str(asset.get("name") or "").lower().endswith(suffix)
    ]
    if platform == "darwin":
        universal = [asset for asset in candidates if "universal" in str(asset.get("name", "")).lower()]
        if universal:
            candidates = universal
    return candidates[0] if candidates else None


def _read_latest(opener: Callable = urlopen) -> dict:
    request = Request(LATEST_RELEASE_URL, headers={
        "User-Agent": "DraftAssistant/0.3 (+https://github.com/keganvosteen/draft-assistant)",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    })
    with opener(request, timeout=5) as response:
        raw = response.read(512 * 1024 + 1)
    if len(raw) > 512 * 1024:
        raise ValueError("GitHub release response was unexpectedly large")
    data = json.loads(raw.decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError("unexpected GitHub release response")
    return data


def check_for_update(current_version: str, *, platform: Optional[str] = None,
                     packaged: Optional[bool] = None, opener: Callable = urlopen,
                     now: Optional[float] = None, force: bool = False) -> dict:
    """Return a platform-specific release notice without downloading anything."""
    platform = platform or sys.platform
    packaged = is_frozen() if packaged is None else bool(packaged)
    now = time.time() if now is None else float(now)
    base = {
        "currentVersion": current_version,
        "supported": packaged and platform in {"win32", "darwin"},
        "updateAvailable": False,
        "latestVersion": None,
        "releaseUrl": None,
        "downloadUrl": None,
        "assetName": None,
        "digest": None,
        "publishedAt": None,
        "releaseNotes": None,
        "error": None,
    }
    if not base["supported"]:
        return base

    key = (current_version, platform, packaged)
    with _cache_lock:
        cached = _cache.get(key)
        if cached and not force and now - cached[0] < CACHE_SECONDS:
            return dict(cached[1])

    try:
        release = _read_latest(opener)
        if release.get("draft") or release.get("prerelease"):
            raise ValueError("latest release is not stable")
        current = parse_stable_version(current_version)
        latest = parse_stable_version(release.get("tag_name"))
        if current is None or latest is None:
            raise ValueError("release versions must use vMAJOR.MINOR.PATCH")
        asset = _platform_asset(release.get("assets"), platform)
        latest_text = ".".join(str(part) for part in latest)
        base.update({
            "latestVersion": latest_text,
            "updateAvailable": bool(latest > current and asset),
            "releaseUrl": release.get("html_url"),
            "downloadUrl": asset.get("browser_download_url") if asset else None,
            "assetName": asset.get("name") if asset else None,
            "digest": asset.get("digest") if asset else None,
            "publishedAt": release.get("published_at"),
            "releaseNotes": str(release.get("body") or "")[:12000],
        })
    except Exception as exc:
        base["error"] = str(exc)

    with _cache_lock:
        _cache[key] = (now, dict(base))
    return base


def clear_update_cache() -> None:
    with _cache_lock:
        _cache.clear()
