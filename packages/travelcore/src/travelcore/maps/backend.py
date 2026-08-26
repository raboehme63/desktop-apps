"""Folium/Leaflet map renderer. Original media files are never written."""

from __future__ import annotations

import html
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

import folium
from folium.plugins import MarkerCluster

from travelcore.maps.groups import MapTimelineCard
from travelcore.maps.scene import FLIGHT_LINE_MIN_ZOOM, MapMarker, MapPolyline, MapScene

OSM_LATIN_TILES = "https://tile.openstreetmap.de/{z}/{x}/{y}.png"
OSM_LATIN_ATTR = (
    '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>-Mitwirkende'
)


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

    def __init__(self, *, tiles: str | None = OSM_LATIN_TILES) -> None:
        self.tiles = tiles

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
            cover_layer.add_to(fmap)
            bounds = _latlng_bounds(covers)
            if bounds is not None:
                fmap.fit_bounds(bounds, padding=(56, 56), max_zoom=13)
            fmap.get_root().html.add_child(folium.Element(_overview_script(fmap, cover_layer)))
            output_html.parent.mkdir(parents=True, exist_ok=True)
            fmap.save(str(output_html))
            return output_html

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


def _latlng_bounds(markers: list[MapMarker]) -> list[list[float]] | None:
    if not markers:
        return None
    lats = [item.latitude for item in markers]
    lons = [item.longitude for item in markers]
    return [[min(lats), min(lons)], [max(lats), max(lons)]]


def leaflet_payload(scene: MapScene, html_path: Path) -> dict[str, Any]:
    """JSON for ``traveljournalShowDetail`` in the overview HTML."""

    markers = [
        {
            "latitude": marker.latitude,
            "longitude": marker.longitude,
            "kind": marker.kind,
            "label": marker.label,
            "popup_html": _popup_body(marker, html_path),
            "preview": _thumb_href(html_path, marker.preview_path) or "",
            "source_file_id": marker.source_file_id,
        }
        for marker in scene.markers
    ]
    lines = [
        {
            "points": [list(point) for point in line.points],
            "color": line.color,
            "kind": line.kind,
            "name": line.name,
            "weight": 3.5 if line.kind == "flight" else 3,
            "external_url": line.external_url or "",
            "pilot": line.pilot or "",
        }
        for line in scene.polylines
    ]
    return {"markers": markers, "polylines": lines}


def timeline_js_cards(
    cards: Sequence[MapTimelineCard],
    html_path: Path,
) -> list[dict[str, Any]]:
    """JSON for ``traveljournalSetTimeline`` in the overview HTML."""

    return [
        {
            "key": card.group_key,
            "title": card.title,
            "time_label": card.time_label,
            "cover": _thumb_href(html_path, card.cover_path) or "",
            "lat": card.latitude,
            "lon": card.longitude,
        }
        for card in cards
    ]


_COVER_CSS = """
<style>
.tj-cover-icon {
  background: rgba(0, 0, 0, 0.01) !important;
  border: none !important;
  pointer-events: auto !important;
}
.tj-cover {
  width: 47px;
  height: 47px;
  border-radius: 50%;
  overflow: hidden;
  border: 3px solid #fff;
  box-shadow: 0 1px 4px rgba(0,0,0,.45);
  background: #222;
  cursor: pointer;
  text-align: center;
  color: #fff;
  pointer-events: auto;
}
.tj-cover.tj-focused {
  box-shadow: 0 0 0 3px #2eb8a0, 0 1px 4px rgba(0,0,0,.45);
}
.tj-thumb {
  width: 48px;
  height: 48px;
  border-radius: 0;
  overflow: hidden;
  border: 2px solid #fff;
  box-shadow: 0 1px 4px rgba(0,0,0,.45);
  background: #222;
  cursor: pointer;
}
.tj-cover img, .tj-thumb img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
  pointer-events: none;
}
.leaflet-marker-icon.tj-cover-icon {
  z-index: 700 !important;
  pointer-events: auto !important;
}
.leaflet-interactive.tj-cover-icon {
  pointer-events: auto !important;
}
.tj-popup-thumb {
  display: block;
  margin-top: 6px;
  cursor: pointer;
  pointer-events: auto;
}
</style>
"""


