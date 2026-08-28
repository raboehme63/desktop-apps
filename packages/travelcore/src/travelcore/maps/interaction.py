"""Leaflet interaction: JSON payload, CSS and boot scripts.

Folium (or another host) only creates the map and injects this module.
SQLite and original media files are never written here.
"""

from __future__ import annotations

import html
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from travelcore.maps.groups import MapTimelineCard
from travelcore.maps.scene import (
    COVER_ICON_PX,
    COVER_LINE_INSET_PX,
    DEFAULT_PHOTO_FOV_DEGREES,
    PHOTO_CONE_MIN_ZOOM,
    PHOTO_STACK_DISABLE_ZOOM,
    MapMarker,
    MapScene,
    StayLink,
)
from travelcore.project_settings import DEFAULT_STAY_LINK_COLOR, normalize_stay_link_color

OSM_LATIN_TILES = "https://tile.openstreetmap.de/{z}/{x}/{y}.png"
OSM_LATIN_ATTR = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>-Mitwirkende'
OPENTOPO_TILES = "https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png"
OPENTOPO_ATTR = (
    'Kartendaten &copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>-Mitwirkende, '
    '<a href="https://viewfinderpanoramas.org">SRTM</a> | Darstellung &copy; '
    '<a href="https://opentopomap.org">OpenTopoMap</a> '
    '(<a href="https://creativecommons.org/licenses/by-sa/3.0/">CC-BY-SA</a>)'
)
ESRI_SAT_TILES = (
    "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
)
ESRI_SAT_ATTR = "Kacheln &copy; Esri &mdash; Esri, Maxar, Earthstar Geographics, GIS User Community"

_RATE_CHIPS = (
    ("favorite", "★", "Favorit"),
    ("reserve", "R", "Reserve"),
    ("rejected", "×", "Aussortiert"),
)

_LAYERS_ICON_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" '
    'fill="none" stroke="#333" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" '
    'aria-hidden="true">'
    '<polygon points="12 2 2 7 12 12 22 7 12 2"/>'
    '<polyline points="2 12 12 17 22 12"/>'
    '<polyline points="2 17 12 22 22 17"/>'
    "</svg>"
)


_GEAR_ICON_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" '
    'fill="none" stroke="#333" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" '
    'aria-hidden="true">'
    '<circle cx="12" cy="12" r="11"/>'
    '<circle cx="12" cy="12" r="2.15"/>'
    '<path d="M11.03 6.94 10.66 4.98 13.34 4.98 12.97 6.94 14.89 7.74 16.02 6.09 17.91 7.98 '
    "16.26 9.11 17.06 11.03 19.02 10.66 19.02 13.34 17.06 12.97 16.26 14.89 17.91 16.02 "
    "16.02 17.91 14.89 16.26 12.97 17.06 13.34 19.02 10.66 19.02 11.03 17.06 9.11 16.26 "
    "7.98 17.91 6.09 16.02 7.74 14.89 6.94 12.97 4.98 13.34 4.98 10.66 6.94 11.03 7.74 9.11 "
    '6.09 7.98 7.98 6.09 9.11 7.74Z"/>'
    "</svg>"
)


PHOTO_STACK_RADIUS_PX = 48


PHOTO_OVERLAP_PX = 40


PHOTO_ROTATE_MS = 1400


_STACK_ICON_JS = """
function (cluster) {
  var n = cluster.getChildCount();
  return L.divIcon({
    html: '<div class="tj-stack"><span>' + n + '</span></div>',
    className: 'tj-stack-icon',
    iconSize: L.point(36, 36)
  });
}
"""


def _photo_cluster_js() -> str:
    return f"""
    function photoClusterGroup() {{
      if (typeof L.markerClusterGroup !== 'function') {{
        return null;
      }}
      return L.markerClusterGroup({{
        disableClusteringAtZoom: {PHOTO_STACK_DISABLE_ZOOM},
        spiderfyOnMaxZoom: false,
        maxClusterRadius: {PHOTO_STACK_RADIUS_PX},
        showCoverageOnHover: false,
        iconCreateFunction: function(cluster) {{
          var n = cluster.getChildCount();
          return L.divIcon({{
            html: '<div class="tj-stack"><span>' + n + '</span></div>',
            className: 'tj-stack-icon',
            iconSize: L.point(36, 36)
          }});
        }}
      }});
    }}
"""


