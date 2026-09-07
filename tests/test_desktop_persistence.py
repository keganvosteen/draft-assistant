"""The desktop wrapper must not discard storage or leak its local server."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from draft_assistant.desktop import DesktopAPI, run_desktop


class DesktopPersistenceTests(unittest.TestCase):
    def test_pending_save_delays_close_and_success_closes_once(self):
        api = DesktopAPI()
        api._window = MagicMock()
        api._window.evaluate_js.side_effect = [True, None, False]
        self.assertFalse(api.request_close())
        self.assertFalse(api.request_close())
        api._window.destroy.assert_not_called()
        self.assertTrue(api.close_after_save())
        self.assertIsNone(api.request_close())
        api._window.destroy.assert_called_once()

    def test_failed_save_keeps_window_open_and_can_retry(self):
        api = DesktopAPI()
        api._window = MagicMock()
        api._window.evaluate_js.side_effect = [True, None, None, True, None]
        self.assertFalse(api.request_close())
        self.assertFalse(api.close_save_failed())
        self.assertFalse(api.request_close())
        api._window.destroy.assert_not_called()

    def test_new_edit_during_close_and_unsolicited_callback_cannot_destroy_window(self):
        api = DesktopAPI()
        api._window = MagicMock()
        self.assertFalse(api.close_after_save())
        api._window.evaluate_js.side_effect = [True, None, True]
        self.assertFalse(api.request_close())
        self.assertFalse(api.close_after_save())
        api._window.destroy.assert_not_called()

    def test_relaunch_and_new_install_location_keep_the_same_browser_directory(self):
        with tempfile.TemporaryDirectory() as root:
            browser = Path(root) / "webview"
            fake = MagicMock()
            server = MagicMock(server_address=("127.0.0.1", 54321))
            with patch.dict("sys.modules", {"webview": fake}), \
                    patch("draft_assistant.desktop.resolve", return_value=str(browser)), \
                    patch("draft_assistant.desktop._ensure_data"), \
                    patch("draft_assistant.desktop.ThreadingHTTPServer", return_value=server) as bind, \
                    patch("draft_assistant.desktop.threading.Thread"):
                run_desktop()
                marker = browser / "saved-profile-marker"
                marker.write_text("retain", encoding="utf-8")
                run_desktop(debug=True)
            self.assertEqual(marker.read_text(encoding="utf-8"), "retain")
            for call in fake.start.call_args_list:
                self.assertFalse(call.kwargs["private_mode"])
                self.assertEqual(call.kwargs["storage_path"], str(browser))
            self.assertEqual(bind.call_args.args[0], ("127.0.0.1", 0))
            fake.settings.__setitem__.assert_called_with("ALLOW_DOWNLOADS", True)
            self.assertEqual(server.server_close.call_count, 2)

    def test_browser_failure_closes_local_server(self):
        with tempfile.TemporaryDirectory() as root:
            fake = MagicMock()
            fake.start.side_effect = RuntimeError("browser failed")
            server = MagicMock(server_address=("127.0.0.1", 54321))
            with patch.dict("sys.modules", {"webview": fake}), \
                    patch("draft_assistant.desktop.resolve", return_value=root), \
                    patch("draft_assistant.desktop._ensure_data"), \
                    patch("draft_assistant.desktop.ThreadingHTTPServer", return_value=server), \
                    patch("draft_assistant.desktop.threading.Thread"):
                with self.assertRaisesRegex(RuntimeError, "browser failed"):
                    run_desktop()
            server.shutdown.assert_called_once()
            server.server_close.assert_called_once()

    def test_open_external_url_allowlist(self):
        api = DesktopAPI()
        with patch("webbrowser.open", return_value=True) as mock_open:
            # Valid GitHub releases
            self.assertTrue(api.open_external_url("https://github.com/keganvosteen/draft-assistant/releases/tag/v0.6.0"))
            mock_open.assert_called_with("https://github.com/keganvosteen/draft-assistant/releases/tag/v0.6.0")

            # Valid Yahoo OAuth & Developer URLs
            self.assertTrue(api.open_external_url("https://api.login.yahoo.com/oauth2/request_auth?client_id=abc"))
            self.assertTrue(api.open_external_url("https://login.yahoo.com/oauth2/request_auth?client_id=abc"))
            self.assertTrue(api.open_external_url("https://sports.yahoo.com/developer/access/"))
            self.assertTrue(api.open_external_url("https://developer.yahoo.com/apps/"))

            # Disallowed URLs
            self.assertFalse(api.open_external_url("http://api.login.yahoo.com/oauth2/request_auth"))
            self.assertFalse(api.open_external_url("https://evil.com/oauth2/request_auth"))
            self.assertFalse(api.open_external_url("https://login.yahoo.com/account/security"))
            self.assertFalse(api.open_external_url("https://github.com/malicious/repo"))


