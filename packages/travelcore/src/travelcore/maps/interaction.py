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
    MapPolyline,
    MapScene,
    StayLink,
)
from travelcore.project_settings import DEFAULT_STAY_LINK_COLOR, normalize_stay_link_color
from travelcore.timeline.symbols import stay_symbol_svg_js

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
CARTO_LABEL_TILES = (
    "https://{s}.basemaps.cartocdn.com/rastertiles/voyager_only_labels/{z}/{x}/{y}{r}.png"
)
CARTO_LABEL_ATTR = (
    '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>-Mitwirkende, '
    '&copy; <a href="https://carto.com/attributions">CARTO</a>'
)
ESRI_STREET_TILES = (
    "https://server.arcgisonline.com/ArcGIS/rest/services/Reference/"
    "World_Transportation/MapServer/tile/{z}/{y}/{x}"
)
ESRI_STREET_ATTR = "Kacheln &copy; Esri &mdash; Esri, HERE, Garmin"

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


_FIT_TRIP_ICON_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" '
    'fill="none" stroke="#333" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" '
    'aria-hidden="true">'
    '<path d="M8 3H3v5"/><path d="M16 3h5v5"/><path d="M8 21H3v-5"/><path d="M16 21h5v-5"/>'
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

# Round caps turn a near-zero dash into a circular dot. A 1px dash with
# butt caps looks like a perpendicular tick (the previous dotted style).
STAY_LINK_WEIGHT = 3.5
STAY_LINK_DOTTED_WEIGHT = 5.0
STAY_LINK_DOTTED_DASH = "0.01, 12"
STAY_LINK_DASHED_DASH = "10, 8"
STAY_SYMBOL_BADGE_PX = 36


def stay_link_line_options(dash: str, *, color: str) -> dict[str, Any]:
    """Leaflet path options for a stay-link polyline (Folium fallback)."""

    dotted = dash == "dotted"
    dashed = dash == "dashed"
    style: dict[str, Any] = {
        "color": color,
        "weight": STAY_LINK_DOTTED_WEIGHT if dotted else STAY_LINK_WEIGHT,
        "opacity": 1.0,
        "interactive": False,
        "className": "tj-stay-link",
        "lineCap": "round",
        "lineJoin": "round",
    }
    if dotted:
        style["dashArray"] = STAY_LINK_DOTTED_DASH
    elif dashed:
        style["dashArray"] = STAY_LINK_DASHED_DASH
    return style


PHOTO_OVERLAP_PX = 56


