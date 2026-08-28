"""Folium/Leaflet map renderer. Original media files are never written."""

from __future__ import annotations

import html
from collections.abc import Sequence
from pathlib import Path
from typing import Any, NamedTuple, Protocol, runtime_checkable

import folium
from folium.plugins import MarkerCluster

from travelcore.maps.interaction import (
    _BASEMAP_CSS,
    _COVER_CSS,
    _STACK_CSS,
    _STACK_ICON_JS,
    ESRI_SAT_ATTR,
    ESRI_SAT_TILES,
    OPENTOPO_ATTR,
    OPENTOPO_TILES,
    OSM_LATIN_ATTR,
    OSM_LATIN_TILES,
    PHOTO_STACK_RADIUS_PX,
    _overview_script,
    _popup_body,
    _standalone_basemap_script,
    _standalone_settings_script,
    _thumb_href,
    config_script,
    interaction_config,
)
from travelcore.maps.scene import (
    COVER_ICON_PX,
    FLIGHT_LINE_MIN_ZOOM,
    PHOTO_STACK_DISABLE_ZOOM,
    MapMarker,
    MapPolyline,
    MapScene,
    StayLink,
)
from travelcore.project_settings import DEFAULT_STAY_LINK_COLOR, normalize_stay_link_color


@runtime_checkable
class MapBackend(Protocol):
    """Write an interactive map document for display in a web view."""

    def render(self, scene: MapScene, output_html: Path) -> Path: ...


def _folium_map(*, location: tuple[float, float], zoom: int, tiles: str | None) -> folium.Map:
    kwargs: dict[str, Any] = {
        "location": location,
        "zoom_start": zoom,
        "tiles": tiles,
        "control_scale": True,
        "double_click_zoom": False,
    }
    if tiles is not None and "://" in tiles:
        kwargs["attr"] = OSM_LATIN_ATTR
    return folium.Map(**kwargs)


class FoliumMapBackend:
    """Leaflet via Folium. Remote tiles are optional; vectors are always local."""

    def __init__(
        self,
        *,
        tiles: str | None = OSM_LATIN_TILES,
        link_color: str = DEFAULT_STAY_LINK_COLOR,
    ) -> None:
        self.tiles = tiles
        self.link_color = normalize_stay_link_color(link_color)

    def render(self, scene: MapScene, output_html: Path) -> Path:
        location = scene.center or (50.0, 10.0)
        zoom = 6 if scene.center is not None else 4
        fmap = _folium_map(location=location, zoom=zoom, tiles=self.tiles)
        covers = [marker for marker in scene.markers if marker.kind == "cover"]
        if covers:
            output_html.parent.mkdir(parents=True, exist_ok=True)
            fmap.get_root().header.add_child(folium.Element(_COVER_CSS))
            cover_layer = folium.FeatureGroup(name="Titelbilder", show=True)
            for marker in covers:
                folium.Marker(
                    location=(marker.latitude, marker.longitude),
                    tooltip=marker.label,
                    icon=_cover_icon(marker, output_html),
                    bubblingMouseEvents=False,
                    interactive=True,
                    group_key=marker.group_key or "",
                ).add_to(cover_layer)
            link_layer = _stay_link_layer(scene.stay_links, color=self.link_color)
            if link_layer is not None:
                link_layer.add_to(fmap)
            cover_layer.add_to(fmap)
            extra = _add_extra_basemaps(fmap) if self.tiles else None
            _photo_stack_cluster(control=False, show=False).add_to(fmap)
            bounds = _latlng_bounds(covers)
            if bounds is not None:
                fmap.fit_bounds(bounds, padding=(56, 56), max_zoom=13)
            fmap.get_root().html.add_child(
                folium.Element(
                    config_script(interaction_config(scene, output_html, link_color=self.link_color))
                )
            )
            fmap.get_root().html.add_child(
                folium.Element(
                    _overview_script(
                        fmap,
                        cover_layer,
                        scene.stay_links,
                        link_layer,
                        extra=extra,
                        color=self.link_color,
                    )
                )
            )
            output_html.parent.mkdir(parents=True, exist_ok=True)
            fmap.save(str(output_html))
            return output_html

        track_layer = folium.FeatureGroup(name="Tracks", show=True)
        flight_layer = folium.FeatureGroup(name="Flugtracks (IGC)", show=True)
        flight_ends = folium.FeatureGroup(name="Start / Landung", show=True)
        place_layer = folium.FeatureGroup(name="Orte", show=True)
        media_cluster: MarkerCluster | None = None
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
            if marker.kind == "place":
                folium.Marker(
                    location=(marker.latitude, marker.longitude),
                    tooltip=marker.label,
                    popup=popup,
                    icon=folium.Icon(color="gray", icon="flag", prefix="fa"),
                ).add_to(place_layer)
                continue
            if media_cluster is None:
                media_cluster = _photo_stack_cluster()
            icon_name = "camera" if marker.kind == "photo" else "film"
            folium.Marker(
                location=(marker.latitude, marker.longitude),
                tooltip=marker.label,
                popup=popup,
                icon=folium.Icon(color=marker.color, icon=icon_name, prefix="fa"),
            ).add_to(media_cluster)

        track_layer.add_to(fmap)
        if has_flights:
            flight_layer.add_to(fmap)
            flight_ends.add_to(fmap)
        if media_cluster is not None:
            media_cluster.add_to(fmap)
        place_layer.add_to(fmap)
        extra = _add_extra_basemaps(fmap) if self.tiles else None
        folium.LayerControl(collapsed=False).add_to(fmap)
        fmap.get_root().header.add_child(folium.Element(_STACK_CSS))
        fmap.get_root().header.add_child(folium.Element(_BASEMAP_CSS))
        fmap.get_root().html.add_child(
            folium.Element(config_script(interaction_config(scene, output_html, link_color=self.link_color)))
        )
        if has_flights:
            fmap.get_root().html.add_child(
                folium.Element(_zoom_script(fmap, flight_layer, FLIGHT_LINE_MIN_ZOOM))
            )
        if extra is not None:
            fmap.get_root().html.add_child(folium.Element(_standalone_basemap_script(fmap, extra)))
        else:
            fmap.get_root().html.add_child(folium.Element(_standalone_settings_script(fmap)))
        if scene.center is None and scene.empty:
            fmap.location = [50.0, 10.0]
        output_html.parent.mkdir(parents=True, exist_ok=True)
        fmap.save(str(output_html))
        return output_html


