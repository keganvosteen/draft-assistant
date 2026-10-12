"""Exercise the real OS keystore using isolated, disposable synthetic secrets."""
from pathlib import Path
import json
import sys
import tempfile
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from draft_assistant import secret_store


def main():
    if not secret_store.available():
        raise SystemExit("Native keystore smoke check requires Windows or macOS")
    account = "audit-smoke-" + uuid.uuid4().hex
    with tempfile.TemporaryDirectory(prefix="DraftAssistant-secret-smoke-") as temporary:
        paths = [str(Path(temporary) / f"profile-{index}.json") for index in range(4)]
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
            for path in paths:
                secret_store.forget(path, account)
            if secret_store.backend() == "keychain":
                secret_store._keychain_delete(account)
    print(f"Native {secret_store.backend()} credential isolation and cleanup: PASS")


if __name__ == "__main__":
    main()
