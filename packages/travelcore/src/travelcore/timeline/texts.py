"""Prefill day title and journal text from imported note files."""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

JOURNAL_TEXT_SUFFIXES = {".txt", ".md", ".markdown"}
_DATE_PREFIX = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")
_MAX_TITLE_LEN = 120


def date_from_text_filename(filename: str) -> date | None:
    """ISO date at the start of the stem, e.g. ``2025-05-15.md`` or ``2025-05-15 Bozen.txt``."""

    match = _DATE_PREFIX.match(Path(filename).stem)
    if match is None:
        return None
    try:
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None


def title_from_text_filename(filename: str) -> str | None:
    """Human title leftover after an optional ISO date prefix."""

    stem = Path(filename).stem.strip()
    leftover = _DATE_PREFIX.sub("", stem, count=1).strip(" \t-–_")
    if leftover and leftover != stem:
        return leftover
    if _DATE_PREFIX.match(stem):
        return None
    return stem or None


def parse_imported_text(body: str, filename: str = "") -> tuple[str | None, str]:
    """Split a note into (title, remainder). Markdown headings win over the first line."""

    lines = body.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    heading_at: int | None = None
    heading: str | None = None
    first_line_at: int | None = None
    first_line: str | None = None
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            heading = stripped.lstrip("#").strip() or None
            heading_at = index
            break
        first_line = stripped
        first_line_at = index
        break
    if heading_at is not None:
        rest = "\n".join(lines[heading_at + 1 :]).strip()
        return heading, rest
    if first_line is not None and first_line_at is not None and len(first_line) <= _MAX_TITLE_LEN:
        rest = "\n".join(lines[first_line_at + 1 :]).strip()
        return first_line, rest
    fallback = title_from_text_filename(filename)
    return fallback, body.strip()


def read_imported_text(path: Path) -> tuple[str | None, str]:
    """Read a UTF-8 note file. Missing or unreadable files yield empty text."""

    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return title_from_text_filename(path.name), ""
    return parse_imported_text(raw, filename=path.name)


def combine_imported_texts(parts: list[tuple[str | None, str]]) -> tuple[str | None, str | None]:
    """First non-empty title wins; bodies are joined with a blank line."""

    titles = [title for title, _body in parts if title]
    bodies = [body.strip() for _title, body in parts if body.strip()]
    title = titles[0] if titles else None
    notes = "\n\n".join(bodies) if bodies else None
    return title, notes
