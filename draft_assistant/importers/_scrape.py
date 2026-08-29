"""Shared plumbing for the sources that come from scraping HTML pages.

Extracted from ``fftoday.py``, which was the only scraper for a long time. The
table parser in particular is worth not rewriting: fantasy sites still use
old-school *nested* layout tables, and a naive single-buffer parser silently
scrambles them.

Scrapers are the fragile end of the pipeline — a site redesign breaks them with
no warning from upstream — so everything here fails loudly rather than returning
half a table, and callers are expected to isolate each source so one broken site
cannot cost the whole pull.
"""
from __future__ import annotations

import re
import time
from html.parser import HTMLParser
from typing import Callable, Dict, List, Optional, TypeVar
from urllib.request import Request, urlopen

T = TypeVar("T")

BROWSER_HEADERS: Dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Cache-Control": "no-cache",
}


class _TableFrame:
    """In-progress rows for one open <table> (one frame per nesting level)."""
    __slots__ = ("rows", "row", "cell")

    def __init__(self) -> None:
        self.rows: List[List[str]] = []
        self.row: Optional[List[str]] = None
        self.cell: Optional[str] = None


class TableParser(HTMLParser):
    """Collect every <table> as rows of cell text.

    Fantasy sites use old-school *nested* layout tables, so a single in-progress
    buffer gets scrambled (an inner <table> resets it and its </table> closes the
    outer one). We keep a stack of frames — one per open table — so each table's
    rows are captured independently regardless of nesting.
    """

    def __init__(self) -> None:
        super().__init__()
        self.tables: List[List[List[str]]] = []
        self._stack: List[_TableFrame] = []

    def _top(self) -> Optional[_TableFrame]:
        return self._stack[-1] if self._stack else None

    def handle_starttag(self, tag: str, attrs):
        frame = self._top()
        if tag == "table":
            self._stack.append(_TableFrame())
        elif tag == "tr" and frame is not None:
            frame.row = []
        elif tag in ("td", "th") and frame is not None and frame.row is not None:
            frame.cell = ""

    def handle_endtag(self, tag: str):
        frame = self._top()
        if frame is None:
            return
        if tag in ("td", "th") and frame.cell is not None:
            frame.row.append(self._clean(frame.cell))
            frame.cell = None
        elif tag == "tr" and frame.row is not None:
            frame.rows.append(frame.row)
            frame.row = None
        elif tag == "table":
            done = self._stack.pop()
            if done.rows:
                self.tables.append(done.rows)

    def handle_data(self, data: str):
        frame = self._top()
        if frame is not None and frame.cell is not None:
            frame.cell += data

    def _clean(self, s: str) -> str:
        return re.sub(r"\s+", " ", s).strip()


def largest_table(html: str, min_rows: int = 5) -> Optional[List[List[str]]]:
    """The biggest table on the page, which on a stats page is the data."""
    parser = TableParser()
    parser.feed(html)
    tables = [t for t in parser.tables if len(t) >= min_rows]
    return max(tables, key=len) if tables else None


def fetch_once(url: str, timeout: int = 20) -> str:
    req = Request(url, headers=BROWSER_HEADERS)
    with urlopen(req, timeout=timeout) as resp:
        data = resp.read()
        for encoding in ("utf-8", "latin-1"):
            try:
                return data.decode(encoding)
            except Exception:
                continue
        return data.decode("utf-8", errors="ignore")


def retry(call: Callable[[], T], attempts: int = 3, backoff: float = 2.0) -> T:
    """Run ``call``, retrying transient failures with a short backoff.

    Scraped servers drop connections; a single hiccup used to silently cost a
    whole source (and with it the consensus), so a retry is worth the wait.
    """
    last_exc: Optional[Exception] = None
    for attempt in range(attempts):
        if attempt:
            time.sleep(backoff * attempt)
        try:
            return call()
        except Exception as exc:
            last_exc = exc
    raise last_exc


def fetch_html(url: str, attempts: int = 3, timeout: int = 20) -> str:
    return retry(lambda: fetch_once(url, timeout=timeout), attempts=attempts)


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")


def to_float(s: str) -> float:
    try:
        s = s.replace(",", "").strip()
        if s in ("", "-", "--"):
            return 0.0
        return float(s)
    except Exception:
        return 0.0
