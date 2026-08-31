"""ISO-2 country catalog with German names, flag SVG, and silhouette SVG."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

_DATA = Path(__file__).resolve().parent / "data"
_CATALOG_FILE = "catalog.json"


@dataclass(frozen=True, slots=True)
class Country:
    iso2: str
    name_de: str
    name_en: str
    aliases: tuple[str, ...]
    flag_svg: Path
    shape_svg: Path

    @property
    def label(self) -> str:
        return self.name_de


def data_dir() -> Path:
    return _DATA


@lru_cache(maxsize=1)
def load_catalog() -> tuple[Country, ...]:
    path = _DATA / _CATALOG_FILE
    raw = json.loads(path.read_text(encoding="utf-8"))
    items = raw.get("countries")
    if not isinstance(items, list) or not items:
        raise FileNotFoundError(f"Länderkatalog leer: {path}")
    countries: list[Country] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        iso2 = str(item.get("iso2") or "").strip().upper()
        flag = _DATA / str(item.get("flag") or "")
        shape = _DATA / str(item.get("shape") or "")
        if len(iso2) != 2 or not flag.is_file() or not shape.is_file():
            continue
        aliases = item.get("aliases") or ()
        countries.append(
            Country(
                iso2=iso2,
                name_de=str(item.get("name_de") or iso2),
                name_en=str(item.get("name_en") or iso2),
                aliases=tuple(str(alias) for alias in aliases if str(alias).strip()),
                flag_svg=flag,
                shape_svg=shape,
            )
        )
    if not countries:
        raise FileNotFoundError(f"Länderkatalog ohne gültige Einträge: {path}")
    return tuple(countries)


@lru_cache(maxsize=1)
def _by_iso() -> dict[str, Country]:
    return {item.iso2: item for item in load_catalog()}


@lru_cache(maxsize=1)
def _by_name() -> dict[str, str]:
    index: dict[str, str] = {}
    for item in load_catalog():
        index[item.iso2.casefold()] = item.iso2
        for token in (item.name_de, item.name_en, *item.aliases):
            key = token.casefold()
            index.setdefault(key, item.iso2)
    return index


def list_countries() -> tuple[Country, ...]:
    return load_catalog()


def get_country(iso2: str | None) -> Country | None:
    if not iso2 or not str(iso2).strip():
        return None
    return _by_iso().get(str(iso2).strip().upper())


def resolve_token(token: str | None) -> str | None:
    """Return ISO-2 when ``token`` is a code, German/English name, or alias."""

    if not token or not str(token).strip():
        return None
    return _by_name().get(str(token).strip().casefold())


def resolve_countries(tokens: Sequence[str]) -> tuple[Country, ...]:
    found: list[Country] = []
    seen: set[str] = set()
    for token in tokens:
        iso = resolve_token(token) or str(token).strip().upper()
        country = get_country(iso)
        if country is None or country.iso2 in seen:
            continue
        seen.add(country.iso2)
        found.append(country)
    return tuple(found)


def country_label(token: str) -> str:
    country = get_country(token) or next(iter(resolve_countries((token,))), None)
    if country is not None:
        return country.name_de
    return token.strip()


def search_countries(query: str, *, limit: int = 12) -> tuple[Country, ...]:
    needle = query.strip().casefold()
    if not needle:
        return load_catalog()[:limit]
    exact: list[Country] = []
    prefix: list[Country] = []
    contains: list[Country] = []
    for item in load_catalog():
        haystacks = (item.iso2.casefold(), item.name_de.casefold(), item.name_en.casefold()) + tuple(
            alias.casefold() for alias in item.aliases
        )
        if needle in {item.iso2.casefold()} or needle == item.name_de.casefold():
            exact.append(item)
            continue
        if any(text.startswith(needle) for text in haystacks):
            prefix.append(item)
            continue
        if any(needle in text for text in haystacks):
            contains.append(item)
    ranked = exact + prefix + contains
    return tuple(ranked[:limit])