def _cover_icon(marker: MapMarker, html_path: Path) -> folium.DivIcon:
    thumb = _thumb_href(html_path, marker.preview_path)
    key = html.escape(marker.group_key or "", quote=True)
    if thumb is not None:
        inner = f'<img src="{html.escape(thumb, quote=True)}" alt="">'
    else:
        inner = '<span style="font-size:20px;line-height:47px">&#128247;</span>'
    body = f'<div class="tj-cover" data-group-key="{key}">{inner}</div>'
    return folium.DivIcon(
        html=body,
        icon_size=(54, 54),
        icon_anchor=(27, 27),
        class_name="tj-cover-icon",
    )



def _overview_script(fmap: folium.Map, covers: folium.FeatureGroup) -> str:
    map_name = fmap.get_name()
    cover_name = covers.get_name()
    return f"""
<script>
(function() {{
    function boot() {{
    if (window.traveljournalShowDetail) {{
      return;
    }}
    var map = {map_name};
    var covers = {cover_name};
    if (!map || !covers) {{
      return;
    }}
    var detail = L.layerGroup().addTo(map);
    var savedView = null;
    var closeCtl = null;
    function setCloseVisible(show) {{
      var el = closeCtl && closeCtl.getContainer && closeCtl.getContainer();
      if (el) {{
        el.style.display = show ? '' : 'none';
      }}
    }}
    function layerKey(layer) {{
      var opts = (layer && layer.options) || {{}};
      var fromOpts = opts.group_key || opts.groupKey || '';
      if (fromOpts) {{
        return fromOpts;
      }}
      var el = (layer.getElement && layer.getElement()) || layer._icon;
      var node = el && el.querySelector
        ? el.querySelector('[data-group-key]')
        : null;
      return (node && node.getAttribute('data-group-key')) || '';
    }}
    function enableDrag() {{
      if (map.dragging) {{
        map.dragging.enable();
      }}
    }}
    window.traveljournalExpand = function(key) {{
      if (!key) {{
        return;
      }}
      enableDrag();
      if (window.tjBridge && window.tjBridge.expand) {{
        window.tjBridge.expand(key);
      }}
      console.warn('traveljournal:expand:' + key);
    }};
    window.traveljournalOpenMedia = function(sourceId) {{
      var id = parseInt(sourceId, 10);
      if (!id) {{
        return;
      }}
      if (window.tjBridge && window.tjBridge.openMedia) {{
        window.tjBridge.openMedia(id);
        return;
      }}
      console.info('traveljournal:media:' + id);
    }};
    window.traveljournalCloseSection = function() {{
      enableDrag();
      detail.clearLayers();
      if (!map.hasLayer(covers)) {{
        map.addLayer(covers);
      }}
      if (savedView) {{
        map.setView(savedView.center, savedView.zoom);
        savedView = null;
      }}
      setCloseVisible(false);
      if (window.tjBridge && window.tjBridge.sectionClosed) {{
        window.tjBridge.sectionClosed();
      }}
    }};
    window.traveljournalFocusCover = function(lat, lon, key, offsetY) {{
      window.traveljournalKeepFocus = true;
      if (savedView) {{
        detail.clearLayers();
        if (!map.hasLayer(covers)) {{
          map.addLayer(covers);
        }}
        savedView = null;
        setCloseVisible(false);
        if (window.tjBridge && window.tjBridge.sectionClosed) {{
          window.tjBridge.sectionClosed();
        }}
      }}
      if (typeof lat !== 'number' || typeof lon !== 'number') {{
        return;
      }}
      try {{
        var zoom = map.getZoom();
        var target = L.latLng(lat, lon);
        var dy = typeof offsetY === 'number' ? offsetY : 0;
        if (dy) {{
          var point = map.project(target, zoom);
          point.y += dy;
          target = map.unproject(point, zoom);
        }}
        if (map.stop) {{
          map.stop();
        }}
        map.setView(target, zoom, {{
          animate: true,
          pan: {{animate: true}},
          zoom: {{animate: false}}
        }});
        covers.eachLayer(function(layer) {{
          var el = (layer.getElement && layer.getElement()) || layer._icon;
          var node = el && el.querySelector ? el.querySelector('.tj-cover') : null;
          if (!node || !node.classList) {{
            return;
          }}
          var on = key && node.getAttribute('data-group-key') === key;
          node.classList.toggle('tj-focused', on);
        }});
      }} catch (err) {{}}
    }};
    window.traveljournalShowDetail = function(payload) {{
      enableDrag();
      savedView = {{center: map.getCenter(), zoom: map.getZoom()}};
      if (map.hasLayer(covers)) {{
        map.removeLayer(covers);
      }}
      detail.clearLayers();
      (payload.markers || []).forEach(function(item) {{
        var latlng = [item.latitude, item.longitude];
        var marker;
        if (item.preview) {{
          marker = L.marker(latlng, {{
            icon: L.divIcon({{
              className: 'tj-cover-icon',
              iconSize: [52, 52],
              iconAnchor: [26, 26],
              html: '<div class="tj-thumb"><img src="' +
                String(item.preview).replace(/"/g, '&quot;') + '" alt=""></div>'
            }})
          }});
        }} else {{
          var color = '#2a7ade';
          if (item.kind === 'overnight') {{
            color = '#111';
          }} else if (item.kind === 'place') {{
            color = '#777';
          }}
          marker = L.circleMarker(latlng, {{
            radius: 8,
            color: color,
            fillColor: color,
            fillOpacity: 0.9
          }});
        }}
        if (item.label) {{
          marker.bindTooltip(item.label);
        }}
        if (item.popup_html) {{
          marker.bindPopup(item.popup_html, {{maxWidth: 260}});
        }}
        if (item.source_file_id) {{
          marker.on('dblclick', function(event) {{
            L.DomEvent.stop(event);
            window.traveljournalOpenMedia(item.source_file_id);
          }});
        }}
        marker.addTo(detail);
      }});
      (payload.polylines || []).forEach(function(line) {{
        var layer = L.polyline(line.points, {{
          color: line.color || '#2eb8a0',
          weight: line.weight || 3,
          opacity: 0.9
        }});
        if (line.name) {{
          layer.bindTooltip(line.name);
        }}
        var parts = ['<div style="min-width:180px">'];
        if (line.name) {{
          parts.push('<strong>' + String(line.name).replace(/</g, '') + '</strong>');
        }}
        if (line.pilot) {{
          parts.push('<div>Pilot: ' + String(line.pilot).replace(/</g, '') + '</div>');
        }}
        if (line.external_url) {{
          parts.push(
            '<div><a href="' + String(line.external_url).replace(/"/g, '&quot;') +
            '" target="_blank" rel="noopener">DHV-Leonardo</a></div>'
          );
        }}
        parts.push('</div>');
        if (parts.length > 2) {{
          layer.bindPopup(parts.join(''));
        }}
        layer.addTo(detail);
      }});
      setCloseVisible(true);
      try {{
        var bounds = L.featureGroup(detail.getLayers()).getBounds();
        if (bounds && bounds.isValid()) {{
          var pad = window.traveljournalOverlayPad || 0;
          map.fitBounds(bounds, {{
            paddingTopLeft: [32, 32],
            paddingBottomRight: [32, 32 + pad],
            maxZoom: 15
          }});
        }}
      }} catch (err) {{}}
    }};
    closeCtl = L.control({{position: 'topleft'}});
    closeCtl.onAdd = function() {{
      var box = L.DomUtil.create('div', 'leaflet-bar');
      var link = L.DomUtil.create('a', '', box);
      link.href = '#';
      link.title = 'Reiseabschnitt schließen';
      link.innerHTML = 'Reiseabschnitt schließen';
      link.style.width = 'auto';
      link.style.padding = '0 8px';
      link.style.lineHeight = '26px';
      L.DomEvent.on(link, 'click', function(event) {{
        L.DomEvent.stop(event);
        window.traveljournalCloseSection();
        if (window.tjBridge && window.tjBridge.sectionClosed) {{
          window.tjBridge.sectionClosed();
        }}
      }});
      box.style.display = 'none';
      return box;
    }};
    closeCtl.addTo(map);
    function fitOverview() {{
      if (window.traveljournalKeepFocus) {{
        return;
      }}
      try {{
        map.invalidateSize();
        var bounds = covers.getBounds && covers.getBounds();
        if (bounds && bounds.isValid()) {{
          var pad = window.traveljournalOverlayPad || 0;
          map.fitBounds(bounds, {{
            paddingTopLeft: [56, 56],
            paddingBottomRight: [56, 56 + pad],
            maxZoom: 13
          }});
        }}
      }} catch (err) {{}}
    }}
    window.traveljournalFitOverview = function() {{
      window.traveljournalKeepFocus = false;
      if (savedView) {{
        detail.clearLayers();
        if (!map.hasLayer(covers)) {{
          map.addLayer(covers);
        }}
        savedView = null;
        setCloseVisible(false);
        if (window.tjBridge && window.tjBridge.sectionClosed) {{
          window.tjBridge.sectionClosed();
        }}
      }}
      fitOverview();
    }};
    if (map.doubleClickZoom) {{
      map.doubleClickZoom.disable();
    }}
    map.on('zoomstart', function(event) {{
      if (event && event.originalEvent) {{
        window.traveljournalKeepFocus = true;
      }}
    }});
    map.on('popupopen', function(event) {{
      var root = event.popup && event.popup.getElement && event.popup.getElement();
      var img = root && root.querySelector
        ? root.querySelector('.tj-popup-thumb[data-source-id]')
        : null;
      if (!img || img._tjBound) {{
        return;
      }}
      img._tjBound = true;
      L.DomEvent.on(img, 'dblclick', function(ev) {{
        L.DomEvent.stop(ev);
        window.traveljournalOpenMedia(img.getAttribute('data-source-id'));
      }});
    }});
    map.on('dblclick', function(event) {{
      var target = event.originalEvent && event.originalEvent.target;
      if (target && target.closest && target.closest(
        '.tj-cover, .tj-cover-icon, .tj-thumb, .tj-popup-thumb, .leaflet-popup'
      )) {{
        L.DomEvent.stop(event);
        return;
      }}
      L.DomEvent.stop(event);
      window.traveljournalFitOverview();
    }});
    function bindCover(layer) {{
      if (layer._tjBound) {{
        return;
      }}
      layer._tjBound = true;
      function openCover(event) {{
        L.DomEvent.stop(event);
        var key = layerKey(layer);
        if (key) {{
          window.traveljournalExpand(key);
        }}
      }}
      layer.on('click', openCover);
      layer.on('dblclick', function(event) {{
        L.DomEvent.stop(event);
      }});
      layer.on('mouseover', function() {{
        if (map.dragging) {{
          map.dragging.disable();
        }}
      }});
      layer.on('mouseout', function() {{
        enableDrag();
      }});
      function bindIcon() {{
        var el = (layer.getElement && layer.getElement()) || layer._icon;
        if (!el || el._tjBound) {{
          return;
        }}
        el._tjBound = true;
        el.style.cursor = 'pointer';
        L.DomEvent.on(el, 'click', openCover);
        L.DomEvent.on(el, 'pointerup', openCover);
      }}
      bindIcon();
      layer.on('add', bindIcon);
    }}
    covers.eachLayer(bindCover);
    function coverNodeFromEvent(event) {{
      var target = event.originalEvent ? event.originalEvent.target : event.target;
      if (!target || !target.closest) {{
        return null;
      }}
      var node = target.closest('.tj-cover[data-group-key]');
      if (node) {{
        return node;
      }}
      var icon = target.closest('.tj-cover-icon');
      return icon ? icon.querySelector('[data-group-key]') : null;
    }}
    var mapEl = map.getContainer && map.getContainer();
    if (mapEl && mapEl.addEventListener) {{
      mapEl.addEventListener('pointerup', function(event) {{
        var node = coverNodeFromEvent(event);
        if (!node) {{
          return;
        }}
        event.preventDefault();
        event.stopPropagation();
        window.traveljournalExpand(node.getAttribute('data-group-key'));
      }}, true);
      mapEl.addEventListener('click', function(event) {{
        var node = coverNodeFromEvent(event);
        if (!node) {{
          return;
        }}
        event.stopPropagation();
        window.traveljournalExpand(node.getAttribute('data-group-key'));
      }}, true);
    }}
    map.on('click', function(event) {{
      if (!map.hasLayer || !map.hasLayer(covers)) {{
        return;
      }}
      var orig = event.originalEvent && event.originalEvent.target;
      if (orig && orig.closest && orig.closest('.tj-timeline, .leaflet-control')) {{
        return;
      }}
      var clickPt = map.latLngToContainerPoint(event.latlng);
      var bestKey = '';
      var bestDist = 48;
      covers.eachLayer(function(layer) {{
        var latlng = layer.getLatLng && layer.getLatLng();
        if (!latlng) {{
          return;
        }}
        var dist = clickPt.distanceTo(map.latLngToContainerPoint(latlng));
        if (dist > bestDist) {{
          return;
        }}
        var key = layerKey(layer);
        if (key) {{
          bestDist = dist;
          bestKey = key;
        }}
      }});
      if (bestKey) {{
        L.DomEvent.stop(event);
        window.traveljournalExpand(bestKey);
      }}
    }});
    fitOverview();
    setTimeout(fitOverview, 150);
  }}
  function wait(tries) {{
    try {{
      if (typeof {map_name} !== 'undefined' && typeof {cover_name} !== 'undefined'
          && {cover_name}.getLayers && {cover_name}.getLayers().length) {{
        boot();
        return;
      }}
    }} catch (err) {{}}
    if (tries > 0) {{
      setTimeout(function() {{ wait(tries - 1); }}, 50);
    }}
  }}
  wait(120);
}})();
</script>
"""


def _popup_body(marker: MapMarker, html_path: Path) -> str:
    title = html.escape(marker.label)
    parts = [f"<strong>{title}</strong>"]
    if marker.subtitle:
        parts.append(f"<div>{html.escape(marker.subtitle)}</div>")
    elif marker.kind in {"photo", "video"}:
        parts.append(f"<div>{html.escape(marker.kind)}</div>")
    href = _thumb_href(html_path, marker.preview_path)
    if href is not None:
        sid = ""
        if marker.source_file_id:
            sid = f' data-source-id="{int(marker.source_file_id)}"'
        parts.append(
            f'<img class="tj-popup-thumb" src="{html.escape(href, quote=True)}" '
            f'width="180" alt=""{sid}>'
        )
    return "<div style='min-width:160px'>" + "".join(parts) + "</div>"


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


def _thumb_href(html_path: Path, preview: Path | None) -> str | None:
    if preview is None or not preview.is_file():
        return None
    try:
        relative = preview.resolve().relative_to(html_path.parent.resolve(), walk_up=True)
    except ValueError:
        return preview.resolve().as_uri()
    return relative.as_posix()