class ExtraBasemaps(NamedTuple):
    satellite: folium.TileLayer
    topo: folium.TileLayer


def _photo_stack_cluster(*, control: bool = True, show: bool = True) -> MarkerCluster:
    """One cluster for nearby photo/video/track markers until zoom 17."""

    return MarkerCluster(
        name="Fotos" if control else None,
        overlay=True,
        control=control,
        show=show,
        icon_create_function=_STACK_ICON_JS,
        options={
            "disableClusteringAtZoom": PHOTO_STACK_DISABLE_ZOOM,
            "spiderfyOnMaxZoom": False,
            "maxClusterRadius": PHOTO_STACK_RADIUS_PX,
            "showCoverageOnHover": False,
        },
    )


def _tile_layer(
    tiles: str,
    *,
    attr: str,
    name: str,
    max_zoom: int,
    subdomains: str | None = None,
) -> folium.TileLayer:
    kwargs: dict[str, Any] = {
        "tiles": tiles,
        "attr": attr,
        "name": name,
        "overlay": False,
        "control": False,
        "show": False,
        "max_zoom": max_zoom,
    }
    if subdomains is not None:
        kwargs["subdomains"] = subdomains
    return folium.TileLayer(**kwargs)


def _add_extra_basemaps(fmap: folium.Map) -> ExtraBasemaps:
    """OpenTopoMap and Esri World Imagery. Hidden until the user picks them."""

    satellite = _tile_layer(ESRI_SAT_TILES, attr=ESRI_SAT_ATTR, name="Satellit", max_zoom=19)
    topo = _tile_layer(
        OPENTOPO_TILES,
        attr=OPENTOPO_ATTR,
        name="Topo",
        max_zoom=17,
        subdomains="abc",
    )
    satellite.add_to(fmap)
    topo.add_to(fmap)
    return ExtraBasemaps(satellite=satellite, topo=topo)


def _latlng_bounds(markers: list[MapMarker]) -> list[list[float]] | None:
    if not markers:
        return None
    lats = [item.latitude for item in markers]
    lons = [item.longitude for item in markers]
    return [[min(lats), min(lons)], [max(lats), max(lons)]]


def _cover_icon(marker: MapMarker, html_path: Path) -> folium.DivIcon:
    thumb = _thumb_href(html_path, marker.preview_path)
    key = html.escape(marker.group_key or "", quote=True)
    if thumb is not None:
        inner = f'<img src="{html.escape(thumb, quote=True)}" alt="">'
    else:
        inner = '<span style="font-size:20px;line-height:47px">&#128247;</span>'
    body = f'<div class="tj-cover" data-group-key="{key}">{inner}</div>'
    half = COVER_ICON_PX // 2
    return folium.DivIcon(
        html=body,
        icon_size=(COVER_ICON_PX, COVER_ICON_PX),
        icon_anchor=(half, half),
        class_name="tj-cover-icon",
    )


def _stay_link_layer(links: Sequence[StayLink], *, color: str) -> folium.FeatureGroup | None:
    """Real overlay polylines so connections are visible without extra JS panes."""

    if not links:
        return None
    group = folium.FeatureGroup(name="Aufenthaltslinien", show=True)
    for link in links:
        folium.PolyLine(
            locations=[list(link.start), list(link.end)],
            color=color,
            weight=3.5,
            opacity=1.0,
            interactive=False,
            className="tj-stay-link",
            lineCap="butt",
        ).add_to(group)
    return group


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
    return folium.Popup(_popup_body(marker, html_path), max_width=240)
