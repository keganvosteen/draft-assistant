"""Exercise the real OS keystore using isolated, disposable synthetic secrets."""
from pathlib import Path
import json
import sys
import tempfile
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from draft_assistant import secret_store


def _padded(label, size, filler="x"):
    """A synthetic payload whose stored JSON runs to roughly *size* bytes."""
    return {"token": f"synthetic-{label}-" + (filler * size)[:size]}


# (label, payload, how it must reach the Keychain). The Keychain backend keeps
# a secret off the command line whenever it fits one `security -i` line: as
# hex while that fits, single-quoted when only that does, and through argv —
# the pre-stdin behaviour — only when neither can.
ROUND_TRIPS = (
    ("small", {"token": "synthetic-small"}, "stdin-hex"),
    ("1.5 KB", _padded("medium", 1500), "stdin-hex"),
    # Too long for hex. The quotes and backslashes are there to put the
    # escaping in front of the real tool's tokenizer, not a model of it.
    ("3 KB", _padded("large", 2700, "x" * 40 + "it's \"q\" \\ "), "stdin-quoted"),
    ("quoting and non-ASCII",
     {"token": "synthetic-\"double\" 'single' back\\slash ünïcödé 日本語 ☃"},
     "stdin-hex"),
    ("oversized", _padded("oversized", 6000), "argv"),
)


def _check_round_trip(path, account, label, payload, transport):
    assert secret_store.save(path, account, payload), label
    if secret_store.backend() == "keychain":
        used = secret_store._keychain_transport
        assert used == transport, f"{label}: expected {transport}, used {used}"
    assert secret_store.load(path, account) == payload, label
    assert secret_store.is_sealed(path), label
    assert "synthetic-" not in Path(path).read_text(), label


def main():
    if not secret_store.available():
        raise SystemExit("Native keystore smoke check requires Windows or macOS")
    account = "audit-smoke-" + uuid.uuid4().hex
    with tempfile.TemporaryDirectory(prefix="DraftAssistant-secret-smoke-") as temporary:
        paths = [str(Path(temporary) / f"profile-{index}.json") for index in range(4)]
        sized = [str(Path(temporary) / f"sized-{index}.json") for index in range(len(ROUND_TRIPS))]
        before, after = Path(temporary) / "before-move", Path(temporary) / "after-move"
        moving = [str(directory / "yahoo.json") for directory in (before, after)]
        first, second = {"token": "synthetic-first"}, {"token": "synthetic-second"}
        try:
            assert secret_store.save(paths[0], account, first)
            assert secret_store.save(paths[1], account, second)
            assert secret_store.load(paths[0], account) == first
            assert secret_store.load(paths[1], account) == second
            assert all(secret_store.is_sealed(path) for path in paths[:2])
            assert all("synthetic-" not in Path(path).read_text() for path in paths[:2])
            secret_store.forget(paths[0], account)
            assert secret_store.load(paths[0], account) == {}
            assert secret_store.load(paths[1], account) == second

            # Create each item, then update it with the next payload along, so
            # every transport both adds an item and overwrites another's.
            for path, (label, payload, transport) in zip(sized, ROUND_TRIPS):
                _check_round_trip(path, account, label, payload, transport)
            for path, (label, payload, transport) in zip(sized, ROUND_TRIPS[1:] + ROUND_TRIPS[:1]):
                _check_round_trip(path, account, f"{label} (update)", payload, transport)

            # A moved data directory keeps its credential, and forgetting it
            # there leaves nothing behind in the keystore.
            moved = {"token": "synthetic-moved"}
            assert secret_store.save(moving[0], account, moved)
            before.rename(after)
            assert secret_store.load(moving[1], account) == moved
            if secret_store.backend() == "keychain":
                item = json.loads(Path(moving[1]).read_text())["account"]
                assert secret_store._keychain_read(item) is not None
                # forget() keeps the marker when a delete fails, and tells a
                # failed delete from "no such item" by asking the real tool
                # whether the item exists. Both answers have to be right.
                assert secret_store._keychain_has(item)
                secret_store.forget(moving[1], account)
                assert secret_store._keychain_read(item) is None
                assert not secret_store._keychain_has(item)
                secret_store._keychain_delete(item)
            secret_store.forget(moving[1], account)
            assert secret_store.load(moving[1], account) == {}

            if secret_store.backend() == "keychain":
                # A legacy account can be shared by multiple profiles. Migrate
                # one, delete it, then confirm the other still has its secret.
                legacy = {"token": "synthetic-legacy"}
                secret_store._keychain_write(account, json.dumps(legacy))
                marker = {"magic": secret_store._MAGIC, "backend": "keychain", "account": account}
                for path in paths[2:]:
                    Path(path).write_text(json.dumps(marker))
                assert secret_store.load(paths[2], account) == legacy
                secret_store.forget(paths[2], account)
                assert secret_store.load(paths[3], account) == legacy
                assert secret_store._keychain_read(account) is not None
        finally:
            for path in paths + sized + moving:
                secret_store.forget(path, account)
            if secret_store.backend() == "keychain":
                secret_store._keychain_delete(account)
    print(f"Native {secret_store.backend()} credential isolation, transports and cleanup: PASS")


if __name__ == "__main__":
    main()
