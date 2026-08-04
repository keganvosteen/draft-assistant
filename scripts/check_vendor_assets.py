"""Verify that reviewed offline browser dependencies were not replaced."""
from __future__ import annotations

import hashlib
from pathlib import Path


EXPECTED = {
    "react.production.min.js": "d72610e728466bf70f27ecc9a1a14580fd8f1e75b977aa0612146cab0e80a3fe",
    "react-dom.production.min.js": "13b1c0705b9fa93346936ed98bd4a858fea4cdacdb09e564f897c5ba6bd0943a",
    "babel.min.js": "7094c930172b48b4b05f2b7b102be439af601fc873b64b857a4c5eb779476d93",
}


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    vendor = root / "draft_assistant" / "web" / "static" / "vendor"
    failures = []
    for name, expected in EXPECTED.items():
        path = vendor / name
        actual = hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else "missing"
        if actual != expected:
            failures.append(f"{name}: expected {expected}, got {actual}")
    for notice in (root / "LICENSE", root / "THIRD_PARTY_NOTICES.md"):
        if not notice.exists():
            failures.append(f"missing {notice.name}")
    if failures:
        print("Vendor asset check: FAIL")
        print("\n".join(f"- {failure}" for failure in failures))
        return 1
    print("Vendor asset check: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
