"""Visited countries stored as ISO-3166-1 alpha-2 codes (one per line)."""

from __future__ import annotations

from collections.abc import Sequence

from travelcore.geo.catalog import country_label, resolve_token


def parse_countries(raw: str | None) -> tuple[str, ...]:
    if not raw or not str(raw).strip():
        return ()
    codes: list[str] = []
    seen: set[str] = set()
    for chunk in str(raw).replace(",", "\n").splitlines():
        token = chunk.strip()
        if not token:
            continue
        iso = resolve_token(token) or token
        key = iso.casefold()
        if key in seen:
            continue
        seen.add(key)
        codes.append(iso)
    return tuple(codes)


def serialize_countries(names: Sequence[str]) -> str | None:
    cleaned = parse_countries("\n".join(str(item) for item in names))
    if not cleaned:
        return None
    return "\n".join(cleaned)


def country_labels(tokens: Sequence[str]) -> tuple[str, ...]:
    return tuple(country_label(token) for token in tokens)
