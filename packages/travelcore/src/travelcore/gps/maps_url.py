"""Convert a Google Maps directions URL into a GPX track with waypoints."""

from __future__ import annotations

import argparse
import json
import re
import sys
import xml.etree.ElementTree as ET
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, unquote, unquote_plus, urlparse
from urllib.request import Request, urlopen

CREATOR = "maps_url_to_gpx"
USER_AGENT = "traveljournal-maps-url-to-gpx/1.0"
DEFAULT_ROUTER = "https://router.project-osrm.org"
NOMINATIM_REVERSE = "https://nominatim.openstreetmap.org/reverse"
_SETTLEMENT_KEYS = ("village", "town", "city", "municipality", "suburb", "hamlet")
_TOKEN = re.compile(r"!(\d+)([A-Za-z])([^!]*)")
_COORD = re.compile(
    r"^(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)(?:\s*,\s*-?\d+(?:\.\d+)?[a-zA-Z]*)?$"
)
_BARE_NUMBER = re.compile(r"^-?\d+(?:\.\d+)?$")
_HOUSE_NUMBER = re.compile(r"\s+\d+[a-zA-Z]?$")
_DIR_IN_HTML = re.compile(
    r"https?://(?:www\.)?google\.[^/\"']+/maps/dir/[^\"'<>\s]+",
    re.IGNORECASE,
)
_PREVIEW_PB = re.compile(
    r"/maps/preview/directions[^\"']*[?&]pb=([^\"'&]+)",
    re.IGNORECASE,
)
_MODE_FROM_ENUM = {
    0: "driving",
    1: "bike",
    2: "foot",
    3: "transit",
    4: "flight",
}
_MODE_FROM_NAME = {
    "driving": "driving",
    "drive": "driving",
    "car": "driving",
    "bicycling": "bike",
    "bicycle": "bike",
    "biking": "bike",
    "bike": "bike",
    "cycling": "bike",
    "walking": "foot",
    "walk": "foot",
    "foot": "foot",
    "transit": "transit",
    "transit_mode": "transit",
    "two-wheeler": "driving",
    "two_wheeler": "driving",
    "flight": "flight",
    "fly": "flight",
}
_OSRM_PROFILE = {
    "driving": "driving",
    "bike": "bike",
    "foot": "foot",
    "transit": "driving",
}
_CURRENT_LOCATION = frozenset(
    {
        "current location",
        "my location",
        "your location",
        "aktueller standort",
        "dein standort",
        "ihr standort",
    }
)
HttpGet = Callable[[str], tuple[str, bytes]]


class MapsGpxError(Exception):
    """User-facing conversion error."""


@dataclass(frozen=True, slots=True)
class Waypoint:
    latitude: float | None
    longitude: float | None
    name: str = ""
    description: str = ""

    @property
    def has_coords(self) -> bool:
        return self.latitude is not None and self.longitude is not None


@dataclass(frozen=True, slots=True)
class Directions:
    waypoints: tuple[Waypoint, ...]
    travel_mode: str = "driving"
    source_url: str = ""

    @property
    def complete(self) -> bool:
        return len(self.waypoints) >= 2 and all(point.has_coords for point in self.waypoints)


def parse_directions_url(url: str) -> Directions:
    """Parse stops and travel mode from an expanded Maps directions URL."""

    parsed = urlparse(url.strip())
    query = {key.lower(): values for key, values in parse_qs(parsed.query, keep_blank_values=True).items()}
    if _is_api_directions(query):
        return _parse_api_url(url, query)
    path = unquote(parsed.path)
    parts = [part for part in path.split("/") if part]
    if "dir" not in (part.lower() for part in parts):
        return Directions(waypoints=(), travel_mode=_mode_from_query(query), source_url=url)
    dir_index = next(index for index, part in enumerate(parts) if part.lower() == "dir")
    raw_stops: list[str] = []
    data_blob = ""
    for part in parts[dir_index + 1 :]:
        if part.lower().startswith("data="):
            data_blob = part[5:]
            break
        if part.startswith("@"):
            continue
        raw_stops.append(part)
    if not data_blob:
        data_values = query.get("data") or []
        data_blob = data_values[0] if data_values else ""
    stops = _waypoints_from_path(raw_stops)
    stops = _fill_from_data_blob(stops, data_blob)
    stops = _fill_names_from_data_blob(stops, data_blob)
    mode = _mode_from_data(data_blob) or _mode_from_query(query)
    return Directions(waypoints=tuple(stops), travel_mode=mode, source_url=url)


