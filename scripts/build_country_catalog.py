"""Build the local country catalog (flags + simplified silhouettes + DE/EN names).

Sources (downloaded into build/country-catalog-cache/, not committed):
  - lipis/flag-icons (MIT) 4x3 SVG flags
  - datasets/geo-countries (Natural Earth 10m, PDDL / public domain) polygons
  - Unicode CLDR territory names (de, en)

Run from the repo root:

    .\\.venv\\Scripts\\python.exe scripts\\build_country_catalog.py
"""

from __future__ import annotations

import json
import math
import re
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "build" / "country-catalog-cache"
OUT = ROOT / "packages" / "travelcore" / "src" / "travelcore" / "geo" / "data"

FLAG_VERSION = "7.3.2"
FLAG_ZIP_URL = f"https://github.com/lipis/flag-icons/archive/refs/tags/v{FLAG_VERSION}.zip"
GEOJSON_URL = "https://raw.githubusercontent.com/datasets/geo-countries/main/data/countries.geojson"
CLDR_DE_URL = (
    "https://raw.githubusercontent.com/unicode-org/cldr-json/main/cldr-json/"
    "cldr-localenames-full/main/de/territories.json"
)
CLDR_EN_URL = (
    "https://raw.githubusercontent.com/unicode-org/cldr-json/main/cldr-json/"
    "cldr-localenames-full/main/en/territories.json"
)

_ISO2 = re.compile(r"^[A-Za-z]{2}$")
_NAME_ISO = {
    "kosovo": "XK",
    "france": "FR",
    "norway": "NO",
    "taiwan": "TW",
}
_USER_AGENT = "traveljournal-country-catalog/1.0"

NOTICE = """Country assets bundled with Reisetagebuch
=============================================

Flags
-----
SVG flags from lipis/flag-icons (MIT License), 4x3 ratio.
https://github.com/lipis/flag-icons
Pinned version: {flag_version}

Country outlines
----------------
Simplified from datasets/geo-countries (Open Data Commons PDDL 1.0).
Original cartography: Natural Earth (public domain).
https://github.com/datasets/geo-countries
https://www.naturalearthdata.com/

Names
-----
German and English territory names from Unicode CLDR.
https://github.com/unicode-org/cldr-json
"""


