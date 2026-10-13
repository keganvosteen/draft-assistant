"""Credentials must never land on disk in the clear.

The store is exercised against a stand-in for the platform keystore, so these
run the same on CI (which has neither DPAPI nor a Keychain) as on Windows.
"""
import contextlib
import io
import json
import base64
import os
import shutil
import subprocess
import tempfile
import traceback
import unittest
from unittest.mock import patch

from draft_assistant import secret_store


def _fake_dpapi(data: bytes, protect: bool) -> bytes:
    """Reversible stand-in for CryptProtectData — round-trips, not secure."""
    return bytes(b ^ 0x5A for b in data)


@contextlib.contextmanager
def unreadable(target, error=None):
    """Make the store's reads of *target* fail, as a file that is out of reach does.

    Only secret_store's own open() is replaced, so the atomic marker write in
    storage.py and the test's own file handling carry on working.
    """
    error = error or PermissionError(13, "Permission denied", target)
    real = open

    def guarded(path, *args, **kwargs):
        if os.path.abspath(os.fspath(path)) == os.path.abspath(target):
            raise error
        return real(path, *args, **kwargs)

    with patch.object(secret_store, "open", side_effect=guarded, create=True):
        yield


class TestSecretStore(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.dir = directory.name
        self.path = os.path.join(self.dir, "espn.json")
        self.data = {"1440816112": {"espnS2": "AEAw%2Fsecret", "swid": "{ABC-123}"}}
        self.addCleanup(secret_store._session.clear)
        self.addCleanup(secret_store._plaintext_removed.clear)

    def _plaintext(self, path=None, data=None):
        with open(path or self.path, "w", encoding="utf-8") as handle:
            json.dump(self.data if data is None else data, handle)

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

    def test_a_dpapi_store_still_follows_its_file_when_the_directory_moves(self):
        # DPAPI seals the payload into the file itself, so it never had the
        # Keychain's moved-directory problem. Pin that it still has no path in it.
        moved = os.path.join(self.dir, "moved", "espn.json")
        with patch.object(secret_store, "backend", return_value="dpapi"), \
             patch.object(secret_store, "_dpapi", side_effect=_fake_dpapi):
            secret_store.save(self.path, "espn", self.data)
            with open(self.path, encoding="utf-8") as handle:
                self.assertEqual(sorted(json.load(handle)), ["account", "backend", "magic", "sealed"])
            os.makedirs(os.path.dirname(moved))
            os.rename(self.path, moved)
            self.assertEqual(secret_store.load(moved, "espn"), self.data)
            self.assertEqual(secret_store.load(moved, "yahoo"), {})

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
        self._plaintext()
        with patch.object(secret_store, "backend", return_value="none"), \
             contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(secret_store.load(self.path, "espn"), self.data)
            self.assertFalse(os.path.exists(self.path))
            self.assertEqual(secret_store.load(self.path, "espn"), self.data)
            # A new process has no session values and must authorize again.
            secret_store._session.clear()
            self.assertEqual(secret_store.load(self.path, "espn"), {})

    def test_removing_a_plaintext_file_is_announced_exactly_once(self):
        # The first read deletes the only durable copy. That used to happen
        # without a word, and the credentials were simply gone after a restart.
        self._plaintext()
        stderr = io.StringIO()
        with patch.object(secret_store, "backend", return_value="none"), \
             contextlib.redirect_stderr(stderr):
            self.assertFalse(secret_store.plaintext_removed(self.path, "espn"))
            self.assertEqual(secret_store.load(self.path, "espn"), self.data)
            self.assertEqual(secret_store.load(self.path, "espn"), self.data)
            secret_store.save(self.path, "espn", self.data)
            self.assertEqual(secret_store.load(self.path, "espn"), self.data)
            self.assertTrue(secret_store.plaintext_removed(self.path, "espn"))
        notices = stderr.getvalue().splitlines()
        self.assertEqual(len(notices), 1, notices)
        self.assertTrue(notices[0].startswith("WARNING: "))
        self.assertIn(os.path.abspath(self.path), notices[0])
        self.assertIn("only in memory", notices[0])
        self.assertIn("re-entered after the app restarts", notices[0])
        self.assertNotIn("AEAw", notices[0])
        self.assertNotIn("ABC-123", notices[0])

    def test_each_removed_plaintext_file_gets_its_own_notice(self):
        other = os.path.join(self.dir, "yahoo.json")
        self._plaintext()
        self._plaintext(other, {"client_id": "abc"})
        stderr = io.StringIO()
        with patch.object(secret_store, "backend", return_value="none"), \
             contextlib.redirect_stderr(stderr):
            secret_store.load(self.path, "espn")
            secret_store.load(other, "yahoo")
            secret_store.load(self.path, "espn")
            secret_store.load(other, "yahoo")
        notices = stderr.getvalue().splitlines()
        self.assertEqual(len(notices), 2, notices)
        self.assertIn(os.path.abspath(self.path), notices[0])
        self.assertIn(os.path.abspath(other), notices[1])

    def test_nothing_is_announced_unless_a_plaintext_file_was_removed(self):
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            with patch.object(secret_store, "backend", return_value="none"):
                # Nothing on disk to lose.
                secret_store.save(self.path, "espn", self.data)
                secret_store.load(self.path, "espn")
                self.assertFalse(secret_store.plaintext_removed(self.path, "espn"))
                secret_store.forget(self.path, "espn")
            with patch.object(secret_store, "backend", return_value="dpapi"), \
                 patch.object(secret_store, "_dpapi", side_effect=_fake_dpapi):
                # Sealed in place: the credentials survive, so nothing was lost.
                self._plaintext()
                self.assertEqual(secret_store.load(self.path, "espn"), self.data)
                self.assertFalse(secret_store.plaintext_removed(self.path, "espn"))
            with patch.object(secret_store, "backend", return_value="none"):
                # Another OS's sealed file is neither readable nor ours to delete.
                self.assertEqual(secret_store.load(self.path, "espn"), {})
                secret_store.save(self.path, "espn", self.data)
                self.assertTrue(secret_store.is_sealed(self.path))
        self.assertEqual(stderr.getvalue(), "")

    def test_forgetting_ends_the_removed_plaintext_report(self):
        self._plaintext()
        with patch.object(secret_store, "backend", return_value="none"), \
             contextlib.redirect_stderr(io.StringIO()):
            secret_store.load(self.path, "espn")
            self.assertTrue(secret_store.plaintext_removed(self.path, "espn"))
            self.assertFalse(secret_store.plaintext_removed(self.path, "yahoo"))
            secret_store.forget(self.path, "espn")
            self.assertFalse(secret_store.plaintext_removed(self.path, "espn"))

    def test_describe_without_a_keystore_says_what_the_notice_says(self):
        # /api/yahoo/status and /api/espn/credentials hand this to the UI as
        # "storage"; it is the only place a user reads why a login is gone.
        with patch.object(secret_store, "backend", return_value="none"):
            text = secret_store.describe()
        self.assertIn("memory only", text)
        self.assertIn("re-entered after the app restarts", text)
        self.assertIn("deleted", text)

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

    def _marker(self, path, account=None, backend="keychain", **extra):
        """Read *path*'s marker, or write one naming *account*."""
        if account is None:
            with open(path, encoding="utf-8") as handle:
                return json.load(handle)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump({"magic": secret_store._MAGIC, "backend": backend,
                       "account": account, **extra}, handle)

    def _legacy_marker(self, path):
        self._marker(path, "yahoo")

    def _store_from_0_7_4(self, path, data):
        """What 0.7.4 left behind: an item named after a hash of the path."""
        name = secret_store._keychain_account(path, "yahoo")
        self.entries[name] = json.dumps(data)
        self._marker(path, name)
        return name

    def _move(self, source, target):
        os.rename(os.path.dirname(source), os.path.dirname(target))

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

    def test_each_store_mints_one_random_item_and_keeps_it(self):
        secret_store.save(self.first, "yahoo", {"token": "one"})
        item = self._marker(self.first)["account"]
        self.assertRegex(item, r"\Ayahoo:[0-9a-f]{32}\Z")
        # Nothing about the item may depend on where the file sits.
        self.assertNotEqual(item, secret_store._keychain_account(self.first, "yahoo"))
        self.assertEqual(sorted(self._marker(self.first)), ["account", "backend", "magic"])
        secret_store.save(self.first, "yahoo", {"token": "renewed"})
        self.assertEqual(self._marker(self.first)["account"], item)
        self.assertEqual(self.entries, {item: json.dumps({"token": "renewed"})})
        secret_store.save(self.second, "yahoo", {"token": "two"})
        self.assertNotEqual(self._marker(self.second)["account"], item)

    def test_a_moved_directory_keeps_its_credentials_and_orphans_nothing(self):
        # The item used to be named after the path, so moving the data
        # directory lost the credential and stranded the item for good.
        secret_store.save(self.first, "yahoo", {"token": "one"})
        self._move(self.first, self.second)
        self.assertEqual(secret_store.load(self.second, "yahoo"), {"token": "one"})
        secret_store.save(self.second, "yahoo", {"token": "renewed"})
        self.assertEqual(len(self.entries), 1)
        self.assertEqual(secret_store.load(self.second, "yahoo"), {"token": "renewed"})
        secret_store.forget(self.second, "yahoo")
        self.assertEqual(self.entries, {})
        self.assertFalse(os.path.exists(self.second))

    def test_a_0_7_4_marker_keeps_loading_in_place_and_after_a_move(self):
        name = self._store_from_0_7_4(self.first, {"token": "old"})
        self.assertEqual(secret_store.load(self.first, "yahoo"), {"token": "old"})
        self._move(self.first, self.second)
        self.assertEqual(secret_store.load(self.second, "yahoo"), {"token": "old"})
        # The recorded name is the id now: reused as it stands, never re-derived.
        secret_store.save(self.second, "yahoo", {"token": "new"})
        self.assertEqual(self.entries, {name: json.dumps({"token": "new"})})
        self.assertEqual(self._marker(self.second)["account"], name)
        secret_store.forget(self.second, "yahoo")
        self.assertEqual(self.entries, {})

    def test_forget_without_a_usable_marker_removes_the_0_7_4_item(self):
        damage = {
            "missing": lambda: os.remove(self.first),
            "corrupt": lambda: self._write(self.first, b"{not json"),
            "binary": lambda: self._write(self.first, b"\xff\xfe\x00\x80"),
            "not an object": lambda: self._write(self.first, b"[1, 2]"),
        }
        for label, spoil in damage.items():
            with self.subTest(marker=label):
                name = self._store_from_0_7_4(self.first, {"token": "old"})
                spoil()
                self.assertEqual(secret_store.load(self.first, "yahoo"), {})
                secret_store.forget(self.first, "yahoo")
                self.assertNotIn(name, self.entries)
                self.assertFalse(os.path.exists(self.first))

    @staticmethod
    def _write(path, content):
        with open(path, "wb") as handle:
            handle.write(content)

    def test_a_marker_nested_too_deep_to_parse_can_still_be_replaced_and_forgotten(self):
        # json reports that with RecursionError, not ValueError. 0.7.4 never
        # parsed the file in save() or forget(), so it could stop neither;
        # here it left a store nothing in the app could clear.
        nested = b"[" * 100000
        name = self._store_from_0_7_4(self.first, {"token": "old"})
        self._write(self.first, nested)
        self.assertEqual(secret_store.load(self.first, "yahoo"), {})
        secret_store.save(self.first, "yahoo", {"token": "new"})
        self.assertEqual(secret_store.load(self.first, "yahoo"), {"token": "new"})
        self._write(self.first, nested)
        secret_store.forget(self.first, "yahoo")
        self.assertNotIn(name, self.entries)
        self.assertFalse(os.path.exists(self.first))

    def test_a_marker_that_cannot_be_read_stops_save_from_minting_a_second_item(self):
        # "Could not read it" is not "there is none". Taken for that, save()
        # minted a fresh id and replaced the marker with it, and the first
        # item stayed in the Keychain with nothing left recording its name.
        secret_store.save(self.first, "yahoo", {"token": "one"})
        item = self._marker(self.first)["account"]
        with unreadable(self.first):
            self.assertEqual(secret_store.load(self.first, "yahoo"), {})
            with self.assertRaises(OSError) as raised:
                secret_store.save(self.first, "yahoo", {"token": "two"})
        self.assertIn(os.path.abspath(self.first), str(raised.exception))
        self.assertIn("Permission denied", str(raised.exception))
        self.assertEqual(self.entries, {item: json.dumps({"token": "one"})})
        self.assertEqual(self._marker(self.first)["account"], item)
        # Readable again, the same item simply carries on.
        secret_store.save(self.first, "yahoo", {"token": "two"})
        self.assertEqual(self.entries, {item: json.dumps({"token": "two"})})

    def test_a_marker_that_cannot_be_read_is_not_thrown_away_by_forget(self):
        # Deleting the file on the strength of a failed read reported the
        # credentials forgotten while the item it named was still there, and
        # now beyond finding. Saving "nothing" is a forget and must stop too.
        secret_store.save(self.first, "yahoo", {"token": "one"})
        item = self._marker(self.first)["account"]
        errors = (PermissionError(13, "Permission denied"), OSError(24, "Too many open files"),
                  OSError(5, "Input/output error"), OSError("no errno at all"))
        for error in errors:
            for forget in (lambda: secret_store.forget(self.first, "yahoo"),
                           lambda: secret_store.save(self.first, "yahoo", {})):
                with self.subTest(error=str(error)), unreadable(self.first, error):
                    with self.assertRaises(OSError) as raised:
                        forget()
                    self.assertIn("nothing was changed", str(raised.exception))
                    self.assertEqual(self.entries, {item: json.dumps({"token": "one"})})
                    self.assertTrue(os.path.exists(self.first))
        self.assertEqual(secret_store.load(self.first, "yahoo"), {"token": "one"})
        secret_store.forget(self.first, "yahoo")
        self.assertEqual(self.entries, {})
        self.assertFalse(os.path.exists(self.first))

    def test_a_marker_that_is_simply_not_there_still_reads_as_absent(self):
        # Only these two say the file does not exist; neither may be mistaken
        # for the out-of-reach kind, or a first save could never happen.
        for error in (FileNotFoundError(2, "No such file or directory"),
                      NotADirectoryError(20, "Not a directory")):
            with self.subTest(error=type(error).__name__):
                with unreadable(self.first, error):
                    secret_store.forget(self.first, "yahoo")
                    secret_store.save(self.first, "yahoo", {"token": "one"})
                self.assertEqual(secret_store.load(self.first, "yahoo"), {"token": "one"})
                secret_store.forget(self.first, "yahoo")
                self.assertEqual(self.entries, {})

    def test_forget_removes_both_the_marker_item_and_the_0_7_4_path_item(self):
        # 0.7.4 wrote an item here and its marker was lost (the directory was
        # deleted and recreated, say). The next save mints a fresh id, so
        # nothing but the path still points at the old item.
        stale = secret_store._keychain_account(self.first, "yahoo")
        self.entries[stale] = json.dumps({"token": "old"})
        secret_store.save(self.first, "yahoo", {"token": "new"})
        item = self._marker(self.first)["account"]
        self.assertEqual(sorted(self.entries), sorted([stale, item]))
        deleted = []
        with patch.object(secret_store, "_keychain_delete",
                          side_effect=lambda name: deleted.append(name) or self.entries.pop(name, None)):
            secret_store.forget(self.first, "yahoo")
        self.assertEqual(self.entries, {})
        self.assertEqual(deleted, [item, stale])
        self.assertFalse(os.path.exists(self.first))

    def test_forget_asks_for_a_0_7_4_item_only_once(self):
        # Its marker and its path name the same item.
        name = self._store_from_0_7_4(self.first, {"token": "old"})
        deleted = []
        with patch.object(secret_store, "_keychain_delete",
                          side_effect=lambda item: deleted.append(item) or self.entries.pop(item, None)):
            secret_store.forget(self.first, "yahoo")
        self.assertEqual(deleted, [name])
        self.assertEqual(self.entries, {})

    def test_forgetting_at_a_reused_path_also_forgets_the_0_7_4_store_moved_from_it(self):
        # The cost of never leaving a 0.7.4 item behind, pinned so it is a
        # known trade and not a surprise: the moved store still reads the item
        # named after its old path, and forgetting there takes it along.
        self._store_from_0_7_4(self.first, {"token": "moved"})
        self._move(self.first, self.second)
        self.assertEqual(secret_store.load(self.second, "yahoo"), {"token": "moved"})
        secret_store.save(self.first, "yahoo", {"token": "newcomer"})
        self.assertEqual(secret_store.load(self.second, "yahoo"), {"token": "moved"})
        secret_store.forget(self.first, "yahoo")
        self.assertEqual(self.entries, {})
        self.assertEqual(secret_store.load(self.second, "yahoo"), {})

    def test_a_copied_directory_shares_one_item_and_forgetting_either_forgets_both(self):
        # A copy cannot be told from a move — both markers name the same item
        # — so the two directories read and write one credential. 0.7.4 told
        # them apart by path, which is exactly what broke a moved directory.
        secret_store.save(self.first, "yahoo", {"token": "one"})
        shutil.copytree(os.path.dirname(self.first), os.path.dirname(self.second))
        self.assertEqual(secret_store.load(self.second, "yahoo"), {"token": "one"})
        secret_store.save(self.second, "yahoo", {"token": "two"})
        self.assertEqual(secret_store.load(self.first, "yahoo"), {"token": "two"})
        self.assertEqual(len(self.entries), 1)
        # Forgetting through the copy must not leave the secret in the Keychain
        # on the strength of a marker that may or may not exist elsewhere.
        secret_store.forget(self.second, "yahoo")
        self.assertEqual(self.entries, {})
        self.assertEqual(secret_store.load(self.first, "yahoo"), {})
        # The survivor's marker names an item that is gone; authorizing again
        # simply refills it.
        secret_store.save(self.first, "yahoo", {"token": "three"})
        self.assertEqual(secret_store.load(self.first, "yahoo"), {"token": "three"})
        self.assertEqual(len(self.entries), 1)

    def test_a_marker_naming_another_providers_item_is_rejected(self):
        secret_store.save(self.first, "yahoo", {"token": "one"})
        yahoo_item = self._marker(self.first)["account"]
        self.entries["yahoo"] = json.dumps({"token": "shared"})
        espn = os.path.join(os.path.dirname(self.first), "espn.json")
        # Other providers' items, then names shaped almost — but not quite —
        # like one of this provider's own.
        foreign = (yahoo_item, "yahoo", "yaho:" + "a" * 32, "espnx:" + "a" * 32,
                   "espn:", "espn:../" + "a" * 29, "espn:" + "g" * 32, "espn:" + "a" * 33,
                   "espn: " + "a" * 32, "espn:" + "A" * 32, "espn:" + yahoo_item, ["espn"], 5)
        for account in foreign:
            with self.subTest(account=account):
                if isinstance(account, str):
                    # Something really is stored under the name, so a marker
                    # that got through would visibly read it or delete it.
                    self.entries.setdefault(account, json.dumps({"token": "planted"}))
                before = dict(self.entries)
                self._marker(espn, account)
                self.assertEqual(secret_store.load(espn, "espn"), {})
                secret_store.forget(espn, "espn")
                self.assertFalse(os.path.exists(espn))
                self.assertEqual(self.entries, before)
                self.assertEqual(secret_store.load(self.first, "yahoo"), {"token": "one"})

    def test_a_marker_from_another_backend_names_no_keychain_item(self):
        secret_store.save(self.first, "yahoo", {"token": "one"})
        item = self._marker(self.first)["account"]
        self.entries["yahoo"] = json.dumps({"token": "shared"})
        # A DPAPI file carried over from Windows records the bare provider
        # name; a doctored one could claim somebody's item outright.
        for account in ("yahoo", item):
            with self.subTest(account=account):
                self._marker(self.second, account, backend="dpapi", sealed="AAAA")
                self.assertEqual(secret_store.load(self.second, "yahoo"), {})
                secret_store.forget(self.second, "yahoo")
                self.assertFalse(os.path.exists(self.second))
                self.assertEqual(sorted(self.entries), sorted(["yahoo", item]))
        # Saving over one replaces it with a marker of this backend's own.
        self._marker(self.second, item, backend="dpapi", sealed="AAAA")
        secret_store.save(self.second, "yahoo", {"token": "two"})
        self.assertEqual(self._marker(self.second)["backend"], "keychain")
        self.assertNotEqual(self._marker(self.second)["account"], item)
        self.assertEqual(secret_store.load(self.first, "yahoo"), {"token": "one"})
        self.assertEqual(secret_store.load(self.second, "yahoo"), {"token": "two"})

    def test_a_keychain_marker_is_not_read_by_another_backend(self):
        secret_store.save(self.first, "yahoo", {"token": "one"})
        with patch.object(secret_store, "backend", return_value="dpapi"), \
             patch.object(secret_store, "_dpapi", side_effect=_fake_dpapi):
            self.assertEqual(secret_store.load(self.first, "yahoo"), {})
        with patch.object(secret_store, "backend", return_value="none"):
            self.assertEqual(secret_store.load(self.first, "yahoo"), {})
            self.assertTrue(os.path.exists(self.first))

    def test_a_first_save_that_cannot_finish_leaves_no_orphan(self):
        # A minted id exists nowhere but the marker, so an item written
        # without one could never be found again.
        with patch("draft_assistant.storage.atomic_write_json", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                secret_store.save(self.first, "yahoo", {"token": "one"})
        self.assertEqual(self.entries, {})
        self.assertFalse(os.path.exists(self.first))

    def test_a_failed_resave_keeps_the_item_its_marker_names(self):
        secret_store.save(self.first, "yahoo", {"token": "one"})
        item = self._marker(self.first)["account"]
        with patch("draft_assistant.storage.atomic_write_json", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                secret_store.save(self.first, "yahoo", {"token": "two"})
        self.assertEqual(list(self.entries), [item])
        self.assertEqual(self._marker(self.first)["account"], item)

    def test_legacy_migration_copies_without_deleting_shared_credentials(self):
        self.entries["yahoo"] = json.dumps({"token": "legacy"})
        self._legacy_marker(self.first)
        self._legacy_marker(self.second)
        self.assertEqual(secret_store.load(self.first, "yahoo"), {"token": "legacy"})
        self.assertRegex(self._marker(self.first)["account"], r"\Ayahoo:[0-9a-f]{32}\Z")
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
        self.assertEqual(self.entries, {"yahoo": json.dumps({"token": "legacy"})})


class FakeSecurity:
    """Stand-in for /usr/bin/security that reads and tokenizes as the real one.

    The stdin reader and the tokenizer follow Apple's SecurityTool (readline.c,
    and split_line in security.c): a fixed line buffer that *splits* an
    over-long line rather than rejecting it, a quoted argument that ends only
    at its opening quote character, and a backslash that escapes whatever
    follows. The quoting is therefore checked against the tool's rules, not
    against a second copy of the code under test.
    """

    MAX_ARGS = 32

    def __init__(self, line_buffer=4096):
        self.line_buffer = line_buffer
        self.items = {}      # account -> stored bytes
        self.writes = []     # every (account, bytes) stored, in order
        self.calls = []      # (argv, stdin, timeout) for each run
        self.commands = []   # every command read from stdin, tokenized
        self.refuse_stdin = False
        self.stdin_exit = None
        self.mangle_stdin = None
        self.fail_argv_writes = False
        self.refuse_delete = False

    def run(self, argv, input=None, capture_output=False, text=False, timeout=None, **_):
        argv = list(argv)
        self.calls.append((argv, input, timeout))
        out = []
        if argv == ["security", "-i"]:
            status = 2 if self.refuse_stdin else 0
            for tokens in () if self.refuse_stdin else self._read_commands(input or b""):
                self.commands.append(tokens)
                status = self._execute(tokens, out, self.mangle_stdin)
            if self.stdin_exit is not None:
                status = self.stdin_exit
        elif self.fail_argv_writes and argv[1] == "add-generic-password":
            status = 36  # a locked keychain, say: a non-zero exit, nothing raised
        else:
            status = self._execute([arg.encode("utf-8") for arg in argv[1:]], out)
        stdout = b"".join(out)
        return subprocess.CompletedProcess(
            argv, status, stdout.decode("ascii") if text else stdout, "" if text else b"")

    def _read_commands(self, data):
        position = 0
        while True:
            line = bytearray()
            # A full buffer ends the line *without* consuming anything more:
            # whatever follows is read as the next command.
            while len(line) < self.line_buffer - 1:
                if position == len(data):
                    return  # EOF: a line with no newline is dropped, not run
                byte = data[position]
                position += 1
                if byte == 0x0A:
                    break
                line.append(byte)
            yield self._split(bytes(line))

    @classmethod
    def _split(cls, line):
        args, current, state, quote = [], bytearray(), "skip", b""
        for byte in line.split(b"\0", 1)[0]:
            char = bytes([byte])
            if state == "skip":
                if char.isspace():
                    continue
                current = bytearray()
                if char in (b'"', b"'"):
                    quote, state = char, "quoted"
                    continue
                state = "read"
            if state == "read":
                if char == b"\\":
                    state = "read-escaped"
                elif char.isspace():
                    args.append(bytes(current))
                    state = "skip"
                    if len(args) >= cls.MAX_ARGS:
                        break
                else:
                    current += char
            elif state == "quoted":
                if char == b"\\":
                    state = "quoted-escaped"
                elif char == quote:
                    args.append(bytes(current))
                    state = "skip"
                    if len(args) >= cls.MAX_ARGS:
                        break
                else:
                    current += char
            elif state == "read-escaped":
                current += char
                state = "read"
            elif state == "quoted-escaped":
                current += char
                state = "quoted"
        if state != "skip":
            args.append(bytes(current))
        return args

    def _execute(self, tokens, out, mangle=None):
        if not tokens:
            return 0
        # command -> (handler, options that take a value, bare flags)
        handler, valued, flags = {
            b"add-generic-password": (self._add, (b"-a", b"-s", b"-w", b"-X"), (b"-U",)),
            b"find-generic-password": (self._find, (b"-a", b"-s"), (b"-w",)),
            b"delete-generic-password": (self._delete, (b"-a", b"-s"), ()),
        }.get(tokens[0], (None, (), ()))
        if handler is None:
            return 1  # "unknown command"
        options, index = {}, 1
        while index < len(tokens):
            flag = tokens[index]
            if flag in valued:
                if index + 1 == len(tokens):
                    raise AssertionError("an option without its value makes the tool prompt")
                options[flag] = tokens[index + 1]
                index += 2
            elif flag in flags:
                options[flag] = b""
                index += 1
            else:
                return 2  # usage
        if options.get(b"-s") != b"DraftAssistant" or b"-a" not in options:
            return 2
        return handler(options, out, mangle)

    def _add(self, options, out, mangle):
        if b"-X" in options:
            digits = options[b"-X"]
            try:  # An odd number of digits is zero-padded, not refused.
                secret = bytes.fromhex(("0" if len(digits) % 2 else "") + digits.decode("ascii"))
            except ValueError:
                return 2
        else:
            secret = options.get(b"-w", b"")
        account = options[b"-a"].decode("utf-8")
        if account in self.items and b"-U" not in options:
            return 45  # errSecDuplicateItem
        if mangle:
            secret = mangle(secret)
        self.items[account] = secret
        self.writes.append((account, secret))
        return 0

    def _find(self, options, out, mangle):
        secret = self.items.get(options[b"-a"].decode("utf-8"))
        if secret is None:
            return 44  # errSecItemNotFound
        if b"-w" not in options:
            # Attributes only: all this says is that the item exists.
            out.append(b'keychain: "login.keychain-db"\n')
            return 0
        # -w prints anything that is not printable ASCII as hex.
        printable = all(0x20 <= byte < 0x7F for byte in secret)
        out.append((secret if printable else secret.hex().encode("ascii")) + b"\n")
        return 0

    def _delete(self, options, out, mangle):
        account = options[b"-a"].decode("utf-8")
        if account not in self.items:
            return 44
        if self.refuse_delete:
            return 36  # errSecInteractionNotAllowed: found, and still there
        del self.items[account]
        return 0


class TestKeychainTransport(unittest.TestCase):
    """How a secret reaches ``security``: stdin when it fits a line, else argv."""

    ACCOUNT = "yahoo:" + "a" * 32

    def setUp(self):
        self.fake = FakeSecurity()
        run = patch.object(secret_store.subprocess, "run", side_effect=self.fake.run)
        run.start()
        self.addCleanup(run.stop)
        self.addCleanup(setattr, secret_store, "_keychain_transport", None)

    def _stdin_calls(self):
        return [call for call in self.fake.calls if call[0] == ["security", "-i"]]

    def _argv_writes(self):
        return [call for call in self.fake.calls if call[0][1] == "add-generic-password"]

    def _write(self, secret, account=ACCOUNT):
        secret_store._keychain_write(account, secret)
        return secret_store._keychain_transport

    def test_a_secret_travels_on_stdin_not_on_the_command_line(self):
        secret = json.dumps({"access_token": "synthetic-token", "expires_in": 3600})
        self.assertEqual(self._write(secret), "stdin-hex")
        (argv, line, timeout), = self._stdin_calls()
        self.assertEqual(argv, ["security", "-i"])
        self.assertEqual(
            line,
            b"add-generic-password -s DraftAssistant -a " + self.ACCOUNT.encode("ascii")
            + b" -X " + secret.encode("utf-8").hex().encode("ascii") + b" -U\n")
        self.assertIsNotNone(timeout)
        self.assertEqual(self._argv_writes(), [])
        for argv, _, _ in self.fake.calls:
            self.assertNotIn("synthetic-token", " ".join(argv))
        self.assertEqual(self.fake.items, {self.ACCOUNT: secret.encode("utf-8")})
        self.assertEqual(secret_store._keychain_read(self.ACCOUNT), secret)

    def test_a_secret_too_long_for_hex_is_single_quoted_and_escaped(self):
        awkward = "it's \"quoted\" \\ back\\slash 'single' \\' \\\\ trailing\\"
        secret = json.dumps({"note": awkward, "pad": "x" * 2400})
        self.assertGreater(len(secret) * 2, secret_store._KEYCHAIN_LINE_LIMIT)
        self.assertEqual(self._write(secret), "stdin-quoted")
        (_, line, _), = self._stdin_calls()
        self.assertIn(b" -w '", line)
        self.assertNotIn(b" -X ", line)
        self.assertEqual(line.count(b"\n"), 1)
        self.assertTrue(line.endswith(b"' -U\n"))
        # One command, tokenized by the tool's own rules into the exact secret.
        self.assertEqual(self.fake.commands, [[
            b"add-generic-password", b"-s", b"DraftAssistant",
            b"-a", self.ACCOUNT.encode("ascii"), b"-w", secret.encode("utf-8"), b"-U"]])
        self.assertEqual(self._argv_writes(), [])
        self.assertEqual(secret_store._keychain_read(self.ACCOUNT), secret)

    def test_every_awkward_character_survives_the_quoted_form(self):
        pad = "p" * 2000
        for awkward in ("'", "\\", "\\'", "'\\", "\\\\", "''", '"', "\\\"", " ' ", "\\n", "$(x) `y` ;#&|",
                        "-U", " -U", "' -U", "\\' -U -a other"):
            with self.subTest(awkward=awkward):
                for secret in (awkward + pad, pad + awkward, pad[:1000] + awkward + pad[:1000]):
                    if secret != secret.strip():
                        continue  # _keychain_read trims, so this could never read back
                    self.fake.commands.clear()
                    self.assertEqual(self._write(secret), "stdin-quoted")
                    self.assertEqual(len(self.fake.commands), 1)
                    self.assertEqual(self.fake.items, {self.ACCOUNT: secret.encode("ascii")})

    def test_no_line_comes_near_the_tools_buffer_at_any_size(self):
        limit = secret_store._KEYCHAIN_LINE_LIMIT
        self.assertLess(limit, self.fake.line_buffer - 1)
        for filler in ("x", "'", "\\"):
            with self.subTest(filler=filler):
                transports, longest = [], {}
                for size in range(1, 4200):
                    transport, line = (secret_store._keychain_stdin_command(self.ACCOUNT, filler * size)
                                       or ("argv", b""))
                    self.assertLessEqual(len(line), limit)
                    transports.append(transport)
                    longest[transport] = max(longest.get(transport, 0), len(line))
                # Hex while it fits, then quoted, then argv — never back again.
                changes = [size for size in range(2, 4200) if transports[size - 1] != transports[size - 2]]
                expected = ["stdin-hex", "stdin-quoted", "argv"]
                if filler != "x":  # every character doubles, so quoting never wins
                    expected.remove("stdin-quoted")
                self.assertEqual([transports[0]] + [transports[size - 1] for size in changes], expected)
                # ...and each form is used right up to the limit, not short of it.
                self.assertGreaterEqual(longest["stdin-hex"], limit - 1)
                if filler == "x":
                    self.assertEqual(longest["stdin-quoted"], limit)
                # Either side of each change, the longest lines really are read
                # by the tool as one command holding the whole secret.
                for size in (near for change in changes for near in range(change - 3, change + 3)):
                    secret = filler * size
                    self.fake.calls.clear()
                    self.fake.commands.clear()
                    self.assertEqual(self._write(secret), transports[size - 1])
                    self.assertEqual(self.fake.items[self.ACCOUNT], secret.encode("ascii"))
                    self.assertEqual(len(self.fake.commands), len(self._stdin_calls()))
                    self.assertEqual(len(self._stdin_calls()), 0 if transports[size - 1] == "argv" else 1)

    def test_an_oversized_secret_still_goes_through_argv(self):
        secret = json.dumps({"token": "t" * 6000})
        self.assertEqual(self._write(secret), "argv")
        self.assertEqual(self._stdin_calls(), [])
        (argv, stdin, timeout), = self._argv_writes()
        self.assertEqual(argv, ["security", "add-generic-password", "-U", "-s", "DraftAssistant",
                                "-a", self.ACCOUNT, "-w", secret])
        self.assertIsNone(stdin)
        self.assertIsNone(timeout)
        self.assertEqual(secret_store._keychain_read(self.ACCOUNT), secret)

    def test_what_cannot_sit_on_a_line_goes_through_argv(self):
        secret = json.dumps({"token": "synthetic"})
        for account in ("has space", "quo'te", 'dou"ble', "back\\slash", "tab\there", "new\nline", ""):
            with self.subTest(account=account):
                self.fake.calls.clear()
                self.assertEqual(self._write(secret, account), "argv")
                self.assertEqual(self._stdin_calls(), [])
                self.assertEqual(self.fake.items[account], secret.encode("ascii"))
        # An empty -X value would swallow the next option as its argument.
        self.fake.calls.clear()
        self.assertEqual(self._write(""), "argv")
        self.assertEqual(self._stdin_calls(), [])
        # A line break cannot be quoted, and this is too long for hex.
        self.fake.calls.clear()
        self.assertEqual(self._write("first\n" + "x" * 2500), "argv")
        self.assertEqual(self._stdin_calls(), [])

    def test_a_secret_the_tool_cannot_echo_back_falls_back_to_argv(self):
        # find-generic-password -w prints hex for anything but printable ASCII,
        # so such a write can never be confirmed. json.dumps never emits one.
        for secret in ("ünïcödé ☃ 日本語", "two\nlines", " leading space"):
            with self.subTest(secret=secret):
                self.fake.calls.clear()
                self.assertEqual(self._write(secret), "argv")
                (_, line, _), = self._stdin_calls()
                self.assertEqual(line.count(b"\n"), 1)
                self.assertIn(b" -X " + secret.encode("utf-8").hex().encode("ascii") + b" -U\n", line)
                self.assertEqual(self.fake.items[self.ACCOUNT], secret.encode("utf-8"))

    def test_a_write_that_reads_back_wrong_is_redone_through_argv(self):
        # Exit status 0 proves nothing: it is only the last command's.
        secret = json.dumps({"token": "t" * 300})
        self.fake.mangle_stdin = lambda stored: stored[:100]
        self.assertEqual(self._write(secret), "argv")
        self.assertEqual(len(self._stdin_calls()), 1)
        self.assertEqual(len(self._argv_writes()), 1)
        self.assertEqual(self.fake.items, {self.ACCOUNT: secret.encode("ascii")})

    def test_a_split_line_cannot_replace_a_good_item_with_a_truncated_one(self):
        # A tool whose buffer is shorter than the limit assumes splits the
        # line. With -U last, the half that runs fails as a duplicate.
        self.fake.line_buffer = 1024
        old = json.dumps({"token": "old"})
        self.fake.items[self.ACCOUNT] = old.encode("ascii")
        secret = json.dumps({"token": "n" * 1500})
        self.assertEqual(self._write(secret), "argv")
        self.assertGreater(len(self.fake.commands), 1)
        self.assertEqual(self.fake.writes, [(self.ACCOUNT, secret.encode("ascii"))])
        # The quoted form splits the same way and is recovered the same way.
        self.fake.commands.clear()
        longer = json.dumps({"token": "q" * 2500})
        self.assertEqual(self._write(longer), "argv")
        self.assertGreater(len(self.fake.commands), 1)
        self.assertEqual(self.fake.writes[1:], [(self.ACCOUNT, longer.encode("ascii"))])

    def test_a_split_line_on_a_new_item_is_overwritten_by_the_fallback(self):
        self.fake.line_buffer = 1024
        secret = json.dumps({"token": "n" * 1500})
        self.assertEqual(self._write(secret), "argv")
        self.assertEqual(self.fake.items, {self.ACCOUNT: secret.encode("ascii")})

    def test_a_failing_stdin_write_falls_back_to_argv(self):
        secret = json.dumps({"token": "synthetic"})
        self.fake.refuse_stdin = True  # e.g. a tool that predates -X
        self.assertEqual(self._write(secret), "argv")
        self.assertEqual(len(self._stdin_calls()), 1)
        self.assertEqual(self.fake.items, {self.ACCOUNT: secret.encode("ascii")})

    def test_a_nonzero_exit_is_a_failure_even_when_the_item_reads_back(self):
        secret = json.dumps({"token": "synthetic"})
        self.fake.stdin_exit = 1
        self.assertEqual(self._write(secret), "argv")
        self.assertEqual(len(self._stdin_calls()), 1)
        self.assertEqual(len(self._argv_writes()), 1)
        self.assertEqual(self.fake.items, {self.ACCOUNT: secret.encode("ascii")})

    def test_a_write_no_transport_can_complete_raises_one_clean_error(self):
        # No exception anywhere: the tool just exits non-zero, as it does for
        # a locked keychain. That still has to surface as a failed save.
        secret = json.dumps({"token": "sensitive-token"})
        self.fake.refuse_stdin = True
        self.fake.fail_argv_writes = True
        with self.assertRaises(OSError) as raised:
            self._write(secret)
        self.assertEqual(str(raised.exception), "Could not save credentials in the macOS Keychain")
        self.assertIsNone(secret_store._keychain_transport)
        self.assertEqual(self.fake.items, {})
        self.assertEqual((len(self._stdin_calls()), len(self._argv_writes())), (1, 1))

    def test_a_stdin_write_that_raises_falls_back_to_argv(self):
        secret = json.dumps({"token": "synthetic"})
        for error in (subprocess.TimeoutExpired(["security", "-i"], 30),
                      subprocess.CalledProcessError(1, ["security", "-i"]),
                      OSError("pipe closed")):
            with self.subTest(error=type(error).__name__):
                self.fake.items.clear()

                def run(argv, **options):
                    if argv == ["security", "-i"]:
                        raise error
                    return self.fake.run(argv, **options)

                with patch.object(secret_store.subprocess, "run", side_effect=run):
                    self.assertEqual(self._write(secret), "argv")
                self.assertEqual(self.fake.items, {self.ACCOUNT: secret.encode("ascii")})

    def test_a_read_back_that_raises_counts_as_a_mismatch(self):
        secret = json.dumps({"token": "synthetic"})
        with patch.object(secret_store, "_keychain_read",
                          side_effect=UnicodeDecodeError("utf-8", secret.encode("ascii"), 0, 1, "x")):
            self.assertEqual(self._write(secret), "argv")
        self.assertEqual(self.fake.items, {self.ACCOUNT: secret.encode("ascii")})

    def test_no_failure_on_any_transport_discloses_the_secret(self):
        for secret in (json.dumps({"token": "sensitive-token"}),           # stdin, then argv
                       json.dumps({"token": "sensitive-token" * 400})):    # argv only
            for kind in (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError, ValueError):
                with self.subTest(kind=kind.__name__, size=len(secret)):

                    def run(argv, input=None, **_):
                        # Each of these carries argv and the piped input, as
                        # the real exceptions do.
                        if kind is subprocess.CalledProcessError:
                            raise kind(1, argv, output=input, stderr=secret)
                        if kind is subprocess.TimeoutExpired:
                            raise kind(argv, 30, output=input, stderr=secret)
                        raise kind(f"{argv} {input!r}")

                    with patch.object(secret_store.subprocess, "run", side_effect=run):
                        with self.assertRaises(OSError) as raised:
                            self._write(secret)
                    error = raised.exception
                    self.assertIsNone(secret_store._keychain_transport)
                    # `raise ... from None` only hides the chain; the original
                    # exception — argv and all — would still hang off __context__.
                    self.assertIsNone(error.__cause__)
                    self.assertIsNone(error.__context__)
                    rendered = "".join(traceback.format_exception(type(error), error, error.__traceback__))
                    for text in (str(error), repr(error), repr(error.args), rendered):
                        self.assertNotIn("sensitive-token", text)
                        self.assertNotIn(b"sensitive-token".hex(), text)
                    self.assertEqual(str(error), "Could not save credentials in the macOS Keychain")

    def test_save_load_and_forget_work_end_to_end_through_the_tool(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = os.path.join(directory.name, "profile", "espn.json")
        payloads = (
            ({"1": {"espnS2": "synthetic-cookie", "swid": "{SYNTHETIC}"}}, "stdin-hex"),
            ({str(league): {"espnS2": "synthetic-" + "c" * 300, "swid": "{SYNTHETIC}"}
              for league in range(7)}, "stdin-quoted"),
            ({"note": "ünïcödé \"double\" 'single' back\\slash ☃"}, "stdin-hex"),
            ({str(league): {"espnS2": "synthetic-" + "c" * 300, "swid": "{SYNTHETIC}"}
              for league in range(20)}, "argv"),
        )
        with patch.object(secret_store, "backend", return_value="keychain"):
            for data, transport in payloads + payloads[:1]:
                self.assertTrue(secret_store.save(path, "espn", data))
                self.assertEqual(secret_store._keychain_transport, transport)
                self.assertEqual(secret_store.load(path, "espn"), data)
                self.assertEqual(len(self.fake.items), 1)
                with open(path, encoding="utf-8") as handle:
                    self.assertRegex(json.load(handle)["account"], r"\Aespn:[0-9a-f]{32}\Z")
            secret_store.forget(path, "espn")
        self.assertEqual(self.fake.items, {})
        self.assertFalse(os.path.exists(path))

    def _store(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        return os.path.join(directory.name, "profile", "yahoo.json")

    def test_forget_keeps_the_marker_when_the_item_could_not_be_deleted(self):
        # The tool exits non-zero and the item is still there — a locked
        # keychain whose unlock prompt was dismissed, say. forget() used to
        # remove the marker regardless and report success, and with the id
        # recorded nowhere else the secret stayed in the Keychain for good.
        path = self._store()
        with patch.object(secret_store, "backend", return_value="keychain"):
            secret_store.save(path, "yahoo", {"token": "sensitive-token"})
            with open(path, encoding="utf-8") as handle:
                item = json.load(handle)["account"]
            self.fake.refuse_delete = True
            for forget in (lambda: secret_store.forget(path, "yahoo"),
                           lambda: secret_store.save(path, "yahoo", {})):
                with self.assertRaises(OSError) as raised:
                    forget()
                self.assertEqual(str(raised.exception), "Could not remove credentials from the macOS Keychain")
                self.assertIsNone(raised.exception.__context__)
                self.assertIn(item, self.fake.items)
                self.assertEqual(secret_store.load(path, "yahoo"), {"token": "sensitive-token"})
            # Nothing was lost: once the tool will delete, the marker that was
            # kept finishes the job.
            self.fake.refuse_delete = False
            secret_store.forget(path, "yahoo")
        self.assertEqual(self.fake.items, {})
        self.assertFalse(os.path.exists(path))

    def test_deleting_what_is_not_there_is_not_a_failure(self):
        # "No such item" exits non-zero too, and forget() asks for the 0.7.4
        # path-derived name every time although it almost never exists.
        path = self._store()
        with patch.object(secret_store, "backend", return_value="keychain"):
            secret_store.forget(path, "yahoo")
            secret_store.save(path, "yahoo", {"token": "one"})
            secret_store.forget(path, "yahoo")
        self.assertEqual(self.fake.items, {})
        self.assertFalse(os.path.exists(path))
        secret_store._keychain_delete("yahoo:" + "b" * 32)
        # Telling the two apart asks whether the item exists, never for its password.
        probes = [argv for argv, _, _ in self.fake.calls
                  if argv[1] == "find-generic-password" and "-w" not in argv]
        self.assertTrue(probes)
        for argv in probes:
            self.assertEqual(argv, ["security", "find-generic-password", "-s", "DraftAssistant", "-a", argv[5]])

    def test_a_refused_cleanup_does_not_hide_why_the_first_save_failed(self):
        path = self._store()
        self.fake.refuse_delete = True
        with patch.object(secret_store, "backend", return_value="keychain"), \
             patch("draft_assistant.storage.atomic_write_json", side_effect=OSError("disk full")):
            with self.assertRaises(OSError) as raised:
                secret_store.save(path, "yahoo", {"token": "one"})
        self.assertEqual(str(raised.exception), "disk full")
        self.assertFalse(os.path.exists(path))


class TestKeychainErrors(unittest.TestCase):
    def test_write_error_does_not_disclose_command_line_secret(self):
        error = subprocess.CalledProcessError(1, ["security", "-w", "sensitive-token"])
        with patch.object(secret_store.subprocess, "run", side_effect=error):
            with self.assertRaises(OSError) as raised:
                secret_store._keychain_write("profile", "sensitive-token")
        self.assertNotIn("sensitive-token", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