def parse_directions_html(html: str, *, source_url: str = "") -> Directions:
    """Read a directions URL and preview protobuf from a Maps HTML page."""

    text = html.replace("&amp;", "&")
    match = _DIR_IN_HTML.search(text)
    from_url = parse_directions_url(unquote(match.group(0))) if match else Directions(waypoints=())
    pb_match = _PREVIEW_PB.search(text)
    from_pb = _waypoints_from_preview_pb(unquote(pb_match.group(1))) if pb_match else []
    merged = list(from_url.waypoints)
    if from_pb:
        merged = _merge_waypoint_lists(merged, from_pb)
    mode = from_url.travel_mode
    return Directions(waypoints=tuple(merged), travel_mode=mode, source_url=source_url or from_url.source_url)


def resolve_directions(url: str, http_get: HttpGet | None = None) -> Directions:
    """Return complete directions, expanding short links when needed."""

    directions = parse_directions_url(url)
    getter = http_get or default_http_get
    if not (directions.complete and _start_end_named(directions)):
        try:
            final_url, body = getter(url)
        except MapsGpxError:
            if not directions.complete:
                raise
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            if not directions.complete:
                raise MapsGpxError(f"Link konnte nicht geladen werden: {exc}") from exc
        else:
            directions = parse_directions_url(final_url)
            html = body.decode("utf-8", errors="replace")
            page = parse_directions_html(html, source_url=final_url)
            directions = _merge_directions(directions, page)
    if not directions.waypoints:
        raise MapsGpxError(
            "Kein Routenlink. Erwartet wird ein Google-Maps-Link aus der Routenplanung "
            "(maps.app.goo.gl oder /maps/dir/…)."
        )
    missing = [point for point in directions.waypoints if not point.has_coords]
    if missing:
        labels = ", ".join(point.name or point.description or "?" for point in missing)
        raise MapsGpxError(f"Für diese Stopps fehlen Koordinaten: {labels}")
    if len(directions.waypoints) < 2:
        raise MapsGpxError("Die Route hat weniger als zwei Stopps.")
    return _fill_missing_place_names(directions, getter)


def route_geometry(
    directions: Directions,
    *,
    router: str = DEFAULT_ROUTER,
    http_get: HttpGet | None = None,
) -> list[tuple[float, float]]:
    """Follow roads between the stops. Flight and unknown modes stay as straight segments."""

    if directions.travel_mode == "flight" or directions.travel_mode not in _OSRM_PROFILE:
        return _straight_geometry(directions)
    profile = _OSRM_PROFILE[directions.travel_mode]
    coords = ";".join(
        f"{point.longitude},{point.latitude}" for point in directions.waypoints if point.has_coords
    )
    base = router.rstrip("/")
    url = f"{base}/route/v1/{profile}/{coords}?overview=full&geometries=geojson"
    getter = http_get or default_http_get
    try:
        _final, body = getter(url)
        payload = json.loads(body.decode("utf-8"))
    except MapsGpxError:
        raise
    except json.JSONDecodeError as exc:
        raise MapsGpxError(f"Ungültige Router-Antwort: {exc.msg}") from exc
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        raise MapsGpxError(f"Router nicht erreichbar: {exc}") from exc
    if payload.get("code") != "Ok" or not payload.get("routes"):
        message = payload.get("message") or payload.get("code") or "unbekannter Fehler"
        raise MapsGpxError(f"Keine Straße zwischen den Stopps: {message}")
    geometry = payload["routes"][0].get("geometry") or {}
    raw_coords = geometry.get("coordinates") or []
    points: list[tuple[float, float]] = []
    for pair in raw_coords:
        if not isinstance(pair, list | tuple) or len(pair) < 2:
            continue
        lon, lat = float(pair[0]), float(pair[1])
        points.append((lat, lon))
    if len(points) < 2:
        raise MapsGpxError("Router lieferte keine Strecke.")
    return points