def _basemap_toggle_js() -> str:
    """Uses ``map``, ``satLayer`` and ``topoLayer`` from the enclosing script."""

    icon = json.dumps(_LAYERS_ICON_SVG, ensure_ascii=True)
    osm_url = json.dumps(OSM_LATIN_TILES, ensure_ascii=True)
    osm_attr = json.dumps(OSM_LATIN_ATTR, ensure_ascii=True)
    sat_url = json.dumps(ESRI_SAT_TILES, ensure_ascii=True)
    sat_attr = json.dumps(ESRI_SAT_ATTR, ensure_ascii=True)
    topo_url = json.dumps(OPENTOPO_TILES, ensure_ascii=True)
    topo_attr = json.dumps(OPENTOPO_ATTR, ensure_ascii=True)
    return f"""
    function installBasemapToggle() {{
      if (window.traveljournalSetBasemap) {{
        return;
      }}
      var osmLayer = null;
      map.eachLayer(function(layer) {{
        if (layer instanceof L.TileLayer && layer !== satLayer && layer !== topoLayer && !osmLayer) {{
          osmLayer = layer;
        }}
      }});
      if (!osmLayer) {{
        osmLayer = L.tileLayer({osm_url}, {{attribution: {osm_attr}}});
      }}
      if (!satLayer || !satLayer._url) {{
        satLayer = L.tileLayer({sat_url}, {{attribution: {sat_attr}, maxZoom: 19}});
      }}
      if (!topoLayer || !topoLayer._url) {{
        topoLayer = L.tileLayer({topo_url}, {{
          attribution: {topo_attr},
          maxZoom: 17,
          subdomains: 'abc'
        }});
      }}
      var choices = {{karte: osmLayer, topo: topoLayer, satellit: satLayer}};
      var labels = {{karte: 'Straßenkarte', topo: 'Topo', satellit: 'Satellit'}};
      var menuLinks = {{}};
      function applyBasemap(kind) {{
        if (!choices[kind]) {{
          kind = 'karte';
        }}
        var wanted = choices[kind];
        Object.keys(choices).forEach(function(key) {{
          var layer = choices[key];
          if (layer === wanted) {{
            if (!map.hasLayer(layer)) {{
              layer.addTo(map);
            }}
          }} else if (map.hasLayer(layer)) {{
            map.removeLayer(layer);
          }}
        }});
        Object.keys(menuLinks).forEach(function(key) {{
          L.DomUtil[key === kind ? 'addClass' : 'removeClass'](menuLinks[key], 'tj-basemap-on');
        }});
        try {{
          window.localStorage.setItem('traveljournal-basemap', kind);
        }} catch (err) {{}}
      }}
      window.traveljournalSetBasemap = applyBasemap;
      var ctl = L.control({{position: 'topright'}});
      ctl.onAdd = function() {{
        var box = L.DomUtil.create('div', 'leaflet-bar tj-basemap');
        var btn = L.DomUtil.create('a', 'tj-basemap-btn', box);
        btn.href = '#';
        btn.title = 'Kartentyp';
        btn.setAttribute('aria-label', 'Kartentyp');
        btn.innerHTML = {icon};
        var menu = L.DomUtil.create('div', 'tj-basemap-menu', box);
        ['karte', 'topo', 'satellit'].forEach(function(kind) {{
          var link = L.DomUtil.create('a', '', menu);
          link.href = '#';
          link.title = labels[kind];
          link.innerHTML = labels[kind];
          menuLinks[kind] = link;
          L.DomEvent.on(link, 'click', function(event) {{
            L.DomEvent.stop(event);
            applyBasemap(kind);
            L.DomUtil.removeClass(box, 'tj-basemap-open');
          }});
        }});
        L.DomEvent.disableClickPropagation(box);
        L.DomEvent.on(btn, 'click', function(event) {{
          L.DomEvent.stop(event);
          if (L.DomUtil.hasClass(box, 'tj-basemap-open')) {{
            L.DomUtil.removeClass(box, 'tj-basemap-open');
          }} else {{
            L.DomUtil.addClass(box, 'tj-basemap-open');
          }}
        }});
        return box;
      }};
      ctl.addTo(map);
      L.DomEvent.on(document, 'click', function() {{
        var el = ctl.getContainer && ctl.getContainer();
        if (el) {{
          L.DomUtil.removeClass(el, 'tj-basemap-open');
        }}
      }});
      var saved = '';
      try {{
        saved = window.localStorage.getItem('traveljournal-basemap') || '';
      }} catch (err) {{}}
      applyBasemap(saved === 'satellit' || saved === 'topo' ? saved : 'karte');
    }}
    """


def _map_settings_js() -> str:
    """Uses ``map`` from the enclosing script. Optional ``traveljournalApplyMapSettings``."""

    icon = json.dumps(_GEAR_ICON_SVG, ensure_ascii=True)
    return f"""
    window.traveljournalMapFlags = window.traveljournalMapFlags || {{cones: false, reserve: false}};
    function readMapFlag(key) {{
      var flags = window.traveljournalMapFlags || {{}};
      if (key === 'traveljournal-photo-cones') {{
        return !!flags.cones;
      }}
      if (key === 'traveljournal-show-reserve') {{
        return !!flags.reserve;
      }}
      return false;
    }}
    function writeMapFlag(key, on) {{
      window.traveljournalMapFlags = window.traveljournalMapFlags || {{cones: false, reserve: false}};
      if (key === 'traveljournal-photo-cones') {{
        window.traveljournalMapFlags.cones = !!on;
      }} else if (key === 'traveljournal-show-reserve') {{
        window.traveljournalMapFlags.reserve = !!on;
      }}
    }}
    function persistMapFlags() {{
      var flags = window.traveljournalMapFlags || {{}};
      if (window.tjBridge && window.tjBridge.saveMapSettings) {{
        window.tjBridge.saveMapSettings(!!flags.cones, !!flags.reserve);
      }}
    }}
    window.traveljournalShowPhotoCones = function() {{
      return readMapFlag('traveljournal-photo-cones');
    }};
    window.traveljournalShowReserve = function() {{
      return readMapFlag('traveljournal-show-reserve');
    }};
    window.traveljournalApplyStoredMapFlags = function(cones, reserve) {{
      window.traveljournalMapFlags = {{cones: !!cones, reserve: !!reserve}};
      var conesBox = document.getElementById('tj-opt-cones');
      var reserveBox = document.getElementById('tj-opt-reserve');
      if (conesBox) {{
        conesBox.checked = !!cones;
      }}
      if (reserveBox) {{
        reserveBox.checked = !!reserve;
      }}
      if (window.traveljournalApplyMapSettings) {{
        window.traveljournalApplyMapSettings();
      }}
    }};
    function installMapSettings() {{
      if (window.traveljournalMapSettingsReady) {{
        return;
      }}
      window.traveljournalMapSettingsReady = true;
      var ctl = L.control({{position: 'topleft'}});
      ctl.onAdd = function() {{
        var box = L.DomUtil.create('div', 'leaflet-bar tj-settings');
        var btn = L.DomUtil.create('a', 'tj-settings-btn', box);
        btn.href = '#';
        btn.title = 'Karteneinstellungen';
        btn.setAttribute('aria-label', 'Karteneinstellungen');
        btn.innerHTML = {icon};
        var menu = L.DomUtil.create('div', 'tj-settings-menu', box);
        function addCheck(id, label, key) {{
          var row = L.DomUtil.create('label', '', menu);
          var boxEl = L.DomUtil.create('input', '', row);
          boxEl.type = 'checkbox';
          boxEl.id = id;
          boxEl.checked = readMapFlag(key);
          row.appendChild(document.createTextNode(label));
          L.DomEvent.on(boxEl, 'change', function(event) {{
            L.DomEvent.stop(event);
            writeMapFlag(key, boxEl.checked);
            persistMapFlags();
            if (key === 'traveljournal-show-reserve' && window.tjBridge
                && window.tjBridge.setShowReserve) {{
              window.tjBridge.setShowReserve(!!boxEl.checked);
            }}
            if (window.traveljournalApplyMapSettings) {{
              window.traveljournalApplyMapSettings();
            }}
          }});
        }}
        addCheck('tj-opt-cones', 'Fotokegel anzeigen', 'traveljournal-photo-cones');
        addCheck('tj-opt-reserve', 'Reserve-Elemente anzeigen', 'traveljournal-show-reserve');
        L.DomEvent.disableClickPropagation(box);
        L.DomEvent.on(btn, 'click', function(event) {{
          L.DomEvent.stop(event);
          if (L.DomUtil.hasClass(box, 'tj-settings-open')) {{
            L.DomUtil.removeClass(box, 'tj-settings-open');
          }} else {{
            L.DomUtil.addClass(box, 'tj-settings-open');
          }}
        }});
        return box;
      }};
      ctl.addTo(map);
      L.DomEvent.on(document, 'click', function() {{
        var el = ctl.getContainer && ctl.getContainer();
        if (el) {{
          L.DomUtil.removeClass(el, 'tj-settings-open');
        }}
      }});
    }}
"""


