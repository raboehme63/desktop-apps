"""Folium/Leaflet map renderer. Original media files are never written."""

from __future__ import annotations

import html
from pathlib import Path
from typing import Protocol, runtime_checkable

import folium
from folium.plugins import MarkerCluster

from travelcore.maps.scene import MapMarker, MapScene

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
        stay_layer = folium.FeatureGroup(name="Übernachtungen", show=True)
        place_layer = folium.FeatureGroup(name="Orte", show=True)
        day_clusters: dict[str, MarkerCluster] = {}

        for line in scene.polylines:
            folium.PolyLine(
                locations=list(line.points),
                color="#2eb8a0",
                weight=3,
                opacity=0.85,
                tooltip=line.name,
            ).add_to(track_layer)

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
        for cluster in day_clusters.values():
            cluster.add_to(fmap)
        stay_layer.add_to(fmap)
        place_layer.add_to(fmap)
        folium.LayerControl(collapsed=False).add_to(fmap)
        if scene.center is None and scene.empty:
            fmap.location = [50.0, 10.0]
        output_html.parent.mkdir(parents=True, exist_ok=True)
        fmap.save(str(output_html))
        return output_html


def _popup_html(marker: MapMarker, html_path: Path) -> folium.Popup:
    title = html.escape(marker.label)
    parts = [f"<strong>{title}</strong>"]
    if marker.kind == "photo" or marker.kind == "video":
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