def main() -> int:
    CACHE.mkdir(parents=True, exist_ok=True)
    flags_dir = _extract_flags()
    names_de, aliases_de = _cldr_names(CLDR_DE_URL, CACHE / "cldr-de-territories.json")
    names_en, aliases_en = _cldr_names(CLDR_EN_URL, CACHE / "cldr-en-territories.json")
    features = _load_geojson()

    out_flags = OUT / "flags"
    out_shapes = OUT / "shapes"
    if OUT.exists():
        for child in (out_flags, out_shapes):
            if child.exists():
                for path in child.glob("*.svg"):
                    path.unlink()
        catalog_path = OUT / "catalog.json"
        if catalog_path.exists():
            catalog_path.unlink()
    out_flags.mkdir(parents=True, exist_ok=True)
    out_shapes.mkdir(parents=True, exist_ok=True)

    countries: list[dict[str, object]] = []
    skipped: list[str] = []
    for feature in features:
        props = feature.get("properties") or {}
        geometry = feature.get("geometry") or {}
        iso = _iso2(props)
        name_en_src = str(props.get("name") or "").strip()
        if iso is None:
            skipped.append(f"no-iso:{name_en_src or '?'}")
            continue
        flag_src = flags_dir / f"{iso.lower()}.svg"
        if not flag_src.is_file():
            skipped.append(f"no-flag:{iso}")
            continue
        rings = _silhouette_rings(geometry)
        if not rings:
            skipped.append(f"no-shape:{iso}")
            continue
        svg = _rings_to_svg(rings)
        if svg is None:
            skipped.append(f"empty-svg:{iso}")
            continue
        name_de = names_de.get(iso) or name_en_src or iso
        name_en = names_en.get(iso) or name_en_src or iso
        aliases = tuple(
            dict.fromkeys(
                item
                for item in (
                    *aliases_de.get(iso, ()),
                    *aliases_en.get(iso, ()),
                    name_en_src,
                )
                if item and item.casefold() not in {name_de.casefold(), name_en.casefold(), iso.casefold()}
            )
        )
        (out_flags / f"{iso.lower()}.svg").write_bytes(flag_src.read_bytes())
        (out_shapes / f"{iso.lower()}.svg").write_text(svg, encoding="utf-8")
        entry: dict[str, object] = {
            "iso2": iso,
            "name_de": name_de,
            "name_en": name_en,
            "flag": f"flags/{iso.lower()}.svg",
            "shape": f"shapes/{iso.lower()}.svg",
        }
        if aliases:
            entry["aliases"] = list(aliases)
        countries.append(entry)

    countries.sort(key=lambda item: str(item["name_de"]).casefold())
    catalog = {
        "schema_version": 1,
        "sources": {
            "flags": f"lipis/flag-icons v{FLAG_VERSION}",
            "shapes": "datasets/geo-countries (Natural Earth 10m, simplified)",
            "names": "CLDR de/en territories",
        },
        "countries": countries,
    }
    (OUT / "catalog.json").write_text(
        json.dumps(catalog, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (OUT / "NOTICE.txt").write_text(NOTICE.format(flag_version=FLAG_VERSION), encoding="utf-8")
    flag_bytes = sum(path.stat().st_size for path in out_flags.glob("*.svg"))
    shape_bytes = sum(path.stat().st_size for path in out_shapes.glob("*.svg"))
    print(f"countries: {len(countries)}")
    print(f"flags:     {flag_bytes / 1024:.0f} KiB")
    print(f"shapes:    {shape_bytes / 1024:.0f} KiB")
    print(f"skipped:   {len(skipped)}")
    if skipped:
        print("  " + ", ".join(skipped[:24]) + (" …" if len(skipped) > 24 else ""))
    return 0


def _iso2(props: dict) -> str | None:
    raw = str(props.get("ISO3166-1-Alpha-2") or "").strip().upper()
    if raw in {"CN-TW", "TW"}:
        return "TW"
    if _ISO2.fullmatch(raw):
        return raw
    name = str(props.get("name") or "").strip().casefold()
    return _NAME_ISO.get(name)


def _extract_flags() -> Path:
    archive = CACHE / f"flag-icons-{FLAG_VERSION}.zip"
    _download(FLAG_ZIP_URL, archive)
    target = CACHE / f"flag-icons-{FLAG_VERSION}" / "flags" / "4x3"
    if target.is_dir() and any(target.glob("*.svg")):
        return target
    with zipfile.ZipFile(archive) as zf:
        zf.extractall(CACHE)
    if not target.is_dir():
        raise SystemExit(f"flag-icons 4x3 folder missing in zip: {target}")
    return target


def _load_geojson() -> list[dict]:
    path = CACHE / "countries.geojson"
    _download(GEOJSON_URL, path)
    data = json.loads(path.read_text(encoding="utf-8"))
    features = data.get("features")
    if not isinstance(features, list) or not features:
        raise SystemExit("geo-countries GeoJSON has no features")
    return features


def _cldr_names(url: str, cache_path: Path) -> tuple[dict[str, str], dict[str, tuple[str, ...]]]:
    _download(url, cache_path)
    payload = json.loads(cache_path.read_text(encoding="utf-8"))
    locale = "de" if "-de-" in cache_path.name else "en"
    territories = payload.get("main", {}).get(locale, {}).get("localeDisplayNames", {}).get("territories", {})
    names: dict[str, str] = {}
    aliases: dict[str, list[str]] = {}
    for key, value in territories.items():
        if not isinstance(value, str) or not value.strip():
            continue
        if _ISO2.fullmatch(key):
            names[key.upper()] = value.strip()
            continue
        if key.endswith("-alt-short") and _ISO2.fullmatch(key[:2]):
            aliases.setdefault(key[:2].upper(), []).append(value.strip())
    return names, {key: tuple(dict.fromkeys(items)) for key, items in aliases.items()}


def _download(url: str, path: Path) -> None:
    if path.is_file() and path.stat().st_size > 0:
        return
    print(f"download {url}")
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(request) as response:
        data = response.read()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _silhouette_rings(geometry: dict) -> list[list[tuple[float, float]]]:
    kind = geometry.get("type")
    coords = geometry.get("coordinates")
    polygons: list[list[list[tuple[float, float]]]] = []
    if kind == "Polygon":
        poly = _as_polygon(coords)
        if poly:
            polygons.append(poly)
    elif kind == "MultiPolygon":
        if isinstance(coords, list):
            for item in coords:
                poly = _as_polygon(item)
                if poly:
                    polygons.append(poly)
    if not polygons:
        return []
    selected = _cluster_polygons(polygons)
    simplified: list[list[tuple[float, float]]] = []
    for ring in selected:
        simple = _simplify_ring(ring)
        if len(simple) >= 4:
            simplified.append(simple)
    return _unwrap_longitudes(simplified)


def _as_polygon(coords: object) -> list[list[tuple[float, float]]] | None:
    if not isinstance(coords, list) or not coords:
        return None
    rings: list[list[tuple[float, float]]] = []
    for ring in coords:
        points = _as_ring(ring)
        if points is not None:
            rings.append(points)
    return rings or None


def _as_ring(ring: object) -> list[tuple[float, float]] | None:
    if not isinstance(ring, list) or len(ring) < 4:
        return None
    points: list[tuple[float, float]] = []
    for item in ring:
        if not isinstance(item, (list, tuple)) or len(item) < 2:
            continue
        points.append((float(item[0]), float(item[1])))
    if len(points) < 4:
        return None
    return points


def _cluster_polygons(
    polygons: list[list[list[tuple[float, float]]]],
) -> list[list[tuple[float, float]]]:
    infos: list[tuple[float, tuple[float, float], list[list[tuple[float, float]]]]] = []
    for poly in polygons:
        exterior = poly[0]
        area = _shoelace(exterior)
        if area <= 0:
            continue
        cx = sum(p[0] for p in exterior) / len(exterior)
        cy = sum(p[1] for p in exterior) / len(exterior)
        infos.append((area, (cx, cy), poly))
    if not infos:
        return []
    infos.sort(key=lambda item: item[0], reverse=True)
    selected = [infos[0]]
    remaining = infos[1:]
    largest = infos[0][0]
    changed = True
    while changed:
        changed = False
        kept: list[tuple[float, tuple[float, float], list[list[tuple[float, float]]]]] = []
        for item in remaining:
            area, centroid, _poly = item
            dist = min(_wrap_dist(centroid, other[1]) for other in selected)
            if dist < 22.0 or (area > 0.02 * largest and dist < 38.0):
                selected.append(item)
                changed = True
            else:
                kept.append(item)
        remaining = kept
    main = selected[0][1]
    rings: list[list[tuple[float, float]]] = []
    for _area, centroid, poly in selected:
        if _wrap_dist(centroid, main) > 48.0:
            continue
        rings.extend(poly)
    return rings


def _unwrap_longitudes(rings: list[list[tuple[float, float]]]) -> list[list[tuple[float, float]]]:
    if not rings:
        return rings
    shifted: list[list[tuple[float, float]]] = []
    for ring in rings:
        lons = [p[0] for p in ring]
        if max(lons) - min(lons) > 180:
            shifted.append([(lon + 360.0 if lon < 0 else lon, lat) for lon, lat in ring])
        else:
            shifted.append(ring)
    xs = [p[0] for ring in shifted for p in ring]
    if xs and max(xs) - min(xs) > 180:
        shifted = [[(lon + 360.0 if lon < 0 else lon, lat) for lon, lat in ring] for ring in shifted]
    return shifted


def _simplify_ring(ring: list[tuple[float, float]], *, max_points: int = 140) -> list[tuple[float, float]]:
    pts = ring[:-1] if ring[0] == ring[-1] else list(ring)
    if len(pts) <= 8:
        closed = list(pts)
        if closed and closed[0] != closed[-1]:
            closed.append(closed[0])
        return closed
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    span = max(max(xs) - min(xs), max(ys) - min(ys), 0.0004)
    eps = min(0.06, max(span * 0.012, 0.00025))
    simplified = pts
    for _ in range(10):
        simplified = _rdp(pts, eps)
        if len(simplified) <= max_points:
            break
        eps *= 1.7
    if len(simplified) < 3:
        simplified = pts[: min(8, len(pts))]
    if simplified[0] != simplified[-1]:
        simplified.append(simplified[0])
    return simplified


def _rdp(points: list[tuple[float, float]], epsilon: float) -> list[tuple[float, float]]:
    if len(points) < 3:
        return list(points)
    keep = [False] * len(points)
    keep[0] = True
    keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        start, end = stack.pop()
        a = points[start]
        b = points[end]
        max_d = -1.0
        index = start
        for i in range(start + 1, end):
            dist = _perp_dist(points[i], a, b)
            if dist > max_d:
                max_d = dist
                index = i
        if max_d > epsilon:
            keep[index] = True
            stack.append((start, index))
            stack.append((index, end))
    return [point for point, flag in zip(points, keep, strict=True) if flag]


def _perp_dist(point: tuple[float, float], start: tuple[float, float], end: tuple[float, float]) -> float:
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    if dx == 0 and dy == 0:
        return math.hypot(point[0] - start[0], point[1] - start[1])
    length = math.hypot(dx, dy)
    return abs(dy * point[0] - dx * point[1] + end[0] * start[1] - end[1] * start[0]) / length


def _shoelace(ring: list[tuple[float, float]]) -> float:
    area = 0.0
    for i in range(len(ring) - 1):
        x1, y1 = ring[i]
        x2, y2 = ring[i + 1]
        area += x1 * y2 - x2 * y1
    return abs(area) / 2.0


def _wrap_dist(a: tuple[float, float], b: tuple[float, float]) -> float:
    dlon = abs(a[0] - b[0])
    if dlon > 180:
        dlon = 360 - dlon
    return math.hypot(dlon, a[1] - b[1])


def _rings_to_svg(rings: list[list[tuple[float, float]]]) -> str | None:
    xs = [p[0] for ring in rings for p in ring]
    ys = [p[1] for ring in rings for p in ring]
    if not xs or not ys:
        return None
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    width = max(max_x - min_x, 0.01)
    height = max(max_y - min_y, 0.01)
    pad_x = width * 0.06
    pad_y = height * 0.06
    view_x = min_x - pad_x
    view_y = -(max_y + pad_y)
    view_w = width + 2 * pad_x
    view_h = height + 2 * pad_y
    parts: list[str] = []
    for ring in rings:
        commands: list[str] = []
        for index, (lon, lat) in enumerate(ring):
            x = _fmt(lon)
            y = _fmt(-lat)
            commands.append(("M" if index == 0 else "L") + f"{x} {y}")
        parts.append(" ".join(commands) + " Z")
    path = " ".join(parts)
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="{_fmt(view_x)} {_fmt(view_y)} {_fmt(view_w)} {_fmt(view_h)}" '
        f'preserveAspectRatio="xMidYMid meet">'
        f'<path fill="#000000" fill-rule="evenodd" d="{path}"/></svg>\n'
    )


def _fmt(value: float) -> str:
    text = f"{value:.2f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except OSError as exc:
        print(f"country catalog build failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