def _photo_cone_js() -> str:
    return f"""
    var coneLayer = L.layerGroup().addTo(map);
    var coneSpecs = [];
    var photoEntries = [];
    var focusedPhotoId = null;
    var photoRotateTimer = null;
    var photoRotateTick = 0;
    var lastDetailPayload = null;
    var CONE_MIN_ZOOM = {PHOTO_CONE_MIN_ZOOM};
    var CONE_RANGE_M = 80;
    var DEFAULT_FOV = {DEFAULT_PHOTO_FOV_DEGREES};
    var PHOTO_OVERLAP_PX = {PHOTO_OVERLAP_PX};
    var PHOTO_ROTATE_MS = {PHOTO_ROTATE_MS};
    function itemVisible(item) {{
      if (item.sort_status === 'rejected') {{
        return false;
      }}
      if (item.sort_status === 'reserve' && window.traveljournalShowReserve
          && !window.traveljournalShowReserve()) {{
        return false;
      }}
      return true;
    }}
    function destination(latlng, headingDeg, meters) {{
      var R = 6378137;
      var lat1 = latlng.lat * Math.PI / 180;
      var lon1 = latlng.lng * Math.PI / 180;
      var brng = headingDeg * Math.PI / 180;
      var ang = meters / R;
      var lat2 = Math.asin(Math.sin(lat1) * Math.cos(ang) +
        Math.cos(lat1) * Math.sin(ang) * Math.cos(brng));
      var lon2 = lon1 + Math.atan2(
        Math.sin(brng) * Math.sin(ang) * Math.cos(lat1),
        Math.cos(ang) - Math.sin(lat1) * Math.sin(lat2)
      );
      return L.latLng(lat2 * 180 / Math.PI, lon2 * 180 / Math.PI);
    }}
    function updatePhotoCones() {{
      coneLayer.clearLayers();
      if (!savedView) {{
        return;
      }}
      if (!window.traveljournalShowPhotoCones || !window.traveljournalShowPhotoCones()) {{
        return;
      }}
      if (map.getZoom() < CONE_MIN_ZOOM) {{
        return;
      }}
      coneSpecs.forEach(function(spec) {{
        if (focusedPhotoId != null && String(spec.id) !== String(focusedPhotoId)) {{
          return;
        }}
        var origin = L.latLng(spec.lat, spec.lon);
        var half = (spec.fov || DEFAULT_FOV) / 2;
        var left = spec.heading - half;
        var right = spec.heading + half;
        var pts = [origin];
        var steps = 8;
        for (var i = 0; i <= steps; i++) {{
          pts.push(destination(origin, left + (right - left) * (i / steps), CONE_RANGE_M));
        }}
        L.polygon(pts, {{
          color: '#2eb8a0',
          weight: 1,
          opacity: 0.85,
          fillColor: '#2eb8a0',
          fillOpacity: 0.22,
          interactive: false,
          className: 'tj-photo-cone'
        }}).addTo(coneLayer);
      }});
    }}
    window.traveljournalApplyMapSettings = function() {{
      if (window.tjBridge && window.tjBridge.setShowReserve && window.traveljournalShowReserve) {{
        window.tjBridge.setShowReserve(!!window.traveljournalShowReserve());
      }}
      if (lastDetailPayload && savedView) {{
        renderDetail(lastDetailPayload, true);
      }} else {{
        updatePhotoCones();
      }}
    }};
    map.on('zoomend', function() {{
      updatePhotoCones();
      syncPhotoStack();
    }});
    map.on('moveend', function() {{
      if (savedView) {{
        syncPhotoStack();
      }}
    }});
    function markerNode(marker) {{
      return (marker.getElement && marker.getElement()) || marker._icon || marker._path;
    }}
    function setEntryVisible(entry, show) {{
      var el = markerNode(entry.marker);
      if (el) {{
        el.style.visibility = show ? '' : 'hidden';
        el.style.pointerEvents = show ? '' : 'none';
      }}
    }}
    function applyPhotoVisibility() {{
      photoEntries.forEach(function(entry) {{
        var show = focusedPhotoId == null || String(entry.id) === String(focusedPhotoId);
        setEntryVisible(entry, show);
        if (!show && entry.marker.closeTooltip) {{
          entry.marker.closeTooltip();
        }}
      }});
    }}
    function overlapPhotoGroups() {{
      var n = photoEntries.length;
      if (n < 2 || map.getZoom() < {PHOTO_STACK_DISABLE_ZOOM}) {{
        return [];
      }}
      var pts = [];
      var parent = [];
      var i;
      var j;
      for (i = 0; i < n; i++) {{
        pts.push(map.latLngToContainerPoint(photoEntries[i].marker.getLatLng()));
        parent[i] = i;
      }}
      function find(x) {{
        while (parent[x] !== x) {{
          parent[x] = parent[parent[x]];
          x = parent[x];
        }}
        return x;
      }}
      var r2 = PHOTO_OVERLAP_PX * PHOTO_OVERLAP_PX;
      for (i = 0; i < n; i++) {{
        for (j = i + 1; j < n; j++) {{
          var dx = pts[i].x - pts[j].x;
          var dy = pts[i].y - pts[j].y;
          if ((dx * dx) + (dy * dy) <= r2) {{
            parent[find(i)] = find(j);
          }}
        }}
      }}
      var buckets = {{}};
      for (i = 0; i < n; i++) {{
        var root = find(i);
        if (!buckets[root]) {{
          buckets[root] = [];
        }}
        buckets[root].push(photoEntries[i]);
      }}
      var groups = [];
      Object.keys(buckets).forEach(function(key) {{
        if (buckets[key].length > 1) {{
          groups.push(buckets[key]);
        }}
      }});
      return groups;
    }}
    function stopPhotoRotate() {{
      if (photoRotateTimer) {{
        window.clearInterval(photoRotateTimer);
        photoRotateTimer = null;
      }}
    }}
    function applyOverlapRotation() {{
      var groups = overlapPhotoGroups();
      var rotating = {{}};
      groups.forEach(function(group) {{
        var idx = photoRotateTick % group.length;
        group.forEach(function(entry, i) {{
          rotating[entry.id] = true;
          var on = i === idx;
          setEntryVisible(entry, on);
          if (on && entry.marker.getTooltip && entry.marker.getTooltip()) {{
            entry.marker.openTooltip();
          }} else if (entry.marker.closeTooltip) {{
            entry.marker.closeTooltip();
          }}
        }});
      }});
      photoEntries.forEach(function(entry) {{
        if (!rotating[entry.id]) {{
          setEntryVisible(entry, true);
        }}
      }});
    }}
    function syncPhotoStack() {{
      if (focusedPhotoId != null) {{
        stopPhotoRotate();
        applyPhotoVisibility();
        return;
      }}
      if (!overlapPhotoGroups().length) {{
        stopPhotoRotate();
        photoEntries.forEach(function(entry) {{
          setEntryVisible(entry, true);
        }});
        return;
      }}
      applyOverlapRotation();
      if (!photoRotateTimer) {{
        photoRotateTimer = window.setInterval(function() {{
          if (focusedPhotoId != null) {{
            return;
          }}
          photoRotateTick += 1;
          applyOverlapRotation();
        }}, PHOTO_ROTATE_MS);
      }}
    }}
    function focusPhoto(entryId) {{
      focusedPhotoId = entryId || null;
      stopPhotoRotate();
      applyPhotoVisibility();
      updatePhotoCones();
    }}
    function clearPhotoFocus() {{
      if (focusedPhotoId == null) {{
        return;
      }}
      focusedPhotoId = null;
      applyPhotoVisibility();
      updatePhotoCones();
      syncPhotoStack();
    }}
"""


