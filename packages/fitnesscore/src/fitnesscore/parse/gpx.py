"""Write GPX 1.1 from parsed tracks."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from collections.abc import Sequence

from fitnesscore.parse.common import format_coord, format_number, gpx_time
from fitnesscore.parse.types import ParsedTrack

CREATOR = "fitnesscore"


def tracks_to_gpx(tracks: Sequence[ParsedTrack], *, creator: str = CREATOR) -> str:
    root = ET.Element(
        "gpx",
        {
            "version": "1.1",
            "creator": creator,
            "xmlns": "http://www.topografix.com/GPX/1/1",
        },
    )
    first_time = next(
        (point.recorded_at for track in tracks for point in track.points if point.recorded_at),
        None,
    )
    if tracks or first_time is not None:
        meta = ET.SubElement(root, "metadata")
        if tracks and tracks[0].name:
            ET.SubElement(meta, "name").text = tracks[0].name
        if first_time is not None:
            ET.SubElement(meta, "time").text = gpx_time(first_time)
    for track in tracks:
        trk = ET.SubElement(root, "trk")
        if track.name:
            ET.SubElement(trk, "name").text = track.name
        seg = ET.SubElement(trk, "trkseg")
        for point in track.points:
            trkpt = ET.SubElement(
                seg,
                "trkpt",
                {"lat": format_coord(point.latitude), "lon": format_coord(point.longitude)},
            )
            if point.elevation is not None:
                ET.SubElement(trkpt, "ele").text = format_number(point.elevation)
            if point.recorded_at is not None:
                ET.SubElement(trkpt, "time").text = gpx_time(point.recorded_at)
    ET.indent(root, space="  ")
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="unicode") + "\n"


def bbox(tracks: Sequence[ParsedTrack]) -> tuple[float, float, float, float] | None:
    lats: list[float] = []
    lons: list[float] = []
    for track in tracks:
        for point in track.points:
            lats.append(point.latitude)
            lons.append(point.longitude)
    if not lats:
        return None
    return min(lats), max(lats), min(lons), max(lons)
