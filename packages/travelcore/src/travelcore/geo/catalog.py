"""ISO-2 country catalog with German names, flag SVG, and silhouette SVG."""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache
from math import hypot
from pathlib import Path

_DATA = Path(__file__).resolve().parent / "data"
_CATALOG_FILE = "catalog.json"
_VIEWBOX = re.compile(r'viewBox="([^"]+)"')
_PATH_D = re.compile(r'\sd="([^"]+)"')
_PATH_TOKEN = re.compile(r"[MmLlZz]|[-+]?(?:\d+\.?\d*|\.\d+)")
_NEAR_DEG = 0.35
_SHALLOW_DEG = 0.12
_ENCLAVE_AREA_RATIO = 0.18


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


def outline_rings(iso2: str) -> tuple[tuple[tuple[float, float], ...], ...]:
    """Silhouette path rings (x = longitude, y = −latitude). Empty if unknown."""

    return _country_rings(str(iso2).strip().upper())


def shape_lonlat_box(country: Country) -> tuple[float, float, float, float] | None:
    """Bounding box of the silhouette: ``(min_lon, min_lat, max_lon, max_lat)``.

    Outlines are stored with SVG ``x = longitude`` and ``y = -latitude``.
    """

    return _country_box(country.iso2)


def country_at(
    latitude: float,
    longitude: float,
    *,
    preferred: Sequence[str] = (),
) -> Country | None:
    """Country whose silhouette contains the point.

    Adjacent states (Germany/Austria) are resolved by how far the pin sits
    inside the outline, then by country size so a larger neighbour wins when
    simplified borders overlap. Tiny nested states (enclaves) still beat the
    surrounding country. ``preferred`` trip codes only break ties among
    similarly large hits.
    """

    preferred_iso = {item.iso2 for item in resolve_countries(preferred)}
    scored = _score_countries(latitude, longitude)
    if not scored:
        return None
    inside = [row for row in scored if row[0] <= 0.0]
    if not inside:
        nearest = min(scored, key=lambda row: row[0])
        return nearest[2] if nearest[0] <= _NEAR_DEG else None
    nested = _nested_hits(inside)
    if nested:
        return min(nested, key=lambda row: row[1])[2]
    deepest = min(inside, key=lambda row: row[0])
    contenders = [row for row in inside if row[0] <= deepest[0] + _SHALLOW_DEG]
    best_area = max(row[1] for row in contenders)
    similar = [row for row in contenders if row[1] >= 0.5 * best_area]
    preferred_similar = [row for row in similar if row[2].iso2 in preferred_iso]
    pool = preferred_similar or similar
    return max(pool, key=lambda row: row[1])[2]


def _score_countries(latitude: float, longitude: float) -> list[tuple[float, float, Country]]:
    rows: list[tuple[float, float, Country]] = []
    for country in load_catalog():
        box = _country_box(country.iso2)
        if box is None or not _box_contains(box, latitude, longitude, pad=_NEAR_DEG):
            continue
        signed = _signed_distance(country.iso2, latitude, longitude)
        if signed is None or signed > _NEAR_DEG:
            continue
        min_lon, min_lat, max_lon, max_lat = box
        area = max(max_lon - min_lon, 0.0) * max(max_lat - min_lat, 0.0)
        rows.append((signed, area, country))
    return rows


def _nested_hits(
    hits: Sequence[tuple[float, float, Country]],
) -> list[tuple[float, float, Country]]:
    nested: list[tuple[float, float, Country]] = []
    for item in hits:
        inner = _country_box(item[2].iso2)
        if inner is None:
            continue
        if any(
            other is not item
            and (outer := _country_box(other[2].iso2)) is not None
            and _bbox_contained(inner, outer)
            and item[1] < _ENCLAVE_AREA_RATIO * other[1]
            for other in hits
        ):
            nested.append(item)
    return nested


