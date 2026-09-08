"""Credentials must never land on disk in the clear.

The store is exercised against a stand-in for the platform keystore, so these
run the same on CI (which has neither DPAPI nor a Keychain) as on Windows.
"""
import json
import os
import tempfile
import unittest
from unittest.mock import patch

from draft_assistant import secret_store


def _fake_dpapi(data: bytes, protect: bool) -> bytes:
    """Reversible stand-in for CryptProtectData — round-trips, not secure."""
    return bytes(b ^ 0x5A for b in data)


class TestSecretStore(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "espn.json")
        self.data = {"1440816112": {"espnS2": "AEAw%2Fsecret", "swid": "{ABC-123}"}}

    def test_without_a_keystore_nothing_is_written(self):
        # Refusing beats writing plaintext: the caller keeps the secret in
        # memory for the session instead.
        with patch.object(secret_store, "backend", return_value="none"):
            self.assertFalse(secret_store.save(self.path, "espn", self.data))
        self.assertFalse(os.path.exists(self.path))

    def test_sealed_file_holds_no_cleartext(self):
        with patch.object(secret_store, "backend", return_value="dpapi"), \
             patch.object(secret_store, "_dpapi", side_effect=_fake_dpapi):
            secret_store.save(self.path, "espn", self.data)
            body = open(self.path, encoding="utf-8").read()
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

    def test_a_pre_existing_plaintext_file_still_loads(self):
        # yahoo.json predates this module; an upgrade must not lose the token.
        legacy = {"client_id": "abc", "token": {"access_token": "xyz"}}
        with open(self.path, "w", encoding="utf-8") as handle:
            json.dump(legacy, handle)
        with patch.object(secret_store, "backend", return_value="dpapi"):
            self.assertEqual(secret_store.load(self.path, "yahoo"), legacy)
            self.assertFalse(secret_store.is_sealed(self.path))

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


if __name__ == "__main__":
    unittest.main()
