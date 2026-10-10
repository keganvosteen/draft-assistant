"""Credentials must never land on disk in the clear.

The store is exercised against a stand-in for the platform keystore, so these
run the same on CI (which has neither DPAPI nor a Keychain) as on Windows.
"""
import json
import base64
import os
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from draft_assistant import secret_store


def _fake_dpapi(data: bytes, protect: bool) -> bytes:
    """Reversible stand-in for CryptProtectData — round-trips, not secure."""
    return bytes(b ^ 0x5A for b in data)


class TestSecretStore(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.dir = directory.name
        self.path = os.path.join(self.dir, "espn.json")
        self.data = {"1440816112": {"espnS2": "AEAw%2Fsecret", "swid": "{ABC-123}"}}
        self.addCleanup(secret_store._session.clear)

    def test_without_a_keystore_nothing_is_written(self):
        # Refusing beats writing plaintext: the caller keeps the secret in
        # memory for the session instead.
        with patch.object(secret_store, "backend", return_value="none"):
            self.assertFalse(secret_store.save(self.path, "espn", self.data))
            self.assertEqual(secret_store.load(self.path, "espn"), self.data)
        self.assertFalse(os.path.exists(self.path))

    def test_session_values_are_isolated_by_path_provider_and_copy(self):
        second = os.path.join(self.dir, "other", "espn.json")
        with patch.object(secret_store, "backend", return_value="none"):
            secret_store.save(self.path, "espn", self.data)
            self.assertEqual(secret_store.load(second, "espn"), {})
            self.assertEqual(secret_store.load(self.path, "yahoo"), {})
            loaded = secret_store.load(self.path, "espn")
            loaded["1440816112"]["espnS2"] = "changed"
            self.assertEqual(secret_store.load(self.path, "espn"), self.data)
            secret_store.forget(self.path, "espn")
            self.assertEqual(secret_store.load(self.path, "espn"), {})

    def test_sealed_file_holds_no_cleartext(self):
        with patch.object(secret_store, "backend", return_value="dpapi"), \
             patch.object(secret_store, "_dpapi", side_effect=_fake_dpapi):
            secret_store.save(self.path, "espn", self.data)
            with open(self.path, encoding="utf-8") as handle:
                body = handle.read()
            self.assertNotIn("AEAw", body)
            self.assertNotIn("ABC-123", body)
            self.assertEqual(json.loads(body)["magic"], "draft-assistant-secret-v1")
            self.assertTrue(secret_store.is_sealed(self.path))
            self.assertEqual(secret_store.load(self.path, "espn"), self.data)

    def test_a_file_sealed_by_another_backend_is_not_guessed_at(self):
        with patch.object(secret_store, "backend", return_value="dpapi"), \
             patch.object(secret_store, "_dpapi", side_effect=_fake_dpapi):
            secret_store.save(self.path, "espn", self.data)
        # Moving the profile to a different OS must not produce garbage.
        with patch.object(secret_store, "backend", return_value="keychain"):
            self.assertEqual(secret_store.load(self.path, "espn"), {})

    def test_existing_v1_dpapi_payload_remains_readable(self):
        legacy = {"magic": "draft-assistant-secret-v1", "backend": "dpapi",
                  "account": "espn", "sealed": base64.b64encode(
                      _fake_dpapi(json.dumps(self.data).encode("utf-8"), True)).decode("ascii")}
        with open(self.path, "w", encoding="utf-8") as handle:
            json.dump(legacy, handle)
        with patch.object(secret_store, "backend", return_value="dpapi"), \
             patch.object(secret_store, "_dpapi", side_effect=_fake_dpapi):
            self.assertEqual(secret_store.load(self.path, "espn"), self.data)

    def test_a_pre_existing_plaintext_file_is_sealed_when_loaded(self):
        # yahoo.json predates this module; an upgrade must not lose the token.
        legacy = {"client_id": "abc", "token": {"access_token": "xyz"}}
        with open(self.path, "w", encoding="utf-8") as handle:
            json.dump(legacy, handle)
        with patch.object(secret_store, "backend", return_value="dpapi"), \
             patch.object(secret_store, "_dpapi", side_effect=_fake_dpapi):
            self.assertEqual(secret_store.load(self.path, "yahoo"), legacy)
            self.assertTrue(secret_store.is_sealed(self.path))
            self.assertEqual(secret_store.load(self.path, "yahoo"), legacy)

    def test_plaintext_migrates_to_memory_without_a_keystore(self):
        with open(self.path, "w", encoding="utf-8") as handle:
            json.dump(self.data, handle)
        with patch.object(secret_store, "backend", return_value="none"):
            self.assertEqual(secret_store.load(self.path, "espn"), self.data)
            self.assertFalse(os.path.exists(self.path))
            self.assertEqual(secret_store.load(self.path, "espn"), self.data)
            # A new process has no session values and must authorize again.
            secret_store._session.clear()
            self.assertEqual(secret_store.load(self.path, "espn"), {})

    def test_failed_plaintext_migration_preserves_original(self):
        with open(self.path, "w", encoding="utf-8") as handle:
            json.dump(self.data, handle)
        with patch.object(secret_store, "backend", return_value="dpapi"), \
             patch.object(secret_store, "_dpapi", side_effect=OSError("unavailable")):
            with self.assertRaises(OSError):
                secret_store.load(self.path, "espn")
        with open(self.path, encoding="utf-8") as handle:
            self.assertEqual(json.load(handle), self.data)

    def test_forget_removes_the_file(self):
        with patch.object(secret_store, "backend", return_value="dpapi"), \
             patch.object(secret_store, "_dpapi", side_effect=_fake_dpapi):
            secret_store.save(self.path, "espn", self.data)
            secret_store.forget(self.path, "espn")
        self.assertFalse(os.path.exists(self.path))
        self.assertEqual(secret_store.load(self.path, "espn"), {})

    def test_saving_empty_clears_the_store(self):
        with patch.object(secret_store, "backend", return_value="dpapi"), \
             patch.object(secret_store, "_dpapi", side_effect=_fake_dpapi):
            secret_store.save(self.path, "espn", self.data)
            self.assertTrue(secret_store.save(self.path, "espn", {}))
        self.assertFalse(os.path.exists(self.path))

    def test_corrupt_file_reads_as_empty_rather_than_raising(self):
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write("{not json")
        self.assertEqual(secret_store.load(self.path, "espn"), {})
        self.assertFalse(secret_store.is_sealed(self.path))


class TestKeychainProfiles(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.first = os.path.join(directory.name, "one", "yahoo.json")
        self.second = os.path.join(directory.name, "two", "yahoo.json")
        self.entries = {}
        for name, options in (
                ("backend", {"return_value": "keychain"}),
                ("_keychain_read", {"side_effect": self.entries.get}),
                ("_keychain_write", {"side_effect": self.entries.__setitem__}),
                ("_keychain_delete", {"side_effect": lambda key: self.entries.pop(key, None)})):
            mock = patch.object(secret_store, name, **options)
            mock.start()
            self.addCleanup(mock.stop)

    def _legacy_marker(self, path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump({"magic": secret_store._MAGIC, "backend": "keychain",
                       "account": "yahoo"}, handle)

    def test_same_provider_in_two_profiles_is_independent(self):
        secret_store.save(self.first, "yahoo", {"token": "one"})
        secret_store.save(self.second, "yahoo", {"token": "two"})
        self.assertEqual(secret_store.load(self.first, "yahoo"), {"token": "one"})
        self.assertEqual(secret_store.load(self.second, "yahoo"), {"token": "two"})
        secret_store.forget(self.first, "yahoo")
        self.assertEqual(secret_store.load(self.second, "yahoo"), {"token": "two"})
        self.assertEqual(len(self.entries), 1)

    def test_account_uses_canonical_path_and_provider(self):
        alias = os.path.join(os.path.dirname(self.first), ".", "yahoo.json")
        self.assertEqual(secret_store._keychain_account(self.first, "yahoo"),
                         secret_store._keychain_account(alias, "yahoo"))
        self.assertNotEqual(secret_store._keychain_account(self.first, "yahoo"),
                            secret_store._keychain_account(self.first, "espn"))

    def test_copied_marker_cannot_read_a_different_profiles_credentials(self):
        import shutil
        secret_store.save(self.first, "yahoo", {"token": "one"})
        os.makedirs(os.path.dirname(self.second), exist_ok=True)
        shutil.copyfile(self.first, self.second)
        self.assertEqual(secret_store.load(self.second, "yahoo"), {})
        secret_store.forget(self.second, "yahoo")
        self.assertEqual(secret_store.load(self.first, "yahoo"), {"token": "one"})

    def test_legacy_migration_copies_without_deleting_shared_credentials(self):
        self.entries["yahoo"] = json.dumps({"token": "legacy"})
        self._legacy_marker(self.first)
        self._legacy_marker(self.second)
        self.assertEqual(secret_store.load(self.first, "yahoo"), {"token": "legacy"})
        secret_store.forget(self.first, "yahoo")
        self.assertIn("yahoo", self.entries)
        self.assertEqual(secret_store.load(self.second, "yahoo"), {"token": "legacy"})

    def test_forgetting_a_legacy_marker_does_not_delete_shared_credentials(self):
        self.entries["yahoo"] = json.dumps({"token": "legacy"})
        self._legacy_marker(self.first)
        secret_store.forget(self.first, "yahoo")
        self.assertIn("yahoo", self.entries)
        self.assertFalse(os.path.exists(self.first))

    def test_failed_legacy_keychain_migration_preserves_shared_item_and_marker(self):
        self.entries["yahoo"] = json.dumps({"token": "legacy"})
        self._legacy_marker(self.first)
        with patch.object(secret_store, "_keychain_write", side_effect=OSError("unavailable")):
            with self.assertRaises(OSError):
                secret_store.load(self.first, "yahoo")
        with open(self.first, encoding="utf-8") as handle:
            self.assertEqual(json.load(handle)["account"], "yahoo")
        self.assertEqual(self.entries["yahoo"], json.dumps({"token": "legacy"}))


class TestKeychainErrors(unittest.TestCase):
    def test_write_error_does_not_disclose_command_line_secret(self):
        error = subprocess.CalledProcessError(1, ["security", "-w", "sensitive-token"])
        with patch.object(secret_store.subprocess, "run", side_effect=error):
            with self.assertRaises(OSError) as raised:
                secret_store._keychain_write("profile", "sensitive-token")
        self.assertNotIn("sensitive-token", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
