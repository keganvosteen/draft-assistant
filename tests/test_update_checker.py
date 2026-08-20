import json
import unittest

from draft_assistant.update_checker import (
    check_for_update,
    clear_update_cache,
    parse_stable_version,
)


class _Response:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, _limit=-1):
        return self.payload


def _release(version="v0.3.0", prerelease=False):
    return {
        "tag_name": version, "draft": False, "prerelease": prerelease,
        "html_url": f"https://github.com/example/releases/{version}",
        "published_at": "2026-09-01T00:00:00Z", "body": "Changes",
        "assets": [
            {"name": "DraftAssistant-Setup-0.3.0.exe", "browser_download_url": "https://github.com/example/win.exe", "digest": "sha256:win"},
            {"name": "DraftAssistant-0.3.0-universal2.dmg", "browser_download_url": "https://github.com/example/mac.dmg", "digest": "sha256:mac"},
        ],
    }


class TestUpdateChecker(unittest.TestCase):
    def setUp(self):
        clear_update_cache()

    def test_stable_version_parser_rejects_prerelease_shapes(self):
        self.assertEqual(parse_stable_version("v1.2.3"), (1, 2, 3))
        self.assertIsNone(parse_stable_version("1.2.3-beta"))

    def test_source_checkout_does_not_make_network_request(self):
        def fail(*_args, **_kwargs):
            raise AssertionError("network should not be called")
        result = check_for_update("0.2.0", packaged=False, opener=fail)
        self.assertFalse(result["supported"])

    def test_windows_selects_exe_and_reports_newer_release(self):
        result = check_for_update(
            "0.2.0", packaged=True, platform="win32",
            opener=lambda *_args, **_kwargs: _Response(_release()), force=True,
        )
        self.assertTrue(result["updateAvailable"])
        self.assertTrue(result["downloadUrl"].endswith("win.exe"))
        self.assertEqual(result["digest"], "sha256:win")

    def test_macos_prefers_universal_dmg(self):
        result = check_for_update(
            "0.2.0", packaged=True, platform="darwin",
            opener=lambda *_args, **_kwargs: _Response(_release()), force=True,
        )
        self.assertTrue(result["downloadUrl"].endswith("mac.dmg"))

    def test_equal_or_prerelease_is_not_offered(self):
        equal = check_for_update(
            "0.3.0", packaged=True, platform="win32",
            opener=lambda *_args, **_kwargs: _Response(_release()), force=True,
        )
        self.assertFalse(equal["updateAvailable"])
        clear_update_cache()
        pre = check_for_update(
            "0.2.0", packaged=True, platform="win32",
            opener=lambda *_args, **_kwargs: _Response(_release(prerelease=True)), force=True,
        )
        self.assertFalse(pre["updateAvailable"])
        self.assertIn("stable", pre["error"])


if __name__ == "__main__":
    unittest.main()
