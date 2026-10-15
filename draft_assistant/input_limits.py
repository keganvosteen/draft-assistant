"""Resource bounds for user-pasted documents, shared by UI and CLI parsers."""
from __future__ import annotations

from typing import List


MAX_PASTED_TEXT_CHARS = 200_000
MAX_PASTED_LINE_CHARS = 4_096
MAX_PASTED_LINES = 2_000
MAX_DRAFT_CANDIDATES = 10_000
MAX_DRAFT_PLAYER_NAME_CHARS = 256
MAX_DRAFT_PLAYER_ID_CHARS = 256


def validate_pasted_line(line: str, label: str = "Pasted text") -> None:
    if not isinstance(line, str):
        raise ValueError(f"{label} must be text")
    if len(line) > MAX_PASTED_LINE_CHARS:
        raise ValueError(f"{label} lines must be at most {MAX_PASTED_LINE_CHARS:,} characters")


def validate_pasted_text(text: str, label: str = "Pasted text") -> List[str]:
    """Reject oversized inputs before parsing or scanning player candidates."""
    if not isinstance(text, str):
        raise ValueError(f"{label} must be text")
    if len(text) > MAX_PASTED_TEXT_CHARS:
        raise ValueError(f"{label} must be at most {MAX_PASTED_TEXT_CHARS:,} characters")
    lines = text.splitlines()
    if len(lines) > MAX_PASTED_LINES:
        raise ValueError(f"{label} must be at most {MAX_PASTED_LINES:,} lines")
    for line in lines:
        validate_pasted_line(line, label)
    return lines
