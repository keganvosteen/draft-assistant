"""Verify that reviewed offline browser dependencies were not replaced."""
from __future__ import annotations

import hashlib
from pathlib import Path


EXPECTED = {
    "react.production.min.js": "d949f1c3687aedadcedac85261865f29b17cd273997e7f6b2bfc53b2f9d4c4dd",
    "react-dom.production.min.js": "35f4f974f4b2bcd44da73963347f8952e341f83909e4498227d4e26b98f66f0d",
    "babel.min.js": "a12872ea8da3d29b2a296c51bfac7c482e81419c755f2207a49ad9b77200f4ea",
}


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    vendor = root / "draft_assistant" / "web" / "static" / "vendor"
    failures = []
    for name, expected in EXPECTED.items():
        path = vendor / name
        # Git normalizes these text assets to LF, while a Windows checkout may
        # materialize CRLF.  Hash the canonical Git representation so the
        # integrity gate has the same result on developer machines and CI.
        contents = path.read_bytes().replace(b"\r\n", b"\n") if path.exists() else None
        actual = hashlib.sha256(contents).hexdigest() if contents is not None else "missing"
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
