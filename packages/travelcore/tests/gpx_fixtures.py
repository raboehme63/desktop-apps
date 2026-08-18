"""Synthetic GPX files for tests. Coordinates are documentary examples, not personal tracks."""

from __future__ import annotations

from pathlib import Path


def write_gpx(
    path: Path,
    points: list[tuple[float, float, float | None, str | None]],
    *,
    name: str = "Testtrack",
    extra_segment: list[tuple[float, float, float | None, str | None]] | None = None,
) -> Path:
    """Write a GPX 1.1 track. Each point is (lat, lon, ele, iso8601 time or None)."""

    def segment_xml(rows: list[tuple[float, float, float | None, str | None]]) -> str:
        parts: list[str] = ["<trkseg>"]
        for latitude, longitude, elevation, recorded in rows:
            body = ""
            if elevation is not None:
                body += f"<ele>{elevation}</ele>"
            if recorded:
                body += f"<time>{recorded}</time>"
            parts.append(f'<trkpt lat="{latitude}" lon="{longitude}">{body}</trkpt>')
        parts.append("</trkseg>")
        return "".join(parts)

    segments = segment_xml(points)
    if extra_segment:
        segments += segment_xml(extra_segment)
    path.write_text(
        (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<gpx version="1.1" creator="travelcore-test" '
            'xmlns="http://www.topografix.com/GPX/1/1">'
            f"<trk><name>{name}</name>{segments}</trk></gpx>"
        ),
        encoding="utf-8",
    )
    return path
