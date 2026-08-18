"""Folium/Leaflet map renderer. Original media files are never written."""

from __future__ import annotations

import html
from pathlib import Path
from typing import Protocol, runtime_checkable

import folium
from folium.plugins import MarkerCluster

from travelcore.maps.scene import FLIGHT_LINE_MIN_ZOOM, MapMarker, MapPolyline, MapScene

_OSM = "OpenStreetMap"


@runtime_checkable
class MapBackend(Protocol):
    """Write an interactive map document for display in a web view."""

    def render(self, scene: MapScene, output_html: Path) -> Path: ...


class FoliumMapBackend:
    """Leaflet via Folium. Remote tiles are optional; vectors are always local."""

    def __init__(self, *, tiles: str | None = _OSM) -> None:
        self.tiles = tiles

    def render(self, scene: MapScene, output_html: Path) -> Path:
        location = scene.center or (50.0, 10.0)
        zoom = 6 if scene.center is not None else 4
        fmap = folium.Map(location=location, zoom_start=zoom, tiles=self.tiles, control_scale=True)
        track_layer = folium.FeatureGroup(name="Tracks", show=True)
        flight_layer = folium.FeatureGroup(name="Flugtracks (IGC)", show=True)
        flight_ends = folium.FeatureGroup(name="Start / Landung", show=True)
        stay_layer = folium.FeatureGroup(name="Übernachtungen", show=True)
        place_layer = folium.FeatureGroup(name="Orte", show=True)
        day_clusters: dict[str, MarkerCluster] = {}
        has_flights = False

        for line in scene.polylines:
            target = flight_layer if line.kind == "flight" else track_layer
            folium.PolyLine(
                locations=list(line.points),
                color=line.color,
                weight=3.5 if line.kind == "flight" else 3,
                opacity=0.9 if line.kind == "flight" else 0.85,
                tooltip=line.name,
                popup=_line_popup(line),
            ).add_to(target)
            if line.kind == "flight" and line.points:
                has_flights = True
                _flight_end_markers(line, flight_ends)

        for marker in scene.markers:
            popup = _popup_html(marker, output_html)
            if marker.kind == "overnight":
                folium.Marker(
                    location=(marker.latitude, marker.longitude),
                    tooltip=marker.label,
                    popup=popup,
                    icon=folium.Icon(color="black", icon="home", prefix="fa"),
                ).add_to(stay_layer)
                continue
            if marker.kind == "place":
                folium.Marker(
                    location=(marker.latitude, marker.longitude),
                    tooltip=marker.label,
                    popup=popup,
                    icon=folium.Icon(color="gray", icon="flag", prefix="fa"),
                ).add_to(place_layer)
                continue
            day_key = marker.day_key or "Ohne Datum"
            cluster = day_clusters.get(day_key)
            if cluster is None:
                cluster = MarkerCluster(name=f"Tag {day_key}")
                day_clusters[day_key] = cluster
            icon_name = "camera" if marker.kind == "photo" else "film"
            folium.Marker(
                location=(marker.latitude, marker.longitude),
                tooltip=marker.label,
                popup=popup,
                icon=folium.Icon(color=marker.color, icon=icon_name, prefix="fa"),
            ).add_to(cluster)

        track_layer.add_to(fmap)
        if has_flights:
            flight_layer.add_to(fmap)
            flight_ends.add_to(fmap)
        for cluster in day_clusters.values():
            cluster.add_to(fmap)
        stay_layer.add_to(fmap)
        place_layer.add_to(fmap)
        folium.LayerControl(collapsed=False).add_to(fmap)
        if has_flights:
            fmap.get_root().html.add_child(
                folium.Element(_zoom_script(fmap, flight_layer, FLIGHT_LINE_MIN_ZOOM))
            )
        if scene.center is None and scene.empty:
            fmap.location = [50.0, 10.0]
        output_html.parent.mkdir(parents=True, exist_ok=True)
        fmap.save(str(output_html))
        return output_html


def _flight_end_markers(line: MapPolyline, group: folium.FeatureGroup) -> None:
    start = line.points[0]
    end = line.points[-1]
    start_popup = _line_popup(line, role="Start")
    end_popup = _line_popup(line, role="Landung")
    folium.Marker(
        location=start,
        tooltip=f"Start: {line.name}",
        popup=start_popup,
        icon=folium.Icon(color="orange", icon="plane", prefix="fa"),
    ).add_to(group)
    folium.Marker(
        location=end,
        tooltip=f"Landung: {line.name}",
        popup=end_popup,
        icon=folium.Icon(color="red", icon="flag", prefix="fa"),
    ).add_to(group)


def _line_popup(line: MapPolyline, *, role: str | None = None) -> folium.Popup:
    title = html.escape(line.name)
    parts = [f"<strong>{title}</strong>"]
    if role:
        parts.append(f"<div>{html.escape(role)}</div>")
    if line.pilot:
        parts.append(f"<div>Pilot: {html.escape(line.pilot)}</div>")
    if line.external_url:
        href = html.escape(line.external_url, quote=True)
        parts.append(f'<div><a href="{href}" target="_blank" rel="noopener">DHV-Leonardo</a></div>')
    body = "<div style='min-width:180px'>" + "".join(parts) + "</div>"
    return folium.Popup(body, max_width=280)


def _zoom_script(fmap: folium.Map, group: folium.FeatureGroup, min_zoom: int) -> str:
    map_name = fmap.get_name()
    group_name = group.get_name()
    return f"""
<script>
(function() {{
  var map = {map_name};
  var flights = {group_name};
  var minZoom = {min_zoom};
  function syncIgc() {{
    var visible = map.getZoom() >= minZoom;
    flights.eachLayer(function(layer) {{
      if (layer.setStyle) {{
        layer.setStyle({{opacity: visible ? 0.9 : 0, weight: visible ? 3.5 : 0}});
      }}
    }});
  }}
  map.on('zoomend', syncIgc);
  map.on('layeradd', syncIgc);
  syncIgc();
}})();
</script>
"""


def _popup_html(marker: MapMarker, html_path: Path) -> folium.Popup:
    title = html.escape(marker.label)
    parts = [f"<strong>{title}</strong>"]
    if marker.subtitle:
        parts.append(f"<div>{html.escape(marker.subtitle)}</div>")
    elif marker.kind in {"photo", "video"}:
        parts.append(f"<div>{html.escape(marker.kind)}</div>")
    href = _thumb_href(html_path, marker.preview_path)
    if href is not None:
        parts.append(f'<img src="{html.escape(href, quote=True)}" width="180" alt="">')
    body = "<div style='min-width:160px'>" + "".join(parts) + "</div>"
    return folium.Popup(body, max_width=240)


def _thumb_href(html_path: Path, preview: Path | None) -> str | None:
    if preview is None or not preview.is_file():
        return None
    try:
        relative = preview.resolve().relative_to(html_path.parent.resolve(), walk_up=True)
    except ValueError:
        return preview.resolve().as_uri()
    return relative.as_posix()