def directions_to_gpx(
    directions: Directions,
    track_points: Sequence[tuple[float, float]],
    *,
    created_at: datetime | None = None,
) -> str:
    root = ET.Element(
        "gpx",
        {
            "version": "1.1",
            "creator": CREATOR,
            "xmlns": "http://www.topografix.com/GPX/1/1",
        },
    )
    meta = ET.SubElement(root, "metadata")
    track_name = _track_name(directions)
    if track_name:
        ET.SubElement(meta, "name").text = track_name
    stamp = created_at or datetime.now(UTC)
    ET.SubElement(meta, "time").text = _gpx_time(stamp)
    if directions.source_url:
        link = ET.SubElement(meta, "link", {"href": directions.source_url})
        ET.SubElement(link, "text").text = "Google Maps"
    for index, point in enumerate(directions.waypoints, start=1):
        if not point.has_coords:
            continue
        wpt = ET.SubElement(
            root,
            "wpt",
            {"lat": _coord(point.latitude), "lon": _coord(point.longitude)},
        )
        name = point.name or f"Stop {index}"
        ET.SubElement(wpt, "name").text = name
        if point.description and point.description != name:
            ET.SubElement(wpt, "desc").text = point.description
    trk = ET.SubElement(root, "trk")
    if track_name:
        ET.SubElement(trk, "name").text = track_name
    seg = ET.SubElement(trk, "trkseg")
    for latitude, longitude in track_points:
        ET.SubElement(seg, "trkpt", {"lat": _coord(latitude), "lon": _coord(longitude)})
    ET.indent(root, space="  ")
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="unicode") + "\n"


def convert_maps_url(
    url: str,
    dest: Path,
    *,
    waypoints_only: bool = False,
    router: str = DEFAULT_ROUTER,
    http_get: HttpGet | None = None,
    created_at: datetime | None = None,
    directions: Directions | None = None,
) -> Path:
    resolved = directions or resolve_directions(url, http_get=http_get)
    if waypoints_only:
        track = _straight_geometry(resolved)
    else:
        track = route_geometry(resolved, router=router, http_get=http_get)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(directions_to_gpx(resolved, track, created_at=created_at), encoding="utf-8")
    return dest


def route_filename_stem(directions: Directions) -> str:
    """Filesystem stem from the first and last Maps-search stop, e.g. ``Bad-Tölz-to-CAMPING-RUDI``."""

    return _filename_stem(directions)


def default_output_path(url: str, dest: str | None, directions: Directions | None = None) -> Path:
    parsed = directions or parse_directions_url(url)
    stem = route_filename_stem(parsed)
    if not dest:
        return Path.cwd() / f"{stem}.gpx"
    path = Path(dest)
    if (path.exists() and path.is_dir()) or dest.endswith(("/", "\\")):
        return path / f"{stem}.gpx"
    return path


def default_http_get(url: str) -> tuple[str, bytes]:
    request = Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept-Language": "de,en;q=0.8",
        },
    )
    try:
        with urlopen(request, timeout=30) as response:
            return response.geturl(), response.read()
    except HTTPError as exc:
        raise MapsGpxError(f"HTTP {exc.code} für {url}") from exc
    except URLError as exc:
        raise MapsGpxError(f"Netzwerkfehler: {exc.reason}") from exc