def _standalone_basemap_script(fmap: Any, extra: Any) -> str:
    map_name = fmap.get_name()
    sat_name = extra.satellite.get_name()
    topo_name = extra.topo.get_name()
    inner = _basemap_toggle_js()
    return f"""
<script>
(function() {{
  function boot() {{
    var map = {map_name};
    var satLayer = {sat_name};
    var topoLayer = {topo_name};
    if (!map || !satLayer || !topoLayer) {{
      return;
    }}
    {inner}
    {_map_settings_js()}
    installMapSettings();
    installBasemapToggle();
  }}
  function wait(tries) {{
    try {{
      if (typeof {map_name} !== 'undefined'
          && typeof {sat_name} !== 'undefined'
          && typeof {topo_name} !== 'undefined') {{
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


def _standalone_settings_script(fmap: Any) -> str:
    map_name = fmap.get_name()
    return f"""
<script>
(function() {{
  function boot() {{
    var map = {map_name};
    if (!map) {{
      return;
    }}
    {_map_settings_js()}
    installMapSettings();
  }}
  function wait(tries) {{
    try {{
      if (typeof {map_name} !== 'undefined') {{
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
            "sort_status": marker.sort_status,
            "heading": marker.heading_degrees,
            "fov": marker.fov_degrees,
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
            "sort_status": line.sort_status,
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


_BASEMAP_RULES = """
.tj-basemap {
  position: relative;
}
.tj-basemap-btn {
  width: 26px !important;
  height: 26px !important;
  display: flex !important;
  align-items: center;
  justify-content: center;
  line-height: 26px !important;
}
.tj-basemap-btn svg {
  display: block;
}
.tj-basemap-menu {
  display: none;
  position: absolute;
  top: 0;
  right: 34px;
  min-width: 108px;
  background: #fff;
  border-radius: 4px;
  box-shadow: 0 1px 5px rgba(0,0,0,.4);
  overflow: hidden;
  z-index: 1000;
}
.tj-basemap-open .tj-basemap-menu {
  display: block;
}
.tj-basemap-menu a {
  display: block;
  width: auto !important;
  min-width: 108px;
  height: 26px;
  line-height: 26px !important;
  padding: 0 12px !important;
  text-align: left;
  font-size: 12px;
  border-bottom: 1px solid #eee;
  color: #333 !important;
}
.tj-basemap-menu a:last-child {
  border-bottom: none;
}
.tj-basemap-menu a.tj-basemap-on {
  background: #2eb8a0 !important;
  color: #fff !important;
}
.tj-settings {
  position: relative;
}
.tj-settings-btn {
  width: 26px !important;
  height: 26px !important;
  display: flex !important;
  align-items: center;
  justify-content: center;
  line-height: 26px !important;
}
.tj-settings-btn svg {
  display: block;
}
.tj-settings-menu {
  display: none;
  position: absolute;
  top: 0;
  left: 34px;
  min-width: 230px;
  background: #fff;
  border-radius: 4px;
  box-shadow: 0 1px 5px rgba(0,0,0,.4);
  z-index: 1000;
  overflow: hidden;
}
.tj-settings-open .tj-settings-menu {
  display: block;
}
.tj-settings-menu label {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  margin: 0;
  color: #333;
  font: 12px/1.3 "Segoe UI", sans-serif;
  cursor: pointer;
  white-space: nowrap;
}
.tj-settings-menu label:hover {
  background: #f3f3f3;
}
.tj-photo-cone {
  pointer-events: none !important;
}
.leaflet-left .leaflet-control.tj-close-section {
  position: absolute;
  left: 36px;
  top: 0;
  margin-top: 10px;
  margin-left: 8px;
  clear: none;
  z-index: 1000;
}
.tj-close-section a {
  width: auto !important;
  padding: 0 8px !important;
  line-height: 26px !important;
  white-space: nowrap;
}
"""


_COVER_CSS = (
    """
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
.leaflet-tooltip.tj-photo-date {
  background: rgba(8, 12, 18, 0.92);
  color: #f4f7fb;
  border: none;
  border-radius: 0 0 6px 6px;
  padding: 2px 7px;
  font: 600 11px/1.2 "Segoe UI", sans-serif;
  box-shadow: 0 1px 4px rgba(0,0,0,.4);
  white-space: nowrap;
  margin: 0;
}
.leaflet-tooltip.leaflet-tooltip-bottom.tj-photo-date {
  margin-top: 0;
  margin-bottom: 0;
}
.leaflet-tooltip-bottom.tj-photo-date::before,
.leaflet-tooltip-bottom.tj-photo-date::after {
  display: none;
  content: none;
  border: none;
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
.tj-rate {
  display: flex;
  gap: 6px;
  margin-top: 8px;
}
.tj-rate-btn {
  width: 26px;
  height: 26px;
  padding: 0;
  border: 1px solid #c5c5c5;
  border-radius: 4px;
  background: #f4f4f4;
  color: #444;
  font: 700 13px/26px "Segoe UI", sans-serif;
  cursor: pointer;
}
.tj-rate-btn.tj-rate-on[data-status="favorite"] {
  background: #2eb8a0;
  border-color: #2eb8a0;
  color: #06231e;
}
.tj-rate-btn.tj-rate-on[data-status="reserve"] {
  background: #5b8def;
  border-color: #5b8def;
  color: #fff;
}
.tj-rate-btn.tj-rate-on[data-status="rejected"] {
  background: #c45c6a;
  border-color: #c45c6a;
  color: #fff;
}
.tj-stay-arrow {
  background: none !important;
  border: none !important;
  pointer-events: none !important;
}
.tj-stay-arrow-rot {
  width: 18px;
  height: 18px;
  transform-origin: 9px 9px;
}
.tj-stay-arrow-rot svg {
  display: block;
}
.leaflet-overlay-pane .tj-stay-link {
  pointer-events: none !important;
}
.tj-stack-icon {
  background: none !important;
  border: none !important;
}
.tj-stack {
  width: 36px;
  height: 36px;
  border-radius: 50%;
  background: #2eb8a0;
  color: #06231e;
  font: 700 13px/36px "Segoe UI", sans-serif;
  text-align: center;
  box-shadow: 0 1px 4px rgba(0,0,0,.45);
  border: 2px solid #fff;
}
"""
    + _BASEMAP_RULES
    + """
</style>
"""
)


_BASEMAP_CSS = "<style>\n" + _BASEMAP_RULES + "</style>\n"


_STACK_CSS = """
<style>
.tj-stack-icon {
  background: none !important;
  border: none !important;
}
.tj-stack {
  width: 36px;
  height: 36px;
  border-radius: 50%;
  background: #2eb8a0;
  color: #06231e;
  font: 700 13px/36px "Segoe UI", sans-serif;
  text-align: center;
  box-shadow: 0 1px 4px rgba(0,0,0,.45);
  border: 2px solid #fff;
}
</style>
"""


def _stay_links_payload(links: Sequence[StayLink]) -> list[dict[str, Any]]:
    return [
        {
            "start": [link.start[0], link.start[1]],
            "end": [link.end[0], link.end[1]],
            "start_key": link.start_key,
            "end_key": link.end_key,
            "style": link.style,
            "via_transfer": link.via_transfer,
        }
        for link in links
    ]


def _overview_script(
    fmap: Any,
    covers: Any,
    stay_links: Sequence[StayLink] = (),
    link_layer: Any | None = None,
    extra: Any | None = None,
    *,
    color: str = DEFAULT_STAY_LINK_COLOR,
) -> str:
    map_name = fmap.get_name()
    cover_name = covers.get_name()
    links_json = json.dumps(_stay_links_payload(stay_links), ensure_ascii=True)
    link_ref = link_layer.get_name() if link_layer is not None else "null"
    sat_ref = extra.satellite.get_name() if extra is not None else "null"
    topo_ref = extra.topo.get_name() if extra is not None else "null"
    link_color = json.dumps(normalize_stay_link_color(color), ensure_ascii=True)
    basemap_js = _basemap_toggle_js() if extra is not None else ""
    basemap_boot = "installBasemapToggle();" if extra is not None else ""
    settings_js = _map_settings_js()
    cone_js = _photo_cone_js()
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
    {_photo_cluster_js()}
    var savedView = null;
    var stayLinks = {links_json};
    var COVER_PX = {COVER_ICON_PX};
    var INSET_PX = {COVER_LINE_INSET_PX};
    var LINK_COLOR = {link_color};
    var stayLinkGroup = {link_ref};
    var satLayer = {sat_ref};
    var topoLayer = {topo_ref};
    var stayArrowLayer = L.layerGroup().addTo(map);
    function stayLinkVisible(pixelDist) {{
      return pixelDist > COVER_PX;
    }}
    function drawStayLinks() {{
      try {{
        stayArrowLayer.clearLayers();
        if (savedView) {{
          if (stayLinkGroup && map.hasLayer(stayLinkGroup)) {{
            map.removeLayer(stayLinkGroup);
          }}
          return;
        }}
        if (stayLinkGroup && !map.hasLayer(stayLinkGroup)) {{
          map.addLayer(stayLinkGroup);
        }}
        var size = map.getSize && map.getSize();
        var ready = size && size.x > 2 && size.y > 2;
        var layers = stayLinkGroup && stayLinkGroup.getLayers
          ? stayLinkGroup.getLayers()
          : [];
        stayLinks.forEach(function(link, idx) {{
          var a = L.latLng(link.start[0], link.start[1]);
          var b = L.latLng(link.end[0], link.end[1]);
          var hide = false;
          var start = a;
          var end = b;
          if (ready) {{
            var pa = map.latLngToLayerPoint(a);
            var pb = map.latLngToLayerPoint(b);
            var dist = pa.distanceTo(pb);
            if (!stayLinkVisible(dist)) {{
              hide = true;
            }} else {{
              var ux = (pb.x - pa.x) / dist;
              var uy = (pb.y - pa.y) / dist;
              start = map.layerPointToLatLng(L.point(pa.x + ux * INSET_PX, pa.y + uy * INSET_PX));
              end = map.layerPointToLatLng(L.point(pb.x - ux * INSET_PX, pb.y - uy * INSET_PX));
            }}
          }}
          var layer = layers[idx];
          if (layer && layer.setLatLngs) {{
            layer.setLatLngs([start, end]);
            if (layer.setStyle) {{
              layer.setStyle({{
                color: LINK_COLOR,
                opacity: hide ? 0 : 1,
                weight: hide ? 0 : 3.5,
                lineCap: 'butt'
              }});
            }}
          }} else if (!hide) {{
            layer = L.polyline([start, end], {{
              color: LINK_COLOR,
              weight: 3.5,
              opacity: 1,
              interactive: false,
              className: 'tj-stay-link',
              lineCap: 'butt'
            }});
            layer.addTo(stayArrowLayer);
          }}
          if (hide || !ready) {{
            return;
          }}
          var sa = map.latLngToLayerPoint(start);
          var sb = map.latLngToLayerPoint(end);
          var t = 0.62;
          var ax = sa.x + (sb.x - sa.x) * t;
          var ay = sa.y + (sb.y - sa.y) * t;
          var angle = Math.atan2(sb.y - sa.y, sb.x - sa.x) * 180 / Math.PI;
          L.marker(map.layerPointToLatLng(L.point(ax, ay)), {{
            pane: 'overlayPane',
            interactive: false,
            keyboard: false,
            icon: L.divIcon({{
              className: 'tj-stay-arrow',
              html: '<div class="tj-stay-arrow-rot" style="transform:rotate(' +
                angle + 'deg)"><svg viewBox="0 0 18 18" width="18" height="18">' +
                '<polygon points="5,4 17,9 5,14" fill="' + LINK_COLOR + '"/></svg></div>',
              iconSize: [18, 18],
              iconAnchor: [9, 9]
            }})
          }}).addTo(stayArrowLayer);
        }});
      }} catch (err) {{
        console.warn('traveljournal:stayLinks', err);
      }}
    }}
    window.traveljournalDrawStayLinks = drawStayLinks;
    map.on('zoomend', drawStayLinks);
    map.on('moveend', drawStayLinks);
    {basemap_js}
    {settings_js}
    {cone_js}
    installMapSettings();
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
    function payloadStatus(sourceId) {{
      var found = null;
      function scan(items) {{
        (items || []).forEach(function(item) {{
          if (item.source_file_id === sourceId && found === null) {{
            found = item.sort_status || null;
          }}
        }});
      }}
      if (lastDetailPayload) {{
        scan(lastDetailPayload.markers);
        if (found === null) {{
          scan(lastDetailPayload.polylines);
        }}
      }}
      return found;
    }}
    function setPayloadSort(sourceId, status) {{
      var next = status || null;
      function patch(item) {{
        if (item.source_file_id === sourceId) {{
          item.sort_status = next;
        }}
      }}
      if (!lastDetailPayload) {{
        return;
      }}
      (lastDetailPayload.markers || []).forEach(patch);
      (lastDetailPayload.polylines || []).forEach(patch);
    }}
    function sortHides(status) {{
      if (status === 'rejected') {{
        return true;
      }}
      if (status === 'reserve' && window.traveljournalShowReserve
          && !window.traveljournalShowReserve()) {{
        return true;
      }}
      return false;
    }}
    function syncRateButtons(sourceId, status) {{
      var wraps = document.querySelectorAll('.tj-rate[data-source-id="' + sourceId + '"]');
      wraps.forEach(function(wrap) {{
        var buttons = wrap.querySelectorAll('.tj-rate-btn');
        for (var i = 0; i < buttons.length; i++) {{
          var btn = buttons[i];
          if (btn.getAttribute('data-status') === status) {{
            L.DomUtil.addClass(btn, 'tj-rate-on');
          }} else {{
            L.DomUtil.removeClass(btn, 'tj-rate-on');
          }}
        }}
      }});
    }}
    function notifySort(sourceId, status) {{
      var text = status || '';
      if (window.tjBridge && window.tjBridge.setSortStatus) {{
        window.tjBridge.setSortStatus(sourceId, text);
        return;
      }}
      console.info('traveljournal:sort:' + sourceId + ':' + text);
    }}
    window.traveljournalApplySort = function(sourceId, status) {{
      var id = parseInt(sourceId, 10);
      if (!id || !savedView) {{
        return;
      }}
      setPayloadSort(id, status || null);
      renderDetail(lastDetailPayload, true);
    }};
    window.traveljournalRate = function(sourceId, status) {{
      var id = parseInt(sourceId, 10);
      if (!id || !status) {{
        return;
      }}
      var current = payloadStatus(id);
      var next = current === status ? null : status;
      setPayloadSort(id, next);
      notifySort(id, next);
      if (sortHides(current) || sortHides(next)) {{
        if (map.closePopup) {{
          map.closePopup();
        }}
        renderDetail(lastDetailPayload, true);
        return;
      }}
      syncRateButtons(id, next);
    }};
    window.traveljournalCloseSection = function() {{
      enableDrag();
      detail.clearLayers();
      coneLayer.clearLayers();
      coneSpecs = [];
      focusedPhotoId = null;
      photoEntries = [];
      stopPhotoRotate();
      lastDetailPayload = null;
      if (!map.hasLayer(covers)) {{
        map.addLayer(covers);
      }}
      if (savedView) {{
        map.setView(savedView.center, savedView.zoom);
        savedView = null;
      }}
      setCloseVisible(false);
      drawStayLinks();
      if (window.tjBridge && window.tjBridge.sectionClosed) {{
        window.tjBridge.sectionClosed();
      }}
    }};
    window.traveljournalFocusCover = function(lat, lon, key, offsetY) {{
      window.traveljournalKeepFocus = true;
      if (savedView) {{
        detail.clearLayers();
        coneLayer.clearLayers();
        coneSpecs = [];
        focusedPhotoId = null;
        photoEntries = [];
        stopPhotoRotate();
        lastDetailPayload = null;
        if (!map.hasLayer(covers)) {{
          map.addLayer(covers);
        }}
        savedView = null;
        setCloseVisible(false);
        drawStayLinks();
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
      renderDetail(payload, false);
    }};
    function renderDetail(payload, refresh) {{
      lastDetailPayload = payload;
      if (!refresh) {{
        enableDrag();
        savedView = {{center: map.getCenter(), zoom: map.getZoom()}};
        drawStayLinks();
        if (map.hasLayer(covers)) {{
          map.removeLayer(covers);
        }}
      }}
      detail.clearLayers();
      coneSpecs = [];
      focusedPhotoId = null;
      photoEntries = [];
      stopPhotoRotate();
      var cluster = photoClusterGroup();
      (payload.markers || []).forEach(function(item) {{
        if (!itemVisible(item)) {{
          return;
        }}
        var latlng = [item.latitude, item.longitude];
        var marker;
        if (item.preview) {{
          marker = L.marker(latlng, {{
            icon: L.divIcon({{
              className: 'tj-cover-icon',
              iconSize: [52, 52],
              iconAnchor: [26, 26],
              tooltipAnchor: [0, 26],
              html: '<div class="tj-thumb"><img src="' +
                String(item.preview).replace(/"/g, '&quot;') + '" alt=""></div>'
            }})
          }});
        }} else {{
          var color = '#2a7ade';
          if (item.kind === 'place') {{
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
          var tipOpts = {{direction: 'top', opacity: 0.95}};
          if (item.preview) {{
            tipOpts = {{
              direction: 'bottom',
              offset: [0, 0],
              opacity: 0.95,
              className: 'tj-photo-date'
            }};
          }}
          marker.bindTooltip(item.label, tipOpts);
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
        if (item.kind !== 'place') {{
          var entryId = item.source_file_id != null ? item.source_file_id : ('m' + photoEntries.length);
          photoEntries.push({{marker: marker, item: item, id: entryId}});
          if (item.kind === 'photo') {{
            marker.on('mouseover', function() {{
              focusPhoto(entryId);
            }});
            marker.on('mouseout', function() {{
              clearPhotoFocus();
            }});
          }}
        }}
        if (item.kind === 'photo' && typeof item.heading === 'number') {{
          coneSpecs.push({{
            id: item.source_file_id || null,
            lat: item.latitude,
            lon: item.longitude,
            heading: item.heading,
            fov: item.fov || DEFAULT_FOV
          }});
        }}
        if (cluster && item.kind !== 'place') {{
          marker.addTo(cluster);
        }} else {{
          marker.addTo(detail);
        }}
      }});
      if (cluster) {{
        cluster.addTo(detail);
      }}
      (payload.polylines || []).forEach(function(line) {{
        if (!itemVisible(line)) {{
          return;
        }}
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
      if (!refresh) {{
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
      }}
      updatePhotoCones();
      syncPhotoStack();
    }}
    closeCtl = L.control({{position: 'topleft'}});
    closeCtl.onAdd = function() {{
      var box = L.DomUtil.create('div', 'leaflet-bar tj-close-section');
      var link = L.DomUtil.create('a', '', box);
      link.href = '#';
      link.title = 'Reiseabschnitt schließen';
      link.setAttribute('aria-label', 'Reiseabschnitt schließen');
      link.innerHTML = 'Reiseabschnitt schließen';
      L.DomEvent.disableClickPropagation(box);
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
        coneLayer.clearLayers();
        coneSpecs = [];
        focusedPhotoId = null;
        photoEntries = [];
        stopPhotoRotate();
        lastDetailPayload = null;
        if (!map.hasLayer(covers)) {{
          map.addLayer(covers);
        }}
        savedView = null;
        setCloseVisible(false);
        drawStayLinks();
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
      if (!root) {{
        return;
      }}
      var img = root.querySelector
        ? root.querySelector('.tj-popup-thumb[data-source-id]')
        : null;
      if (img && !img._tjBound) {{
        img._tjBound = true;
        L.DomEvent.on(img, 'dblclick', function(ev) {{
          L.DomEvent.stop(ev);
          window.traveljournalOpenMedia(img.getAttribute('data-source-id'));
        }});
      }}
      var buttons = root.querySelectorAll ? root.querySelectorAll('.tj-rate-btn') : [];
      for (var i = 0; i < buttons.length; i++) {{
        var btn = buttons[i];
        if (btn._tjBound) {{
          continue;
        }}
        btn._tjBound = true;
        L.DomEvent.on(btn, 'click', function(ev) {{
          L.DomEvent.stop(ev);
          var node = ev.currentTarget || ev.target;
          var wrap = node && node.closest ? node.closest('.tj-rate') : null;
          var sid = wrap && wrap.getAttribute('data-source-id');
          var kind = node && node.getAttribute && node.getAttribute('data-status');
          if (sid && kind) {{
            window.traveljournalRate(sid, kind);
          }}
        }});
      }}
    }});
    map.on('dblclick', function(event) {{
      var target = event.originalEvent && event.originalEvent.target;
      if (target && target.closest && target.closest(
        '.tj-cover, .tj-cover-icon, .tj-thumb, .tj-popup-thumb, .leaflet-popup, '
        + '.tj-stack-icon, .tj-stack, .tj-photo-cone, .tj-settings, .tj-rate, '
        + '.tj-close-section'
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
    {basemap_boot}
    fitOverview();
    drawStayLinks();
    setTimeout(function() {{
      fitOverview();
      drawStayLinks();
    }}, 150);
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
            f'<img class="tj-popup-thumb" src="{html.escape(href, quote=True)}" width="180" alt=""{sid}>'
        )
    parts.append(_rating_bar_html(marker))
    return "<div style='min-width:160px'>" + "".join(parts) + "</div>"


def _rating_bar_html(marker: MapMarker) -> str:
    if not marker.source_file_id or marker.kind == "place":
        return ""
    current = marker.sort_status or ""
    sid = int(marker.source_file_id)
    buttons: list[str] = []
    for status, label, title in _RATE_CHIPS:
        on = " tj-rate-on" if current == status else ""
        buttons.append(
            f'<button type="button" class="tj-rate-btn{on}" data-status="{status}" '
            f'title="{html.escape(title, quote=True)}">{label}</button>'
        )
    return f'<div class="tj-rate" data-source-id="{sid}">' + "".join(buttons) + "</div>"


def _thumb_href(html_path: Path, preview: Path | None) -> str | None:
    if preview is None or not preview.is_file():
        return None
    try:
        relative = preview.resolve().relative_to(html_path.parent.resolve(), walk_up=True)
    except ValueError:
        return preview.resolve().as_uri()
    return relative.as_posix()


def interaction_config(
    scene: MapScene,
    html_path: Path,
    *,
    link_color: str = DEFAULT_STAY_LINK_COLOR,
) -> dict[str, Any]:
    """Declarative Leaflet payload. Hosts inject this as ``window.traveljournalConfig``."""

    return {
        "cover_px": COVER_ICON_PX,
        "inset_px": COVER_LINE_INSET_PX,
        "link_color": normalize_stay_link_color(link_color),
        "stay_links": _stay_links_payload(scene.stay_links),
        "stack_disable_zoom": PHOTO_STACK_DISABLE_ZOOM,
        "cone_min_zoom": PHOTO_CONE_MIN_ZOOM,
        "detail": leaflet_payload(scene, html_path),
    }


def config_script(config: dict[str, Any]) -> str:
    payload = json.dumps(config, ensure_ascii=True)
    return f"<script>window.traveljournalConfig = {payload};</script>\n"