PHOTO_SPIDER_MIN_PX = 120


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
        animate: false,
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
    label_url = json.dumps(CARTO_LABEL_TILES, ensure_ascii=True)
    label_attr = json.dumps(CARTO_LABEL_ATTR, ensure_ascii=True)
    street_url = json.dumps(ESRI_STREET_TILES, ensure_ascii=True)
    street_attr = json.dumps(ESRI_STREET_ATTR, ensure_ascii=True)
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
      if (!map.getPane('tjSatStreets')) {{
        map.createPane('tjSatStreets');
        map.getPane('tjSatStreets').style.zIndex = 240;
        map.getPane('tjSatStreets').style.pointerEvents = 'none';
      }}
      if (!map.getPane('tjSatLabels')) {{
        map.createPane('tjSatLabels');
        map.getPane('tjSatLabels').style.zIndex = 250;
        map.getPane('tjSatLabels').style.pointerEvents = 'none';
      }}
      var satStreetLayer = L.tileLayer({street_url}, {{
        attribution: {street_attr},
        maxZoom: 19,
        pane: 'tjSatStreets'
      }});
      var satLabelLayer = L.tileLayer({label_url}, {{
        attribution: {label_attr},
        maxZoom: 20,
        subdomains: 'abcd',
        pane: 'tjSatLabels'
      }});
      var choices = {{karte: osmLayer, topo: topoLayer, satellit: satLayer}};
      var labels = {{karte: 'Straßenkarte', topo: 'Topo', satellit: 'Satellit'}};
      var menuLinks = {{}};
      var currentBasemap = 'karte';
      function setOverlay(layer, show) {{
        if (show) {{
          if (!map.hasLayer(layer)) {{
            layer.addTo(map);
          }}
        }} else if (map.hasLayer(layer)) {{
          map.removeLayer(layer);
        }}
      }}
      function applySatOverlays() {{
        var flags = window.traveljournalMapFlags || {{}};
        var onSat = currentBasemap === 'satellit';
        setOverlay(satStreetLayer, onSat && !!flags.satStreets);
        setOverlay(satLabelLayer, onSat && !!flags.satLabels);
      }}
      window.traveljournalApplySatOverlays = applySatOverlays;
      window.traveljournalApplySatLabels = applySatOverlays;
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
        currentBasemap = kind;
        applySatOverlays();
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
    fit_icon = json.dumps(_FIT_TRIP_ICON_SVG, ensure_ascii=True)
    return f"""
    window.traveljournalMapFlags = window.traveljournalMapFlags || {{
      cones: false, reserve: false, satLabels: false, satStreets: false
    }};
    function readMapFlag(key) {{
      var flags = window.traveljournalMapFlags || {{}};
      if (key === 'traveljournal-photo-cones') {{
        return !!flags.cones;
      }}
      if (key === 'traveljournal-show-reserve') {{
        return !!flags.reserve;
      }}
      if (key === 'traveljournal-sat-labels') {{
        return !!flags.satLabels;
      }}
      if (key === 'traveljournal-sat-streets') {{
        return !!flags.satStreets;
      }}
      return false;
    }}
    function writeMapFlag(key, on) {{
      window.traveljournalMapFlags = window.traveljournalMapFlags || {{
        cones: false, reserve: false, satLabels: false, satStreets: false
      }};
      if (key === 'traveljournal-photo-cones') {{
        window.traveljournalMapFlags.cones = !!on;
      }} else if (key === 'traveljournal-show-reserve') {{
        window.traveljournalMapFlags.reserve = !!on;
      }} else if (key === 'traveljournal-sat-labels') {{
        window.traveljournalMapFlags.satLabels = !!on;
      }} else if (key === 'traveljournal-sat-streets') {{
        window.traveljournalMapFlags.satStreets = !!on;
      }}
    }}
    function persistMapFlags() {{
      var flags = window.traveljournalMapFlags || {{}};
      if (window.tjBridge && window.tjBridge.saveMapSettings) {{
        window.tjBridge.saveMapSettings(
          !!flags.cones, !!flags.reserve, !!flags.satLabels, !!flags.satStreets
        );
      }}
    }}
    window.traveljournalShowPhotoCones = function() {{
      return readMapFlag('traveljournal-photo-cones');
    }};
    window.traveljournalShowReserve = function() {{
      return readMapFlag('traveljournal-show-reserve');
    }};
    window.traveljournalApplyStoredMapFlags = function(cones, reserve, satLabels, satStreets) {{
      window.traveljournalMapFlags = {{
        cones: !!cones, reserve: !!reserve, satLabels: !!satLabels, satStreets: !!satStreets
      }};
      var conesBox = document.getElementById('tj-opt-cones');
      var reserveBox = document.getElementById('tj-opt-reserve');
      var satBox = document.getElementById('tj-opt-sat-labels');
      var streetBox = document.getElementById('tj-opt-sat-streets');
      if (conesBox) {{
        conesBox.checked = !!cones;
      }}
      if (reserveBox) {{
        reserveBox.checked = !!reserve;
      }}
      if (satBox) {{
        satBox.checked = !!satLabels;
      }}
      if (streetBox) {{
        streetBox.checked = !!satStreets;
      }}
      if (window.traveljournalApplySatOverlays) {{
        window.traveljournalApplySatOverlays();
      }} else if (window.traveljournalApplySatLabels) {{
        window.traveljournalApplySatLabels();
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
      var fitCtl = L.control({{position: 'topleft'}});
      fitCtl.onAdd = function() {{
        var box = L.DomUtil.create('div', 'leaflet-bar tj-fit-trip');
        var btn = L.DomUtil.create('a', '', box);
        btn.href = '#';
        btn.title = 'Zoom auf die gesamte Reise';
        btn.setAttribute('aria-label', 'Zoom auf die gesamte Reise');
        btn.innerHTML = {fit_icon};
        L.DomEvent.disableClickPropagation(box);
        L.DomEvent.on(btn, 'click', function(event) {{
          L.DomEvent.stop(event);
          if (window.traveljournalFitOverview) {{
            window.traveljournalFitOverview();
            return;
          }}
          var pts = [];
          map.eachLayer(function(layer) {{
            if (layer.getLatLng) {{
              pts.push(layer.getLatLng());
            }}
          }});
          if (pts.length) {{
            map.fitBounds(L.latLngBounds(pts), {{padding: [56, 56], maxZoom: 13}});
          }}
        }});
        return box;
      }};
      fitCtl.addTo(map);
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
        addCheck('tj-opt-sat-labels', 'Ortsnamen auf Satellit', 'traveljournal-sat-labels');
        addCheck('tj-opt-sat-streets', 'Straßen auf Satellit', 'traveljournal-sat-streets');
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
    if (!map.getPane('tjSpiderPane')) {{
      map.createPane('tjSpiderPane');
      map.getPane('tjSpiderPane').style.zIndex = 550;
      map.getPane('tjSpiderPane').style.pointerEvents = 'none';
    }}
    var spiderLineLayer = L.layerGroup({{pane: 'tjSpiderPane'}}).addTo(map);
    var spiderMarkerLayer = L.layerGroup().addTo(map);
    var coneSpecs = [];
    var photoEntries = [];
    var focusedPhotoId = null;
    var lastDetailPayload = null;
    var spiderLock = false;
    var stackPhase = 'idle';
    var fannedIds = {{}};
    var photoClickGuard = 0;
    var thumbCentering = false;
    var thumbPlaceTimer = 0;
    var CONE_MIN_ZOOM = {PHOTO_CONE_MIN_ZOOM};
    var CONE_RANGE_M = 80;
    var DEFAULT_FOV = {DEFAULT_PHOTO_FOV_DEGREES};
    var PHOTO_OVERLAP_PX = {PHOTO_OVERLAP_PX};
    var PHOTO_SPIDER_MIN_PX = {PHOTO_SPIDER_MIN_PX};
    var PHOTO_THUMB_PX = 52;
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
      if (stackPhase === 'fan') {{
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
        var coneEntry = spec.id != null ? entryById(spec.id) : null;
        if (coneEntry) {{
          origin = entryDisplayLatLng(coneEntry);
        }}
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
      if (window.traveljournalApplySatOverlays) {{
        window.traveljournalApplySatOverlays();
      }} else if (window.traveljournalApplySatLabels) {{
        window.traveljournalApplySatLabels();
      }}
      if (window.tjBridge && window.tjBridge.setShowReserve && window.traveljournalShowReserve) {{
        window.tjBridge.setShowReserve(!!window.traveljournalShowReserve());
      }}
      if (lastDetailPayload && savedView) {{
        renderDetail(lastDetailPayload, true);
      }} else {{
        updatePhotoCones();
      }}
    }};
    map.on('zoomstart', function() {{
      if (thumbCentering || stackPhase === 'solo' || stackPhase === 'fan') {{
        return;
      }}
      snapEntriesHome();
    }});
    map.on('zoomend', function() {{
      if (map.getZoom() < {PHOTO_STACK_DISABLE_ZOOM}
          && stackPhase !== 'solo' && stackPhase !== 'fan' && !map._popup) {{
        stackPhase = 'idle';
        fannedIds = {{}};
        focusedPhotoId = null;
      }}
      if (!thumbCentering) {{
        syncPhotoStack();
      }}
    }});
    map.on('moveend', function() {{
      if (savedView && !thumbCentering) {{
        syncPhotoStack();
      }}
    }});
    var thumbKeyGuard = 0;
    function isThumbBrowse() {{
      return !!(map._popup || stackPhase === 'solo');
    }}
    map.on('click', function(event) {{
      if (!savedView || stackPhase === 'idle') {{
        return;
      }}
      var orig = event.originalEvent;
      var target = orig && orig.target;
      if (target && target.closest && target.closest(
        '.leaflet-popup, .leaflet-control, .tj-close-section, .tj-settings, .tj-fit-trip, '
        + '.tj-cover-icon, .tj-thumb, .tj-stack, .tj-stack-icon'
      )) {{
        return;
      }}
      if (!orig || (orig.button != null && orig.button !== 0)) {{
        return;
      }}
      if (orig.detail === 0 && !orig.pointerType) {{
        return;
      }}
      if ((Date.now() - photoClickGuard) < 400 || (Date.now() - thumbKeyGuard) < 400) {{
        return;
      }}
      resetPhotoFan();
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
    function overlapPhotoGroups() {{
      var n = photoEntries.length;
      if (n < 2) {{
        return [];
      }}
      var pts = [];
      var parent = [];
      var i;
      var j;
      for (i = 0; i < n; i++) {{
        pts.push(map.latLngToContainerPoint(entryOrigin(photoEntries[i])));
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
    function entryOrigin(entry) {{
      return entry.origin || entry.marker.getLatLng();
    }}
    function entryDisplayLatLng(entry) {{
      if (stackPhase === 'solo' && String(entry.id) === String(focusedPhotoId)) {{
        return entryOrigin(entry);
      }}
      if (stackPhase === 'fan' && entry.spiderLatLng) {{
        return entry.spiderLatLng;
      }}
      return entryOrigin(entry);
    }}
    function entryById(id) {{
      var found = null;
      photoEntries.forEach(function(entry) {{
        if (found === null && String(entry.id) === String(id)) {{
          found = entry;
        }}
      }});
      return found;
    }}
    function groupForEntry(entry) {{
      var groups = overlapPhotoGroups();
      var g;
      var i;
      for (g = 0; g < groups.length; g++) {{
        for (i = 0; i < groups[g].length; i++) {{
          if (String(groups[g][i].id) === String(entry.id)) {{
            return groups[g];
          }}
        }}
      }}
      return null;
    }}
    function spiderOffsets(count) {{
      var radius = PHOTO_SPIDER_MIN_PX;
      if (count >= 2) {{
        var needed = (PHOTO_THUMB_PX / 2) / Math.sin(Math.PI / count);
        if (needed > radius) {{
          radius = needed;
        }}
      }}
      var start = -Math.PI / 2;
      var step = (Math.PI * 2) / Math.max(count, 1);
      var out = [];
      var i;
      for (i = 0; i < count; i++) {{
        var angle = start + i * step;
        out.push({{dx: Math.cos(angle) * radius, dy: Math.sin(angle) * radius}});
      }}
      return out;
    }}
    function paintSpiderOffset(entry) {{
      var el = markerNode(entry.marker);
      if (!el) {{
        return;
      }}
      var dx = entry.spiderDx || 0;
      var dy = entry.spiderDy || 0;
      var shift = (dx || dy) ? ('translate(' + dx + 'px,' + dy + 'px)') : '';
      var thumb = el.querySelector ? el.querySelector('.tj-thumb') : null;
      if (thumb) {{
        thumb.style.transform = shift;
      }}
    }}
    function setSpiderOffset(entry, dx, dy) {{
      entry.spiderDx = dx || 0;
      entry.spiderDy = dy || 0;
      paintSpiderOffset(entry);
    }}
    function clearSpiderOffset(entry) {{
      setSpiderOffset(entry, 0, 0);
    }}
    function revealEntryMarker(entry) {{
      if (!entry || !entry.marker) {{
        return;
      }}
      parkSpiderMarker(entry);
      clearSpiderOffset(entry);
      entry.spiderLatLng = null;
      entry.marker.setLatLng(entryOrigin(entry));
      setEntryVisible(entry, true);
    }}
    function parkSpiderMarker(entry) {{
      var cluster = window._tjPhotoCluster;
      if (cluster && cluster.hasLayer(entry.marker)) {{
        cluster.removeLayer(entry.marker);
      }}
      if (typeof detail !== 'undefined' && detail.hasLayer && detail.hasLayer(entry.marker)) {{
        detail.removeLayer(entry.marker);
      }}
      if (!spiderMarkerLayer.hasLayer(entry.marker)) {{
        spiderMarkerLayer.addLayer(entry.marker);
      }}
    }}
    function unparkSpiderMarker(entry) {{
      if (spiderMarkerLayer.hasLayer(entry.marker)) {{
        spiderMarkerLayer.removeLayer(entry.marker);
      }}
      var cluster = window._tjPhotoCluster;
      if (cluster) {{
        if (!cluster.hasLayer(entry.marker)) {{
          cluster.addLayer(entry.marker);
        }}
        return;
      }}
      if (typeof detail !== 'undefined' && detail.addLayer) {{
        detail.addLayer(entry.marker);
      }}
    }}
    function snapEntriesHome() {{
      spiderLineLayer.clearLayers();
      photoEntries.forEach(function(entry) {{
        entry.spiderLatLng = null;
        clearSpiderOffset(entry);
        if (entry.origin) {{
          entry.marker.setLatLng(entry.origin);
        }}
        unparkSpiderMarker(entry);
        setEntryVisible(entry, true);
      }});
    }}
    function stopPhotoRotate() {{
      stackPhase = 'idle';
      focusedPhotoId = null;
      fannedIds = {{}};
      snapEntriesHome();
    }}
    function applySpiderLayout() {{
      spiderLineLayer.clearLayers();
      var group = [];
      photoEntries.forEach(function(entry) {{
        if (fannedIds[entry.id]) {{
          group.push(entry);
        }}
      }});
      if (group.length < 2) {{
        snapEntriesHome();
        return;
      }}
      var offsets = spiderOffsets(group.length);
      var latSum = 0;
      var lngSum = 0;
      group.forEach(function(entry) {{
        var home = entryOrigin(entry);
        latSum += home.lat;
        lngSum += home.lng;
      }});
      var hub = L.latLng(latSum / group.length, lngSum / group.length);
      var hubPt = map.latLngToContainerPoint(hub);
      group.forEach(function(entry, i) {{
        var dest = map.containerPointToLatLng(
          L.point(hubPt.x + offsets[i].dx, hubPt.y + offsets[i].dy)
        );
        parkSpiderMarker(entry);
        clearSpiderOffset(entry);
        entry.spiderLatLng = dest;
        entry.marker.setLatLng(dest);
        setEntryVisible(entry, true);
        L.polyline([hub, dest], {{
          pane: 'tjSpiderPane',
          color: '#ffffff',
          weight: 1,
          opacity: 0.95,
          interactive: false,
          className: 'tj-spider-line'
        }}).addTo(spiderLineLayer);
      }});
      L.circleMarker(hub, {{
        pane: 'tjSpiderPane',
        radius: 4,
        color: '#333333',
        weight: 1,
        fillColor: '#ffffff',
        fillOpacity: 1,
        interactive: false,
        className: 'tj-spider-origin'
      }}).addTo(spiderLineLayer);
      photoEntries.forEach(function(entry) {{
        if (!fannedIds[entry.id]) {{
          entry.spiderLatLng = null;
          clearSpiderOffset(entry);
          if (entry.origin) {{
            entry.marker.setLatLng(entry.origin);
          }}
          unparkSpiderMarker(entry);
          setEntryVisible(entry, true);
        }}
      }});
      if (spiderMarkerLayer.bringToFront) {{
        spiderMarkerLayer.bringToFront();
      }}
      requestAnimationFrame(function() {{
        photoEntries.forEach(paintSpiderOffset);
      }});
    }}
    function applySoloLayout() {{
      spiderLineLayer.clearLayers();
      photoEntries.forEach(function(entry) {{
        var inFan = !!fannedIds[entry.id];
        var on = String(entry.id) === String(focusedPhotoId);
        if (inFan) {{
          setEntryVisible(entry, on);
          if (on) {{
            parkSpiderMarker(entry);
            clearSpiderOffset(entry);
            entry.spiderLatLng = null;
            entry.marker.setLatLng(entryOrigin(entry));
            if (entry.marker.getTooltip && entry.marker.getTooltip()) {{
              entry.marker.openTooltip();
            }}
          }} else if (entry.marker.closeTooltip) {{
            entry.marker.closeTooltip();
          }}
        }} else {{
          setEntryVisible(entry, true);
        }}
      }});
    }}
    function openFan(group) {{
      stackPhase = 'fan';
      focusedPhotoId = null;
      fannedIds = {{}};
      group.forEach(function(entry) {{
        fannedIds[entry.id] = true;
      }});
      if (map.closePopup) {{
        map.closePopup();
      }}
      applySpiderLayout();
      updatePhotoCones();
    }}
    function isolatePhoto(entry, keepPopup) {{
      stackPhase = 'solo';
      focusedPhotoId = entry.id;
      if (!keepPopup && map.closePopup) {{
        map.closePopup();
      }}
      revealEntryMarker(entry);
      applySoloLayout();
      updatePhotoCones();
    }}
    function resetPhotoFan() {{
      stackPhase = 'idle';
      focusedPhotoId = null;
      fannedIds = {{}};
      if (map.closePopup) {{
        map.closePopup();
      }}
      snapEntriesHome();
      updatePhotoCones();
    }}
    function estimatePopupHeight(entry) {{
      var width = 180;
      if (typeof popupThumbWidth === 'function') {{
        width = popupThumbWidth();
      }}
      var chrome = 130;
      var ratio = 0.75;
      var node = markerNode(entry && entry.marker);
      var img = node && node.querySelector ? node.querySelector('img') : null;
      if (img && img.naturalWidth > 1 && img.naturalHeight > 1) {{
        ratio = img.naturalHeight / img.naturalWidth;
      }}
      return Math.max(140, width * ratio + chrome);
    }}
    function centerBrowseView(entry) {{
      var marker = entry && entry.marker;
      var ll = marker && marker.getLatLng && marker.getLatLng();
      if (!ll) {{
        return;
      }}
      var zoom = map.getZoom() || 0;
      var size = map.getSize && map.getSize();
      if (!size || size.x < 2 || size.y < 2) {{
        return;
      }}
      var pad = 20;
      var popupH = estimatePopupHeight(entry);
      var thumbH = PHOTO_THUMB_PX;
      var groupH = popupH + thumbH;
      var markerY = size.y / 2 + groupH / 2 - thumbH / 2;
      if (markerY - popupH < pad) {{
        markerY = pad + popupH;
      }}
      thumbCentering = true;
      window.traveljournalKeepFocus = true;
      try {{
        if (map.stop) {{
          map.stop();
        }}
        var pt = map.project(ll, zoom);
        var center = map.unproject(L.point(pt.x, pt.y - (markerY - size.y / 2)), zoom);
        map.setView(center, zoom, {{animate: false}});
      }} catch (err) {{}}
      thumbCentering = false;
    }}
    function openPhotoThumbnail(entry) {{
      if (!entry || !entry.marker) {{
        return;
      }}
      revealEntryMarker(entry);
      var popup = entry.marker.getPopup && entry.marker.getPopup();
      if (popup && popup.options) {{
        popup.options.autoPan = false;
      }}
      centerBrowseView(entry);
      if (entry.marker.openPopup) {{
        entry.marker.openPopup();
      }}
    }}
    function onPhotoMarkerClick(entryId) {{
      photoClickGuard = Date.now();
      var entry = entryById(entryId);
      if (!entry) {{
        return;
      }}
      if (stackPhase === 'solo' && String(focusedPhotoId) === String(entryId)) {{
        openPhotoThumbnail(entry);
        return;
      }}
      if (stackPhase === 'fan' && fannedIds[entryId]) {{
        isolatePhoto(entry);
        return;
      }}
      if (stackPhase === 'idle') {{
        var group = groupForEntry(entry);
        if (group && group.length > 1) {{
          openFan(group);
          return;
        }}
      }}
      openPhotoThumbnail(entry);
    }}
    function scheduleSpiderSync() {{
      syncPhotoStack();
      setTimeout(syncPhotoStack, 60);
      setTimeout(syncPhotoStack, 280);
      setTimeout(syncPhotoStack, 520);
    }}
    function syncPhotoStack() {{
      if (spiderLock) {{
        return;
      }}
      spiderLock = true;
      try {{
        if (map.getZoom() < {PHOTO_STACK_DISABLE_ZOOM}) {{
          if (stackPhase === 'solo' || stackPhase === 'fan' || map._popup) {{
            if (stackPhase === 'solo') {{
              applySoloLayout();
            }}
            return;
          }}
          stackPhase = 'idle';
          fannedIds = {{}};
          focusedPhotoId = null;
          snapEntriesHome();
          return;
        }}
        if (stackPhase === 'fan') {{
          applySpiderLayout();
          return;
        }}
        if (stackPhase === 'solo') {{
          applySoloLayout();
          return;
        }}
      }} finally {{
        spiderLock = false;
        updatePhotoCones();
      }}
    }}
    function focusPhoto(entryId, keepPopup) {{
      var entry = entryById(entryId);
      if (!entry) {{
        return;
      }}
      var group = groupForEntry(entry);
      fannedIds = {{}};
      if (group && group.length > 1) {{
        group.forEach(function(item) {{
          fannedIds[item.id] = true;
        }});
      }} else {{
        fannedIds[entry.id] = true;
      }}
      isolatePhoto(entry, keepPopup);
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
            "preview": _preview_src(html_path, marker.preview_path, marker.preview_url) or "",
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
            "source_file_id": line.source_file_id,
            "popup_html": _polyline_popup_html(line),
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
            "cover": _preview_src(html_path, card.cover_path, card.cover_url) or "",
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
.tj-fit-trip a {
  width: 26px !important;
  height: 26px !important;
  display: flex !important;
  align-items: center;
  justify-content: center;
  line-height: 26px !important;
}
.tj-fit-trip svg {
  display: block;
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
.tj-spider-line,
.tj-spider-origin {
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
:root {
  --tj-cover-inner: 47px;
  --tj-cover-icon: 54px;
  --tj-thumb: 48px;
  --tj-thumb-icon: 52px;
  --tj-stack: 36px;
  --tj-popup-thumb: 180px;
}
.tj-cover-icon {
  background: rgba(0, 0, 0, 0.01) !important;
  border: none !important;
  pointer-events: auto !important;
}
.leaflet-marker-icon.tj-cover-icon:has(.tj-cover) {
  width: var(--tj-cover-icon) !important;
  height: var(--tj-cover-icon) !important;
  margin-left: calc(-0.5 * var(--tj-cover-icon)) !important;
  margin-top: calc(-0.5 * var(--tj-cover-icon)) !important;
}
.leaflet-marker-icon.tj-cover-icon:has(.tj-thumb) {
  width: var(--tj-thumb-icon) !important;
  height: var(--tj-thumb-icon) !important;
  margin-left: calc(-0.5 * var(--tj-thumb-icon)) !important;
  margin-top: calc(-0.5 * var(--tj-thumb-icon)) !important;
}
.tj-cover {
  width: var(--tj-cover-inner);
  height: var(--tj-cover-inner);
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
  width: var(--tj-thumb);
  height: var(--tj-thumb);
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
  overflow: visible !important;
}
.leaflet-interactive.tj-cover-icon {
  pointer-events: auto !important;
}
.tj-popup {
  width: var(--tj-popup-thumb);
  box-sizing: border-box;
  overflow-wrap: anywhere;
}
.tj-popup-media {
  position: relative;
  width: 100%;
  margin-top: 6px;
}
.tj-popup-thumb {
  display: block;
  width: 100%;
  height: auto;
  cursor: pointer;
  pointer-events: auto;
}
.tj-popup-arrow {
  position: absolute;
  top: 0;
  bottom: 0;
  z-index: 2;
  width: 22%;
  min-width: 36px;
  border: none;
  padding: 0;
  color: #fff;
  font: 700 28px/1 "Segoe UI", sans-serif;
  cursor: pointer;
  opacity: 0.85;
  background: transparent;
  pointer-events: auto;
}
.tj-popup-arrow[hidden] {
  display: none;
}
.tj-popup-media:hover .tj-popup-arrow:not([hidden]) {
  opacity: 1;
}
.tj-popup-prev {
  left: 0;
  background: linear-gradient(to right, rgba(8, 12, 18, 0.45), transparent);
}
.tj-popup-next {
  right: 0;
  background: linear-gradient(to left, rgba(8, 12, 18, 0.45), transparent);
}
.leaflet-popup-content:has(.tj-popup) {
  width: var(--tj-popup-thumb) !important;
  margin: 13px 14px;
}
.leaflet-popup-content-wrapper:has(.tj-popup) {
  max-width: none;
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
.tj-stay-arrow-hit {
  pointer-events: auto !important;
  cursor: pointer !important;
}
.tj-stay-badge {
  width: 36px;
  height: 36px;
  position: relative;
}
.tj-stay-badge-disc {
  position: absolute;
  inset: 0;
  border-radius: 50%;
  background: #000;
}
.tj-stay-arrow-rot {
  position: absolute;
  inset: 6px;
  width: 24px;
  height: 24px;
  transform-origin: 12px 12px;
}
.tj-stay-arrow-flip {
  width: 24px;
  height: 24px;
  transform-origin: 12px 12px;
}
.tj-stay-arrow-rot svg {
  display: block;
  width: 24px;
  height: 24px;
}
.tj-stay-dir {
  pointer-events: none !important;
}
.tj-stay-dir-rot {
  width: 18px;
  height: 18px;
  transform-origin: 9px 9px;
}
.tj-stay-dir-rot svg {
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
  width: var(--tj-stack);
  height: var(--tj-stack);
  border-radius: 50%;
  background: #2eb8a0;
  color: #06231e;
  font: 700 13px/var(--tj-stack) "Segoe UI", sans-serif;
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
:root {
  --tj-stack: 36px;
}
.tj-stack-icon {
  background: none !important;
  border: none !important;
}
.tj-stack {
  width: var(--tj-stack);
  height: var(--tj-stack);
  border-radius: 50%;
  background: #2eb8a0;
  color: #06231e;
  font: 700 13px/var(--tj-stack) "Segoe UI", sans-serif;
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
            "transfer_key": link.transfer_key,
            "hubs": [
                {"key": hub.key, "lat": hub.latitude, "lon": hub.longitude}
                for hub in link.hubs
            ],
            "segments": [
                {
                    "role": segment.role,
                    "style": segment.style,
                    "dash": segment.dash,
                    "symbol": segment.symbol,
                    "points": [[point[0], point[1]] for point in segment.points],
                }
                for segment in link.segments
                if len(segment.points) >= 2
            ],
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
    symbol_js = stay_symbol_svg_js()
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
    if (!map.getPane('tjStaySymbolPane')) {{
      map.createPane('tjStaySymbolPane');
      map.getPane('tjStaySymbolPane').style.zIndex = 450;
      map.getPane('tjStaySymbolPane').style.pointerEvents = 'none';
    }}
    var stayArrowLayer = L.layerGroup({{pane: 'tjStaySymbolPane'}}).addTo(map);
    function stayLinkVisible(pixelDist) {{
      return pixelDist > COVER_PX;
    }}
    function lineOptsFor(dash, hide) {{
      var dotted = dash === 'dotted';
      var dashed = dash === 'dashed';
      return {{
        color: LINK_COLOR,
        weight: hide ? 0 : (dotted ? 5 : 3.5),
        opacity: hide ? 0 : 1,
        interactive: false,
        className: 'tj-stay-link',
        lineCap: 'round',
        lineJoin: 'round',
        dashArray: dotted ? '0.01, 12' : (dashed ? '10, 8' : null)
      }};
    }}
{symbol_js}
    function staySymbolHeading(angle) {{
      var flip = angle > 90 || angle < -90;
      var rot = flip ? angle - (angle > 0 ? 180 : -180) : angle;
      return {{rot: rot, flip: flip}};
    }}
    function staySymbolMarkup(angle, svg) {{
      var heading = staySymbolHeading(angle);
      return '<div class="tj-stay-badge">' +
        '<div class="tj-stay-badge-disc"></div>' +
        '<div class="tj-stay-arrow-rot" style="transform:rotate(' +
        heading.rot + 'deg)"><div class="tj-stay-arrow-flip"' +
        (heading.flip ? ' style="transform:scaleX(-1)"' : '') +
        '><svg viewBox="0 0 256 256">' + svg + '</svg></div></div></div>';
    }}
    function addStayLine(pts, opts) {{
      var line = L.polyline(pts, opts);
      if (stayLinkGroup) {{
        line.addTo(stayLinkGroup);
      }} else {{
        line.addTo(stayArrowLayer);
      }}
    }}
    function drawStayStem(fromLatLng, toLatLng) {{
      var a = map.latLngToLayerPoint(fromLatLng);
      var b = map.latLngToLayerPoint(toLatLng);
      var dist = a.distanceTo(b);
      var fromR = COVER_PX / 2;
      var toR = 18;
      if (dist < fromR + toR + 4) {{
        return;
      }}
      var ux = (b.x - a.x) / dist;
      var uy = (b.y - a.y) / dist;
      addStayLine([
        map.layerPointToLatLng(L.point(a.x + ux * fromR, a.y + uy * fromR)),
        map.layerPointToLatLng(L.point(b.x - ux * toR, b.y - uy * toR))
      ], {{
        color: '#ffffff',
        weight: 1.25,
        opacity: 1,
        interactive: false,
        className: 'tj-stay-stem',
        lineCap: 'round',
        lineJoin: 'round'
      }});
    }}
    function pointAlong(pts, fraction) {{
      var pixels = pts.map(function(pt) {{
        return map.latLngToLayerPoint(pt);
      }});
      var total = 0;
      for (var i = 1; i < pixels.length; i++) {{
        total += pixels[i - 1].distanceTo(pixels[i]);
      }}
      if (total < 1) {{
        return {{latlng: pts[0], angle: 0}};
      }}
      var target = total * fraction;
      var walked = 0;
      for (var j = 1; j < pixels.length; j++) {{
        var seg = pixels[j - 1].distanceTo(pixels[j]);
        if (walked + seg >= target || j === pixels.length - 1) {{
          var t = seg < 1e-6 ? 0 : (target - walked) / seg;
          t = Math.max(0, Math.min(1, t));
          var angle = Math.atan2(
            pixels[j].y - pixels[j - 1].y,
            pixels[j].x - pixels[j - 1].x
          ) * 180 / Math.PI;
          return {{
            latlng: map.layerPointToLatLng(L.point(
              pixels[j - 1].x + (pixels[j].x - pixels[j - 1].x) * t,
              pixels[j - 1].y + (pixels[j].y - pixels[j - 1].y) * t
            )),
            angle: angle
          }};
        }}
        walked += seg;
      }}
      return {{latlng: pts[pts.length - 1], angle: 0}};
    }}
    function addStayArrow(latlng, angle) {{
      L.marker(latlng, {{
        pane: 'tjStaySymbolPane',
        interactive: false,
        keyboard: false,
        icon: L.divIcon({{
          className: 'tj-stay-arrow tj-stay-dir',
          html: '<div class="tj-stay-dir-rot" style="transform:rotate(' +
            angle + 'deg)"><svg viewBox="0 0 18 18" width="18" height="18">' +
            '<polygon points="5,4 17,9 5,14" fill="' + LINK_COLOR +
            '"/></svg></div>',
          iconSize: [18, 18],
          iconAnchor: [9, 9]
        }})
      }}).addTo(stayArrowLayer);
    }}
    function addStayMarker(latlng, angle, symbol, groupKey) {{
      var svg = staySymbolSvg(symbol, '#ffffff');
      var clickable = !!groupKey;
      var marker = L.marker(latlng, {{
        pane: 'tjStaySymbolPane',
        interactive: clickable,
        keyboard: false,
        icon: L.divIcon({{
          className: 'tj-stay-arrow' + (clickable ? ' tj-stay-arrow-hit' : ''),
          html: staySymbolMarkup(angle, svg),
          iconSize: [36, 36],
          iconAnchor: [18, 18]
        }})
      }});
      if (clickable) {{
        marker.on('click', function(event) {{
          L.DomEvent.stop(event);
          if (window.traveljournalExpand) {{
            window.traveljournalExpand(groupKey);
          }}
        }});
      }}
      marker.addTo(stayArrowLayer);
    }}
    function insetStart(points) {{
      if (!points || points.length < 2) {{
        return points;
      }}
      var first = map.latLngToLayerPoint(points[0]);
      var second = map.latLngToLayerPoint(points[1]);
      var head = first.distanceTo(second);
      if (head <= INSET_PX) {{
        return points;
      }}
      var out = points.slice();
      out[0] = map.layerPointToLatLng(L.point(
        first.x + (second.x - first.x) / head * INSET_PX,
        first.y + (second.y - first.y) / head * INSET_PX
      ));
      return out;
    }}
    function insetEnd(points) {{
      if (!points || points.length < 2) {{
        return points;
      }}
      var last = map.latLngToLayerPoint(points[points.length - 1]);
      var prev = map.latLngToLayerPoint(points[points.length - 2]);
      var tail = last.distanceTo(prev);
      if (tail <= INSET_PX) {{
        return points;
      }}
      var out = points.slice();
      out[out.length - 1] = map.layerPointToLatLng(L.point(
        last.x + (prev.x - last.x) / tail * INSET_PX,
        last.y + (prev.y - last.y) / tail * INSET_PX
      ));
      return out;
    }}
    function drawStayLinks() {{
      try {{
        stayArrowLayer.clearLayers();
        if (stayLinkGroup && stayLinkGroup.clearLayers) {{
          stayLinkGroup.clearLayers();
        }}
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
        stayLinks.forEach(function(link) {{
          var a = L.latLng(link.start[0], link.start[1]);
          var b = L.latLng(link.end[0], link.end[1]);
          var hide = false;
          if (ready) {{
            var pa = map.latLngToLayerPoint(a);
            var pb = map.latLngToLayerPoint(b);
            hide = !stayLinkVisible(pa.distanceTo(pb));
          }}
          var pieces = (link.segments && link.segments.length)
            ? link.segments
            : [{{
                role: 'user',
                style: 'straight',
                dash: 'solid',
                symbol: null,
                points: [[link.start[0], link.start[1]], [link.end[0], link.end[1]]]
              }}];
          var drawn = [];
          pieces.forEach(function(segment) {{
            if (!segment.points || segment.points.length < 2) {{
              return;
            }}
            drawn.push({{
              role: segment.role || 'user',
              dash: segment.dash || 'solid',
              symbol: segment.symbol || null,
              points: segment.points.map(function(pt) {{
                return L.latLng(pt[0], pt[1]);
              }})
            }});
          }});
          if (!drawn.length || hide) {{
            return;
          }}
          if (ready) {{
            drawn[0].points = insetStart(drawn[0].points);
            drawn[drawn.length - 1].points = insetEnd(drawn[drawn.length - 1].points);
          }}
          drawn.forEach(function(segment) {{
            var pts = segment.points;
            if (ready && segment.role === 'gap') {{
              var ga = map.latLngToLayerPoint(pts[0]);
              var gb = map.latLngToLayerPoint(pts[pts.length - 1]);
              if (ga.distanceTo(gb) < 8) {{
                return;
              }}
            }}
            addStayLine(pts, lineOptsFor(segment.dash, hide));
            if (hide || !ready || segment.role === 'gap') {{
              return;
            }}
            var placed = pointAlong(pts, segment.symbol ? 0.62 : 0.5);
            var symbolAt = placed.latlng;
            var angle = placed.angle;
            if (!link.via_transfer) {{
              var from = map.latLngToLayerPoint(a);
              var to = map.latLngToLayerPoint(b);
              if (from.distanceTo(to) >= 1) {{
                angle = Math.atan2(to.y - from.y, to.x - from.x) * 180 / Math.PI;
              }}
            }}
            if (segment.symbol) {{
              addStayMarker(symbolAt, angle, segment.symbol, link.transfer_key);
              var hubs = link.hubs || [];
              for (var h = 0; h < hubs.length; h++) {{
                drawStayStem(L.latLng(hubs[h].lat, hubs[h].lon), symbolAt);
              }}
            }} else {{
              addStayArrow(symbolAt, angle);
            }}
          }});
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
    function overlapCoverPack(key) {{
      var layers = [];
      covers.eachLayer(function(layer) {{
        if (layer.getLatLng && layerKey(layer)) {{
          layers.push(layer);
        }}
      }});
      var n = layers.length;
      if (n < 2) {{
        return [];
      }}
      var pts = [];
      var parent = [];
      var i;
      var j;
      for (i = 0; i < n; i++) {{
        pts.push(map.latLngToContainerPoint(layers[i].getLatLng()));
        parent[i] = i;
      }}
      function find(x) {{
        while (parent[x] !== x) {{
          parent[x] = parent[parent[x]];
          x = parent[x];
        }}
        return x;
      }}
      var r2 = COVER_PX * COVER_PX;
      for (i = 0; i < n; i++) {{
        for (j = i + 1; j < n; j++) {{
          var dx = pts[i].x - pts[j].x;
          var dy = pts[i].y - pts[j].y;
          if ((dx * dx) + (dy * dy) <= r2) {{
            parent[find(i)] = find(j);
          }}
        }}
      }}
      var start = -1;
      for (i = 0; i < n; i++) {{
        if (layerKey(layers[i]) === key) {{
          start = i;
          break;
        }}
      }}
      if (start < 0) {{
        return [];
      }}
      var root = find(start);
      var pack = [];
      for (i = 0; i < n; i++) {{
        if (find(i) === root) {{
          pack.push(layers[i]);
        }}
      }}
      return pack;
    }}
    window.traveljournalFitCoverPack = function(key) {{
      if (!key || savedView) {{
        return false;
      }}
      var pack = overlapCoverPack(key);
      if (pack.length < 2) {{
        return false;
      }}
      var bounds = L.latLngBounds(pack.map(function(layer) {{
        return layer.getLatLng();
      }}));
      if (!bounds || !bounds.isValid()) {{
        return false;
      }}
      var overlay = window.traveljournalOverlayPad || 0;
      var pad = L.point(56, 56 + overlay);
      var wanted = map.getBoundsZoom ? map.getBoundsZoom(bounds, false, pad) : 13;
      if (typeof wanted !== 'number') {{
        return false;
      }}
      wanted = Math.min(wanted, 13);
      if (wanted <= (map.getZoom() || 0) + 0.25) {{
        return false;
      }}
      window.traveljournalKeepFocus = true;
      try {{
        if (map.stop) {{
          map.stop();
        }}
        map.fitBounds(bounds, {{
          paddingTopLeft: [56, 56],
          paddingBottomRight: [56, 56 + overlay],
          maxZoom: 13,
          animate: true,
          pan: {{animate: true}},
          zoom: {{animate: false}}
        }});
        if (window.traveljournalMarkCover) {{
          window.traveljournalMarkCover(key);
        }}
      }} catch (err) {{
        return false;
      }}
      return true;
    }};
    window.traveljournalCenterCover = function(key) {{
      if (!key) {{
        return;
      }}
      if (window.traveljournalFitCoverPack && window.traveljournalFitCoverPack(key)) {{
        return;
      }}
      var target = null;
      covers.eachLayer(function(layer) {{
        if (!target && layerKey(layer) === key) {{
          target = layer;
        }}
      }});
      var ll = target && target.getLatLng && target.getLatLng();
      if (!ll) {{
        return;
      }}
      var zoom = Math.max(map.getZoom() || 0, 14);
      if (window.traveljournalZoomToCover) {{
        window.traveljournalZoomToCover(ll.lat, ll.lng, key, zoom);
        return;
      }}
      window.traveljournalKeepFocus = true;
      map.setView(ll, zoom, {{
        animate: true,
        pan: {{animate: true}},
        zoom: {{animate: false}}
      }});
      if (window.traveljournalMarkCover) {{
        window.traveljournalMarkCover(key);
      }}
    }};
    if (!window.traveljournalCoverActivate) {{
      window.traveljournalCoverActivate = function(key, detail) {{
        if (!key) {{
          return;
        }}
        var now = Date.now();
        if (detail) {{
          if (window._tjCoverTimer) {{
            clearTimeout(window._tjCoverTimer);
            window._tjCoverTimer = null;
          }}
          window.traveljournalExpand(key);
          return;
        }}
        if (window._tjCoverKey === key && now - (window._tjCoverPulse || 0) < 50) {{
          return;
        }}
        window._tjCoverPulse = now;
        if (window._tjCoverKey === key && now - (window._tjCoverAt || 0) < 350) {{
          if (window._tjCoverTimer) {{
            clearTimeout(window._tjCoverTimer);
            window._tjCoverTimer = null;
          }}
          window._tjCoverAt = 0;
          window._tjCoverKey = '';
          window.traveljournalExpand(key);
          return;
        }}
        window._tjCoverKey = key;
        window._tjCoverAt = now;
        if (window._tjCoverTimer) {{
          clearTimeout(window._tjCoverTimer);
        }}
        window._tjCoverTimer = setTimeout(function() {{
          window._tjCoverTimer = null;
          window.traveljournalCenterCover(key);
        }}, 280);
      }};
    }}
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
    function popupThumbWidth() {{
      var raw = document.documentElement.style.getPropertyValue('--tj-popup-thumb');
      var n = parseInt(raw, 10);
      return n > 0 ? n : 180;
    }}
    function applyPopupLayout(popup) {{
      var width = popupThumbWidth();
      if (!popup) {{
        return;
      }}
      popup.options.maxWidth = Math.max(260, width + 48);
      popup.options.minWidth = width;
      popup.options.autoPan = false;
      if (popup.update) {{
        popup.update();
      }}
      var el = popup.getElement && popup.getElement();
      var content = el && el.querySelector ? el.querySelector('.leaflet-popup-content') : null;
      if (content) {{
        content.style.width = width + 'px';
      }}
      var wrap = el && el.querySelector ? el.querySelector('.leaflet-popup-content-wrapper') : null;
      if (wrap) {{
        wrap.style.maxWidth = 'none';
      }}
      bindPopupChrome(el);
    }}
    function visitPopups(layer, fn) {{
      if (!layer) {{
        return;
      }}
      var popup = layer.getPopup && layer.getPopup();
      if (popup) {{
        fn(popup);
      }}
      if (layer.eachLayer) {{
        layer.eachLayer(function(child) {{
          visitPopups(child, fn);
        }});
      }}
    }}
    function popupBrowseList() {{
      var found = [];
      photoEntries.forEach(function(entry) {{
        if (!entry || !entry.item || entry.item.kind === 'place') {{
          return;
        }}
        if (!entry.item.popup_html || entry.id == null) {{
          return;
        }}
        found.push(entry);
      }});
      return found;
    }}
    function currentPopupSourceId() {{
      var img = document.querySelector('.leaflet-popup .tj-popup-thumb[data-source-id]');
      if (img) {{
        return img.getAttribute('data-source-id');
      }}
      var rate = document.querySelector('.leaflet-popup .tj-rate[data-source-id]');
      return rate ? rate.getAttribute('data-source-id') : null;
    }}
    var popupBrowseIndex = -1;
    var popupStepGen = 0;
    var browseLock = false;
    function currentPopupIndex(list) {{
      var sid = currentPopupSourceId();
      var i;
      for (i = 0; i < list.length; i++) {{
        if (String(list[i].id) === String(sid)) {{
          return i;
        }}
      }}
      if (map._popup) {{
        for (i = 0; i < list.length; i++) {{
          var popup = list[i].marker && list[i].marker.getPopup && list[i].marker.getPopup();
          if (popup && popup === map._popup) {{
            return i;
          }}
        }}
      }}
      return -1;
    }}
    function rememberBrowseIndex() {{
      if (browseLock) {{
        return;
      }}
      var idx = currentPopupIndex(popupBrowseList());
      if (idx >= 0) {{
        popupBrowseIndex = idx;
      }}
    }}
    function syncPopupArrows(root) {{
      var list = popupBrowseList();
      var show = list.length > 1;
      var buttons = root && root.querySelectorAll ? root.querySelectorAll('.tj-popup-arrow') : [];
      for (var i = 0; i < buttons.length; i++) {{
        if (show) {{
          buttons[i].removeAttribute('hidden');
        }} else {{
          buttons[i].setAttribute('hidden', 'hidden');
        }}
      }}
    }}
    function bindPopupChrome(root) {{
      if (!root || !root.querySelector) {{
        return;
      }}
      var img = root.querySelector('.tj-popup-thumb[data-source-id]');
      if (img && !img._tjBound) {{
        img._tjBound = true;
        L.DomEvent.on(img, 'dblclick', function(ev) {{
          L.DomEvent.stop(ev);
          window.traveljournalOpenMedia(img.getAttribute('data-source-id'));
        }});
      }}
      rememberBrowseIndex();
      syncPopupArrows(root);
      var arrows = root.querySelectorAll('.tj-popup-arrow');
      for (var a = 0; a < arrows.length; a++) {{
        var arrow = arrows[a];
        if (arrow._tjBound) {{
          continue;
        }}
        arrow._tjBound = true;
        L.DomEvent.on(arrow, 'click', function(ev) {{
          L.DomEvent.stop(ev);
          var node = ev.currentTarget || ev.target;
          var back = node && node.classList && node.classList.contains('tj-popup-prev');
          window.traveljournalPopupStep(back ? -1 : 1);
        }});
      }}
      var buttons = root.querySelectorAll('.tj-rate-btn');
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
    }}
    function openEntryPopup(entry) {{
      openPhotoThumbnail(entry);
    }}
    window.traveljournalPopupStep = function(delta) {{
      var list = popupBrowseList();
      if (list.length < 2 || !delta) {{
        return;
      }}
      var index = popupBrowseIndex;
      if (index < 0 || index >= list.length) {{
        index = currentPopupIndex(list);
      }}
      if (index < 0 || index >= list.length) {{
        index = 0;
      }}
      var nextIndex = (index + delta + list.length) % list.length;
      var next = list[nextIndex];
      if (!next) {{
        return;
      }}
      popupBrowseIndex = nextIndex;
      popupStepGen += 1;
      browseLock = true;
      window.traveljournalKeepFocus = true;
      if (typeof focusPhoto === 'function') {{
        focusPhoto(next.id, true);
      }}
      openEntryPopup(next);
      applyPopupLayout(next.marker && next.marker.getPopup && next.marker.getPopup());
      browseLock = false;
    }};
    window.traveljournalSetThumbZoom = function(percent) {{
      var n = parseInt(percent, 10);
      if (!n || n < 50) {{
        n = 50;
      }}
      if (n > 200) {{
        n = 200;
      }}
      var width = Math.round(180 * n / 100);
      document.documentElement.style.setProperty('--tj-popup-thumb', width + 'px');
      photoEntries.forEach(function(entry) {{
        var popup = entry.marker && entry.marker.getPopup && entry.marker.getPopup();
        if (popup) {{
          popup.options.maxWidth = Math.max(260, width + 48);
          popup.options.minWidth = width;
        }}
      }});
      if (map._popup) {{
        applyPopupLayout(map._popup);
        return;
      }}
      if (map.eachLayer) {{
        map.eachLayer(function(layer) {{
          visitPopups(layer, applyPopupLayout);
        }});
      }}
    }};
    if (window.traveljournalThumbZoom) {{
      window.traveljournalSetThumbZoom(window.traveljournalThumbZoom);
    }}
    window.traveljournalCloseSection = function() {{
      enableDrag();
      stopPhotoRotate();
      focusedPhotoId = null;
      detail.clearLayers();
      coneLayer.clearLayers();
      spiderLineLayer.clearLayers();
      spiderMarkerLayer.clearLayers();
      coneSpecs = [];
      photoEntries = [];
      window._tjPhotoCluster = null;
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
    window.traveljournalMarkCover = function(key) {{
      covers.eachLayer(function(layer) {{
        var el = (layer.getElement && layer.getElement()) || layer._icon;
        var node = el && el.querySelector ? el.querySelector('.tj-cover') : null;
        if (!node || !node.classList) {{
          return;
        }}
        var on = key && node.getAttribute('data-group-key') === key;
        node.classList.toggle('tj-focused', on);
      }});
    }};
    window.traveljournalFocusCover = function(lat, lon, key, offsetY) {{
      window.traveljournalKeepFocus = true;
      if (savedView) {{
        stopPhotoRotate();
        focusedPhotoId = null;
        detail.clearLayers();
        coneLayer.clearLayers();
        spiderLineLayer.clearLayers();
        spiderMarkerLayer.clearLayers();
        coneSpecs = [];
        photoEntries = [];
        window._tjPhotoCluster = null;
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
        window.traveljournalMarkCover(key);
      }} catch (err) {{}}
    }};
    window.traveljournalZoomToCover = function(lat, lon, key, zoom) {{
      window.traveljournalKeepFocus = true;
      if (savedView) {{
        stopPhotoRotate();
        focusedPhotoId = null;
        detail.clearLayers();
        coneLayer.clearLayers();
        spiderLineLayer.clearLayers();
        spiderMarkerLayer.clearLayers();
        coneSpecs = [];
        photoEntries = [];
        window._tjPhotoCluster = null;
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
      var targetZoom = typeof zoom === 'number' ? zoom : 14;
      try {{
        if (map.stop) {{
          map.stop();
        }}
        map.setView(L.latLng(lat, lon), targetZoom, {{
          animate: true,
          pan: {{animate: true}},
          zoom: {{animate: false}}
        }});
        window.traveljournalMarkCover(key);
      }} catch (err) {{}}
    }};
    window.traveljournalShowDetail = function(payload) {{
      renderDetail(payload, false);
    }};
    window.traveljournalFocusMedia = function(sourceId) {{
      var id = parseInt(sourceId, 10);
      if (!id) {{
        return;
      }}
      window.traveljournalKeepFocus = true;
      var target = null;
      photoEntries.forEach(function(entry) {{
        if (target === null && String(entry.id) === String(id)) {{
          target = entry;
        }}
      }});
      if (target && target.marker && target.marker.getLatLng) {{
        focusPhoto(id, true);
        openEntryPopup(target);
        applyPopupLayout(target.marker.getPopup && target.marker.getPopup());
        return;
      }}
      var lines = (lastDetailPayload && lastDetailPayload.polylines) || [];
      for (var i = 0; i < lines.length; i++) {{
        var line = lines[i];
        if (line.source_file_id !== id || !line.points || !line.points.length) {{
          continue;
        }}
        try {{
          var bounds = L.latLngBounds(line.points);
          if (bounds && bounds.isValid()) {{
            var pad = window.traveljournalOverlayPad || 0;
            map.fitBounds(bounds, {{
              paddingTopLeft: [32, 32],
              paddingBottomRight: [32, 32 + pad],
              maxZoom: 15
            }});
          }}
        }} catch (err) {{}}
        return;
      }}
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
      stopPhotoRotate();
      focusedPhotoId = null;
      detail.clearLayers();
      spiderLineLayer.clearLayers();
      spiderMarkerLayer.clearLayers();
      coneSpecs = [];
      photoEntries = [];
      window._tjPhotoCluster = null;
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
              iconSize: [PHOTO_THUMB_PX, PHOTO_THUMB_PX],
              iconAnchor: [PHOTO_THUMB_PX / 2, PHOTO_THUMB_PX / 2],
              tooltipAnchor: [0, PHOTO_THUMB_PX / 2],
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
          marker.bindPopup(item.popup_html, {{
            maxWidth: Math.max(260, popupThumbWidth() + 48),
            minWidth: popupThumbWidth(),
            autoPan: false
          }});
        }}
        if (item.source_file_id) {{
          marker.on('dblclick', function(event) {{
            L.DomEvent.stop(event);
            window.traveljournalOpenMedia(item.source_file_id);
          }});
        }}
        if (item.kind !== 'place') {{
          var entryId = item.source_file_id != null ? item.source_file_id : ('m' + photoEntries.length);
          photoEntries.push({{
            marker: marker,
            item: item,
            id: entryId,
            origin: L.latLng(item.latitude, item.longitude),
            spiderLatLng: null
          }});
          marker.off('click');
          marker.on('click', function(event) {{
            L.DomEvent.stop(event);
            onPhotoMarkerClick(entryId);
          }});
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
        window._tjPhotoCluster = cluster;
        cluster.addTo(detail);
        if (cluster.on) {{
          cluster.on('animationend', scheduleSpiderSync);
        }}
      }} else {{
        window._tjPhotoCluster = null;
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
        if (line.popup_html) {{
          layer.bindPopup(line.popup_html);
        }}
        layer.addTo(detail);
      }});
      if (!refresh) {{
        setCloseVisible(true);
        if (payload && payload.focus_source_id) {{
          window.traveljournalFocusMedia(payload.focus_source_id);
        }} else {{
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
      }}
      updatePhotoCones();
      scheduleSpiderSync();
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
        stopPhotoRotate();
        focusedPhotoId = null;
        detail.clearLayers();
        coneLayer.clearLayers();
        spiderLineLayer.clearLayers();
        spiderMarkerLayer.clearLayers();
        coneSpecs = [];
        photoEntries = [];
        window._tjPhotoCluster = null;
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
      applyPopupLayout(event.popup);
    }});
    map.on('zoomend', function() {{
      var open = map._popup;
      if (open) {{
        bindPopupChrome(open.getElement && open.getElement());
      }}
    }});
    document.addEventListener('keydown', function(ev) {{
      if (ev.key !== 'ArrowLeft' && ev.key !== 'ArrowRight') {{
        return;
      }}
      if (!isThumbBrowse()) {{
        return;
      }}
      thumbKeyGuard = Date.now();
      ev.preventDefault();
      ev.stopPropagation();
      if (ev.stopImmediatePropagation) {{
        ev.stopImmediatePropagation();
      }}
      window.traveljournalPopupStep(ev.key === 'ArrowLeft' ? -1 : 1);
    }}, true);
    map.on('dblclick', function(event) {{
      var target = event.originalEvent && event.originalEvent.target;
      if (target && target.closest && target.closest(
        '.tj-cover, .tj-cover-icon, .tj-thumb, .tj-popup-thumb, .leaflet-popup, '
        + '.tj-stack-icon, .tj-stack, .tj-photo-cone, .tj-settings, .tj-fit-trip, .tj-rate, '
        + '.tj-popup-arrow, .tj-close-section'
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
      function activateCover(event, detail) {{
        L.DomEvent.stop(event);
        var key = layerKey(layer);
        if (key && window.traveljournalCoverActivate) {{
          var clicks = event.originalEvent && event.originalEvent.detail;
          window.traveljournalCoverActivate(key, !!detail || clicks >= 2);
        }}
      }}
      layer.on('click', function(event) {{
        activateCover(event, false);
      }});
      layer.on('dblclick', function(event) {{
        activateCover(event, true);
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
        L.DomEvent.on(el, 'click', function(event) {{
          activateCover(event, false);
        }});
        L.DomEvent.on(el, 'dblclick', function(event) {{
          activateCover(event, true);
        }});
        L.DomEvent.on(el, 'pointerup', function(event) {{
          activateCover(event, false);
        }});
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
        window.traveljournalCoverActivate(node.getAttribute('data-group-key'), false);
      }}, true);
      mapEl.addEventListener('click', function(event) {{
        var node = coverNodeFromEvent(event);
        if (!node) {{
          return;
        }}
        event.stopPropagation();
        window.traveljournalCoverActivate(node.getAttribute('data-group-key'), event.detail >= 2);
      }}, true);
      mapEl.addEventListener('dblclick', function(event) {{
        var node = coverNodeFromEvent(event);
        if (!node) {{
          return;
        }}
        event.preventDefault();
        event.stopPropagation();
        window.traveljournalCoverActivate(node.getAttribute('data-group-key'), true);
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
        var clicks = event.originalEvent && event.originalEvent.detail;
        window.traveljournalCoverActivate(bestKey, clicks >= 2);
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
    href = _preview_src(html_path, marker.preview_path, marker.preview_url)
    if href is not None:
        sid = ""
        if marker.source_file_id:
            sid = f' data-source-id="{int(marker.source_file_id)}"'
        src = html.escape(href, quote=True)
        parts.append(
            '<div class="tj-popup-media">'
            '<button type="button" class="tj-popup-arrow tj-popup-prev" title="Vorheriges">‹</button>'
            f'<img class="tj-popup-thumb" src="{src}" width="180" alt=""{sid}>'
            '<button type="button" class="tj-popup-arrow tj-popup-next" title="Nächstes">›</button>'
            "</div>"
        )
    parts.append(_rating_bar_html(marker))
    return '<div class="tj-popup">' + "".join(parts) + "</div>"


def _polyline_popup_html(line: MapPolyline) -> str:
    parts: list[str] = []
    if line.name:
        parts.append(f"<strong>{html.escape(line.name)}</strong>")
    if line.pilot:
        parts.append(f"<div>Pilot: {html.escape(line.pilot)}</div>")
    if line.external_url:
        href = html.escape(line.external_url, quote=True)
        parts.append(f'<div><a href="{href}" target="_blank" rel="noopener">DHV-Leonardo</a></div>')
    rating = _rating_bar_html_for(line.source_file_id, line.sort_status, kind=line.kind)
    if rating:
        parts.append(rating)
    if not parts:
        return ""
    return '<div style="min-width:180px">' + "".join(parts) + "</div>"


def _rating_bar_html(marker: MapMarker) -> str:
    return _rating_bar_html_for(marker.source_file_id, marker.sort_status, kind=marker.kind)


def _rating_bar_html_for(source_file_id: int | None, sort_status: str | None, *, kind: str = "") -> str:
    if not source_file_id or kind == "place":
        return ""
    current = sort_status or ""
    sid = int(source_file_id)
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


def _preview_src(html_path: Path, preview: Path | None, url: str | None = None) -> str | None:
    href = _thumb_href(html_path, preview)
    if href:
        return href
    if url and url.startswith(("http://", "https://")):
        return url
    return None


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