def main(argv: Sequence[str] | None = None, *, http_get: HttpGet | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Erzeugt eine GPX-Datei aus einem Google-Maps-Link der Routenplanung. "
            "Stopps kommen aus dem Link, die Strecke folgt OpenStreetMap-Straßen (OSRM)."
        )
    )
    parser.add_argument("url", metavar="URL", help="Google-Maps-Routenlink (auch maps.app.goo.gl)")
    parser.add_argument("-o", metavar="DATEI", dest="output", help="Zieldatei oder Ordner")
    parser.add_argument(
        "--waypoints-only",
        action="store_true",
        help="keine Straßenführung, nur Stopps als Track verbinden",
    )
    parser.add_argument(
        "--router",
        default=DEFAULT_ROUTER,
        metavar="URL",
        help=f"OSRM-Basis-URL (Standard: {DEFAULT_ROUTER})",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        directions = resolve_directions(args.url, http_get=http_get)
        dest = default_output_path(args.url, args.output, directions)
        convert_maps_url(
            args.url,
            dest,
            waypoints_only=args.waypoints_only,
            router=args.router,
            http_get=http_get,
            directions=directions,
        )
    except MapsGpxError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except OSError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(dest)
    return 0


def _parse_api_url(url: str, query: dict[str, list[str]]) -> Directions:
    origin = _first(query, "origin")
    destination = _first(query, "destination")
    raw_via = _first(query, "waypoints") or _first(query, "waypoint")
    stops: list[str] = []
    if origin:
        stops.append(origin)
    if raw_via:
        for item in re.split(r"\||%7C", raw_via, flags=re.IGNORECASE):
            text = unquote_plus(item).strip()
            if text.lower().startswith("via:"):
                text = text[4:].strip()
            if text:
                stops.append(text)
    if destination:
        stops.append(destination)
    mode = _mode_from_name(_first(query, "travelmode") or _first(query, "dirflg")) or "driving"
    return Directions(waypoints=tuple(_waypoints_from_path(stops)), travel_mode=mode, source_url=url)


def _is_api_directions(query: dict[str, list[str]]) -> bool:
    if _first(query, "api") == "1" and (_first(query, "origin") or _first(query, "destination")):
        return True
    return bool(_first(query, "origin") and _first(query, "destination"))


def _waypoints_from_path(raw_stops: Sequence[str]) -> list[Waypoint]:
    stops: list[Waypoint] = []
    for raw in raw_stops:
        text = unquote_plus(raw).strip()
        if not text:
            continue
        coords = _parse_coord_text(text)
        if coords is not None:
            latitude, longitude = coords
            stops.append(Waypoint(latitude=latitude, longitude=longitude, name="", description=text))
            continue
        if text.lower() in _CURRENT_LOCATION:
            raise MapsGpxError(
                "Die Route startet am aktuellen Standort. "
                "In Maps Start und Ziel als Orte setzen und den Link neu kopieren."
            )
        stops.append(
            Waypoint(
                latitude=None,
                longitude=None,
                name=_clean_place_name(text),
                description=text,
            )
        )
    return stops


def _fill_from_data_blob(stops: list[Waypoint], data_blob: str) -> list[Waypoint]:
    if not data_blob:
        return stops
    pairs = _lonlat_pairs(data_blob)
    unused = list(pairs)
    filled: list[Waypoint] = []
    for stop in stops:
        if stop.has_coords:
            filled.append(stop)
            continue
        if not unused:
            filled.append(stop)
            continue
        latitude, longitude = unused.pop(0)
        filled.append(
            replace(
                stop,
                latitude=latitude,
                longitude=longitude,
            )
        )
    return filled


def _fill_names_from_data_blob(stops: list[Waypoint], data_blob: str) -> list[Waypoint]:
    if not data_blob:
        return stops
    labels = _place_labels_from_blob(data_blob)
    if not labels:
        return stops
    unused = list(labels)
    filled: list[Waypoint] = []
    for stop in stops:
        if _place_name(stop) or not unused:
            filled.append(stop)
            continue
        label = unused.pop(0)
        filled.append(replace(stop, name=stop.name or label, description=stop.description or label))
    return filled


def _place_labels_from_blob(blob: str) -> list[str]:
    labels: list[str] = []
    for match in _TOKEN.finditer(blob):
        field, kind, value = _token_parts(match)
        if kind != "s" or field != 1 or not value or value.lower().startswith("0x"):
            continue
        cleaned = _clean_place_name(unquote_plus(value))
        if cleaned:
            labels.append(cleaned)
    return labels


def _lonlat_pairs(blob: str) -> list[tuple[float, float]]:
    pairs: list[tuple[float, float]] = []
    tokens = list(_TOKEN.finditer(blob))
    index = 0
    while index < len(tokens) - 1:
        field, kind, value = _token_parts(tokens[index])
        next_field, next_kind, next_value = _token_parts(tokens[index + 1])
        if kind == "d" and field == 1 and next_kind == "d" and next_field == 2:
            longitude = float(value)
            latitude = float(next_value)
            if abs(latitude) <= 90 and abs(longitude) <= 180:
                pairs.append((latitude, longitude))
            index += 2
            continue
        index += 1
    return pairs


def _waypoints_from_preview_pb(blob: str) -> list[Waypoint]:
    pending_name = ""
    stops: list[Waypoint] = []
    tokens = list(_TOKEN.finditer(blob))
    index = 0
    while index < len(tokens):
        field, kind, value = _token_parts(tokens[index])
        if kind == "s" and field == 1 and not value.lower().startswith("0x"):
            pending_name = unquote_plus(value)
        elif kind == "d" and field == 3 and index + 1 < len(tokens):
            next_field, next_kind, next_value = _token_parts(tokens[index + 1])
            if next_kind == "d" and next_field == 4:
                latitude = float(value)
                longitude = float(next_value)
                description = pending_name
                stops.append(
                    Waypoint(
                        latitude=latitude,
                        longitude=longitude,
                        name=_clean_place_name(description),
                        description=description,
                    )
                )
                pending_name = ""
                index += 2
                continue
        index += 1
    if pending_name:
        stops.append(
            Waypoint(
                latitude=None,
                longitude=None,
                name=_clean_place_name(pending_name),
                description=pending_name,
            )
        )
    return stops


def _merge_directions(primary: Directions, extra: Directions) -> Directions:
    waypoints = _merge_waypoint_lists(list(primary.waypoints), list(extra.waypoints))
    mode = primary.travel_mode or extra.travel_mode or "driving"
    source = extra.source_url or primary.source_url
    return Directions(waypoints=tuple(waypoints), travel_mode=mode, source_url=source)


def _merge_waypoint_lists(primary: list[Waypoint], extra: list[Waypoint]) -> list[Waypoint]:
    if not primary:
        return extra
    if not extra:
        return primary
    if len(primary) == len(extra):
        return [
            Waypoint(
                latitude=left.latitude if left.has_coords else right.latitude,
                longitude=left.longitude if left.has_coords else right.longitude,
                name=_clean_place_name(left.name) or _clean_place_name(right.name),
                description=left.description or right.description,
            )
            for left, right in zip(primary, extra, strict=True)
        ]
    unused = [point for point in extra if point.has_coords]
    merged: list[Waypoint] = []
    extra_index = 0
    for stop in primary:
        if stop.has_coords:
            merged.append(stop)
            continue
        if extra_index < len(unused):
            filler = unused[extra_index]
            extra_index += 1
            merged.append(
                replace(
                    stop,
                    latitude=filler.latitude,
                    longitude=filler.longitude,
                    name=_clean_place_name(stop.name) or _clean_place_name(filler.name),
                    description=stop.description or filler.description,
                )
            )
            continue
        merged.append(stop)
    return merged


def _straight_geometry(directions: Directions) -> list[tuple[float, float]]:
    return [
        (point.latitude, point.longitude)
        for point in directions.waypoints
        if point.latitude is not None and point.longitude is not None
    ]


def _mode_from_data(blob: str) -> str:
    last = ""
    for match in _TOKEN.finditer(blob):
        field, kind, value = _token_parts(match)
        if kind == "e" and field == 3:
            try:
                last = _MODE_FROM_ENUM.get(int(value), "")
            except ValueError:
                continue
    return last


def _mode_from_query(query: dict[str, list[str]]) -> str:
    return _mode_from_name(_first(query, "travelmode") or _first(query, "dirflg")) or "driving"


def _mode_from_name(value: str) -> str:
    if not value:
        return ""
    key = value.strip().lower().replace(" ", "_")
    if len(key) == 1:
        letter = {"d": "driving", "b": "bike", "w": "foot", "r": "transit"}
        return letter.get(key, "")
    return _MODE_FROM_NAME.get(key, "")


def _parse_coord_text(text: str) -> tuple[float, float] | None:
    raw = text.strip()
    match = _COORD.fullmatch(raw)
    if match:
        first = float(match.group(1))
        second = float(match.group(2))
        if abs(first) <= 90 and abs(second) <= 180:
            return first, second
        return None
    parts = [part.strip() for part in raw.split(",") if part.strip()]
    if len(parts) < 2:
        return None
    try:
        first = float(parts[0])
        second = float(parts[1])
    except ValueError:
        return None
    if abs(first) <= 90 and abs(second) <= 180:
        return first, second
    return None


def _is_coord_fragment(text: str) -> bool:
    if not text:
        return False
    if _parse_coord_text(text) is not None:
        return True
    stripped = text.strip()
    if not _BARE_NUMBER.fullmatch(stripped) or stripped.lstrip("-").isdigit():
        return False
    return abs(float(stripped)) <= 180


def _short_name(text: str) -> str:
    """First address field as place name: ``Lähnwald, 6600`` → Lähnwald, ``Häselgehr 122`` → Häselgehr."""

    head = text.split(",")[0].strip()
    cleaned = _HOUSE_NUMBER.sub("", head).strip()
    return cleaned or head or text.strip()


def _clean_place_name(text: str) -> str:
    if not text or _is_coord_fragment(text):
        return ""
    name = _short_name(text)
    if not name or _is_coord_fragment(name):
        return ""
    return name


def _place_name(point: Waypoint) -> str:
    for text in (point.name, point.description):
        cleaned = _clean_place_name(text)
        if cleaned:
            return cleaned
    return ""


def _start_end_named(directions: Directions) -> bool:
    if len(directions.waypoints) < 2:
        return False
    return bool(_place_name(directions.waypoints[0]) and _place_name(directions.waypoints[-1]))


def _fill_missing_place_names(directions: Directions, http_get: HttpGet) -> Directions:
    """Ask Nominatim for village/town names when Maps only stored coordinates."""

    last = len(directions.waypoints) - 1
    filled: list[Waypoint] = []
    changed = False
    for index, point in enumerate(directions.waypoints):
        if index not in (0, last) or _place_name(point) or not point.has_coords:
            filled.append(point)
            continue
        label = _nominatim_place_name(point.latitude, point.longitude, http_get)
        if not label:
            filled.append(point)
            continue
        filled.append(replace(point, name=label, description=point.description or label))
        changed = True
    if not changed:
        return directions
    return replace(directions, waypoints=tuple(filled))


def _nominatim_place_name(latitude: float, longitude: float, http_get: HttpGet) -> str:
    query = (
        f"{NOMINATIM_REVERSE}?lat={latitude}&lon={longitude}"
        "&format=jsonv2&zoom=14&addressdetails=1"
    )
    try:
        _final, body = http_get(query)
        payload = json.loads(body.decode("utf-8"))
    except (MapsGpxError, json.JSONDecodeError, HTTPError, URLError, TimeoutError, OSError):
        return ""
    address = payload.get("address")
    if not isinstance(address, dict):
        return ""
    for key in _SETTLEMENT_KEYS:
        value = address.get(key)
        if isinstance(value, str) and value.strip():
            return _clean_place_name(value) or value.strip()
    return ""


def _stop_label(point: Waypoint, index: int) -> str:
    return _place_name(point) or f"Stop {index}"


def _track_name(directions: Directions) -> str:
    if not directions.waypoints:
        return "Google Maps route"
    start = _stop_label(directions.waypoints[0], 1)
    end = _stop_label(directions.waypoints[-1], len(directions.waypoints))
    if start != end:
        return f"{start} to {end}"
    return start


def _filename_stem(directions: Directions) -> str:
    name = _track_name(directions)
    cleaned = re.sub(r'[<>:"/\\|?*]', "", name)
    cleaned = re.sub(r"\s+", "-", cleaned.strip())
    cleaned = cleaned.strip(".-")
    return cleaned[:80] or "maps-route"


def _gpx_time(value: datetime) -> str:
    stamp = value.astimezone(UTC).replace(microsecond=0)
    return stamp.strftime("%Y-%m-%dT%H:%M:%SZ")


def _coord(value: float | None) -> str:
    assert value is not None
    return f"{value:.8f}".rstrip("0").rstrip(".")


def _first(query: dict[str, list[str]], name: str) -> str:
    values = query.get(name) or []
    return unquote_plus(values[0]).strip() if values else ""


def _token_parts(match: re.Match[str]) -> tuple[int, str, str]:
    return int(match.group(1)), match.group(2), match.group(3)


if __name__ == "__main__":
    raise SystemExit(main())