@lru_cache(maxsize=256)
def _country_box(iso2: str) -> tuple[float, float, float, float] | None:
    country = get_country(iso2)
    if country is None or not country.shape_svg.is_file():
        return None
    match = _VIEWBOX.search(country.shape_svg.read_text(encoding="utf-8"))
    if match is None:
        return None
    parts = match.group(1).split()
    if len(parts) != 4:
        return None
    min_x, min_y, width, height = (float(part) for part in parts)
    return (min_x, -(min_y + height), min_x + width, -min_y)


def _signed_distance(iso2: str, latitude: float, longitude: float) -> float | None:
    rings = _country_rings(iso2)
    if not rings:
        return None
    best: float | None = None
    for candidate in (longitude, longitude + 360.0, longitude - 360.0):
        dist = _edge_distance(candidate, -latitude, rings)
        signed = -dist if _path_contains(candidate, -latitude, rings) else dist
        if best is None or signed < best:
            best = signed
    return best


def _edge_distance(x: float, y: float, rings: Sequence[Sequence[tuple[float, float]]]) -> float:
    best = float("inf")
    for ring in rings:
        length = len(ring)
        if length < 2:
            continue
        for index in range(length):
            x1, y1 = ring[index]
            x2, y2 = ring[(index + 1) % length]
            best = min(best, _point_segment_distance(x, y, x1, y1, x2, y2))
    return best if best < float("inf") else 0.0


def _point_segment_distance(
    px: float, py: float, x1: float, y1: float, x2: float, y2: float
) -> float:
    dx = x2 - x1
    dy = y2 - y1
    if dx == 0.0 and dy == 0.0:
        return hypot(px - x1, py - y1)
    span = dx * dx + dy * dy
    t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / span))
    return hypot(px - (x1 + t * dx), py - (y1 + t * dy))


def _bbox_contained(
    inner: tuple[float, float, float, float],
    outer: tuple[float, float, float, float],
    *,
    slack: float = 0.2,
) -> bool:
    return (
        inner[0] >= outer[0] - slack
        and inner[1] >= outer[1] - slack
        and inner[2] <= outer[2] + slack
        and inner[3] <= outer[3] + slack
    )


@lru_cache(maxsize=256)
def _country_rings(iso2: str) -> tuple[tuple[tuple[float, float], ...], ...]:
    country = get_country(iso2)
    if country is None or not country.shape_svg.is_file():
        return ()
    match = _PATH_D.search(country.shape_svg.read_text(encoding="utf-8"))
    if match is None:
        return ()
    rings: list[tuple[tuple[float, float], ...]] = []
    current: list[tuple[float, float]] = []
    tokens = _PATH_TOKEN.findall(match.group(1))
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token in {"Z", "z"}:
            if len(current) >= 3:
                rings.append(tuple(current))
            current = []
            index += 1
            continue
        if token in {"M", "m", "L", "l"}:
            index += 1
            continue
        if index + 1 >= len(tokens):
            break
        try:
            current.append((float(token), float(tokens[index + 1])))
        except ValueError:
            break
        index += 2
    if len(current) >= 3:
        rings.append(tuple(current))
    return tuple(rings)


def _path_contains(x: float, y: float, rings: Sequence[Sequence[tuple[float, float]]]) -> bool:
    crossings = 0
    for ring in rings:
        crossings += _ray_crossings(x, y, ring)
    return crossings % 2 == 1


def _ray_crossings(x: float, y: float, ring: Sequence[tuple[float, float]]) -> int:
    count = 0
    length = len(ring)
    if length < 3:
        return 0
    for index in range(length):
        x1, y1 = ring[index]
        x2, y2 = ring[(index + 1) % length]
        if (y1 > y) == (y2 > y) or y1 == y2:
            continue
        at_x = x1 + (x2 - x1) * (y - y1) / (y2 - y1)
        if at_x > x:
            count += 1
    return count


def _box_contains(
    box: tuple[float, float, float, float],
    latitude: float,
    longitude: float,
    *,
    pad: float = 0.0,
) -> bool:
    min_lon, min_lat, max_lon, max_lat = box
    if latitude < min_lat - pad or latitude > max_lat + pad:
        return False
    return any(
        min_lon - pad <= candidate <= max_lon + pad
        for candidate in (longitude, longitude + 360.0, longitude - 360.0)
    )


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
