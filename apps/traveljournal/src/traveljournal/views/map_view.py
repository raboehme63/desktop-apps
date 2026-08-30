"""Interactive project map. Original media files are never written."""

from __future__ import annotations

import json
import re
from dataclasses import replace
from pathlib import Path
from time import monotonic
from urllib.parse import parse_qs, unquote, urlparse

from PySide6.QtCore import QEvent, QFile, QIODevice, QObject, Qt, QThreadPool, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices, QHideEvent, QKeyEvent, QResizeEvent, QShowEvent
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from travelcore.exceptions import ProjectError
from travelcore.maps import MapRenderResult
from travelcore.maps.groups import parse_group_key
from travelcore.media.gallery import SORT_FAVORITE, SORT_STATUSES, GalleryItem
from traveljournal.services.workers import MapRenderRunnable
from traveljournal.services.workspace import Workspace
from traveljournal.widgets.entry_links import (
    MAP_YOUTUBE_THUMB_SIZE,
    YouTubeThumbsRow,
)
from traveljournal.widgets.map_timeline import COVER_FOCUS_ZOOM, MapTimelineStrip
from traveljournal.widgets.media_inspector import MediaInspectorWindow
from traveljournal.widgets.thumb_zoom import ThumbZoomSlider, clamp_thumb_zoom

try:
    from PySide6.QtWebChannel import QWebChannel
    from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineSettings
    from PySide6.QtWebEngineWidgets import QWebEngineView
except ImportError:  # pragma: no cover - optional Qt WebEngine
    QWebChannel = None  # type: ignore[misc, assignment]
    QWebEngineView = None  # type: ignore[misc, assignment]
    QWebEngineSettings = None  # type: ignore[misc, assignment]
    QWebEnginePage = None  # type: ignore[misc, assignment]

_EXPAND_CONSOLE_PREFIX = "traveljournal:expand:"
_MEDIA_CONSOLE_PREFIX = "traveljournal:media:"
_SORT_CONSOLE_PREFIX = "traveljournal:sort:"
_PLACE_CONSOLE_PREFIX = "traveljournal:place:"
_PLACE_CANCEL_PREFIX = "traveljournal:place-cancel"
_SORT_STATUSES = frozenset({"favorite", "reserve", "rejected"})
_PLACE_COORDS = re.compile(r"(-?\d+(?:\.\d+)?):(-?\d+(?:\.\d+)?)")


def parse_map_expand_console(message: str) -> str | None:
    """Return the group key from a ``traveljournal:expand:…`` console line."""

    text = message.strip()
    idx = text.find(_EXPAND_CONSOLE_PREFIX)
    if idx < 0:
        return None
    key = text[idx + len(_EXPAND_CONSOLE_PREFIX) :].strip()
    return key or None


def parse_map_place_console(message: str) -> tuple[float, float] | None:
    """Return lat/lng from a ``traveljournal:place:lat:lng`` console line."""

    text = message.strip()
    idx = text.find(_PLACE_CONSOLE_PREFIX)
    if idx < 0:
        return None
    rest = text[idx + len(_PLACE_CONSOLE_PREFIX) :].strip()
    match = _PLACE_COORDS.fullmatch(rest)
    if match is None:
        return None
    return float(match.group(1)), float(match.group(2))


def parse_map_place_cancel_console(message: str) -> bool:
    return _PLACE_CANCEL_PREFIX in message.strip()


def parse_map_media_console(message: str) -> int | None:
    """Return the source file id from a ``traveljournal:media:…`` console line."""

    text = message.strip()
    idx = text.find(_MEDIA_CONSOLE_PREFIX)
    if idx < 0:
        return None
    raw = text[idx + len(_MEDIA_CONSOLE_PREFIX) :].strip()
    try:
        value = int(raw)
    except ValueError:
        return None
    return value if value > 0 else None


def parse_map_sort_console(message: str) -> tuple[int, str] | None:
    """Return source id and status from ``traveljournal:sort:id:status``."""

    text = message.strip()
    idx = text.find(_SORT_CONSOLE_PREFIX)
    if idx < 0:
        return None
    rest = text[idx + len(_SORT_CONSOLE_PREFIX) :]
    raw_id, sep, status = rest.partition(":")
    if not sep:
        return None
    try:
        source_id = int(raw_id)
    except ValueError:
        return None
    if source_id <= 0 or status not in _SORT_STATUSES and status != "":
        return None
    return source_id, status


def parse_map_sort_url(url: str) -> tuple[int, str] | None:
    """Return source id and status from a sort-bridge URL, else None."""

    parsed = urlparse(url)
    if parsed.scheme == "traveljournal" and parsed.netloc == "sort":
        query = parse_qs(parsed.query)
    elif parsed.scheme in {"http", "https"} and parsed.netloc == "traveljournal.local":
        path = parsed.path.rstrip("/") or "/"
        if path != "/sort":
            return None
        query = parse_qs(parsed.query)
    else:
        return None
    ids = query.get("id") or []
    if not ids:
        return None
    try:
        source_id = int(unquote(ids[0]))
    except ValueError:
        return None
    status = unquote((query.get("status") or [""])[0])
    if source_id <= 0 or status not in _SORT_STATUSES and status != "":
        return None
    return source_id, status


def parse_map_bridge_url(url: str) -> str | None:
    """Return the group key from an expand URL, else None."""

    parsed = urlparse(url)
    if parsed.scheme == "traveljournal" and parsed.netloc == "expand":
        values = parse_qs(parsed.query).get("key") or []
    elif parsed.scheme in {"http", "https"} and parsed.netloc == "traveljournal.local":
        path = parsed.path.rstrip("/") or "/"
        if path != "/expand":
            return None
        values = parse_qs(parsed.query).get("key") or []
    else:
        return None
    if not values:
        return None
    return unquote(values[0])


def parse_map_media_url(url: str) -> int | None:
    """Return the source file id from a media-bridge URL, else None."""

    parsed = urlparse(url)
    if parsed.scheme == "traveljournal" and parsed.netloc == "media":
        values = parse_qs(parsed.query).get("id") or []
    elif parsed.scheme in {"http", "https"} and parsed.netloc == "traveljournal.local":
        path = parsed.path.rstrip("/") or "/"
        if path != "/media":
            return None
        values = parse_qs(parsed.query).get("id") or []
    else:
        return None
    if not values:
        return None
    try:
        value = int(unquote(values[0]))
    except ValueError:
        return None
    return value if value > 0 else None


MAP_PAGE_SETUP_JS = """
(function() {
  function findMap() {
    if (!window.L || !L.Map) {
      return null;
    }
    for (var name in window) {
      try {
        if (window[name] instanceof L.Map) {
          return window[name];
        }
      } catch (err) {}
    }
    return null;
  }
  function expandKey(key) {
    if (!key) {
      return;
    }
    var now = Date.now();
    if (key === window._tjExpandKey && now - (window._tjExpandAt || 0) < 250) {
      return;
    }
    window._tjExpandKey = key;
    window._tjExpandAt = now;
    if (window.tjBridge && window.tjBridge.expand) {
      window.tjBridge.expand(key);
    }
    console.warn('traveljournal:expand:' + key);
  }
  window.traveljournalExpand = expandKey;
  function coverNode(event) {
    var target = event.target;
    if (!target || !target.closest) {
      return null;
    }
    var node = target.closest('.tj-cover[data-group-key]');
    if (node) {
      return node;
    }
    var icon = target.closest('.tj-cover-icon');
    return icon ? icon.querySelector('[data-group-key]') : null;
  }
    if (!window._tjPointerBound) {
    window._tjPointerBound = true;
    var press = null;
    document.addEventListener('pointerdown', function(event) {
      if (window._tjPlaceMode) {
        return;
      }
      if (event.button !== 0) {
        return;
      }
      var node = coverNode(event);
      if (!node) {
        return;
      }
      press = {
        x: event.clientX,
        y: event.clientY,
        key: node.getAttribute('data-group-key')
      };
      var map = findMap();
      if (map && map.dragging) {
        map.dragging.disable();
      }
    }, true);
    document.addEventListener('pointerup', function(event) {
      var map = findMap();
      if (map && map.dragging) {
        map.dragging.enable();
      }
      if (!press) {
        return;
      }
      var dx = Math.abs(event.clientX - press.x);
      var dy = Math.abs(event.clientY - press.y);
      var key = press.key;
      press = null;
      if (dx > 10 || dy > 10) {
        return;
      }
      event.preventDefault();
      event.stopPropagation();
      expandKey(key);
    }, true);
  }
  function wrapFocus() {
    var current = window.traveljournalFocusCover;
    if (current && current._tjWrap) {
      return;
    }
    var orig = current;
    var wrapped = function(lat, lon, key, offsetY) {
      window.traveljournalKeepFocus = true;
      var map = findMap();
      var zoom = map ? map.getZoom() : null;
      if (typeof orig === 'function') {
        orig(lat, lon, key, offsetY);
      }
      if (!map || typeof lat !== 'number' || typeof lon !== 'number' || zoom === null) {
        return;
      }
      if (map.stop) {
        map.stop();
      }
      map.setView(L.latLng(lat, lon), zoom, {
        animate: true,
        pan: {animate: true},
        zoom: {animate: false}
      });
    };
    wrapped._tjWrap = true;
    window.traveljournalFocusCover = wrapped;
  }
  var wrapTries = 0;
  function retryWrap() {
    wrapFocus();
    wrapTries += 1;
    if (wrapTries < 40) {
      setTimeout(retryWrap, 200);
    }
  }
  retryWrap();
  window.traveljournalSetPlaceMode = function(on) {
    window._tjPlaceMode = !!on;
    var map = findMap();
    var root = map && map.getContainer ? map.getContainer() : document.querySelector('.leaflet-container');
    if (root) {
      if (on) {
        root.classList.add('tj-place-mode');
        root.style.cursor = 'crosshair';
      } else {
        root.classList.remove('tj-place-mode');
        root.style.cursor = '';
      }
    }
    if (!document.getElementById('tj-place-cursor-style')) {
      var style = document.createElement('style');
      style.id = 'tj-place-cursor-style';
      style.textContent = (
        '.leaflet-container.tj-place-mode, .leaflet-container.tj-place-mode *'
        + ' { cursor: crosshair !important; }'
      );
      document.head.appendChild(style);
    }
    if (on && map && map.getCenter) {
      var placed = map.getCenter();
      window._tjSavedPlaceView = [placed.lat, placed.lng, map.getZoom()];
    }
  };
  window.traveljournalCaptureView = function() {
    var map = findMap();
    if (map && map.getCenter) {
      var center = map.getCenter();
      return [center.lat, center.lng, map.getZoom()];
    }
    return window._tjSavedPlaceView || null;
  };
  window.traveljournalRestoreView = function(lat, lon, zoom) {
    window.traveljournalKeepFocus = true;
    var map = findMap();
    if (!map) {
      return;
    }
    if (map.stop) {
      map.stop();
    }
    map.setView(L.latLng(lat, lon), zoom, {animate: false});
  };
  function bindPlace() {
    var map = findMap();
    if (!map || map._tjPlaceBound) {
      return !!map;
    }
    map._tjPlaceBound = true;
    map.on('moveend', function() {
      if (!window._tjPlaceMode) {
        return;
      }
      var moved = map.getCenter();
      window._tjSavedPlaceView = [moved.lat, moved.lng, map.getZoom()];
    });
    map.on('click', function(event) {
      if (!window._tjPlaceMode || !event || !event.latlng) {
        return;
      }
      var lat = event.latlng.lat;
      var lng = event.latlng.lng;
      if (window.tjBridge && window.tjBridge.place) {
        window.tjBridge.place(lat, lng);
      }
      console.warn('traveljournal:place:' + lat + ':' + lng);
    });
    return true;
  }
  document.addEventListener('keydown', function(event) {
    if (event.key !== 'Escape' || !window._tjPlaceMode) {
      return;
    }
    if (window.tjBridge && window.tjBridge.cancelPlace) {
      window.tjBridge.cancelPlace();
    }
    console.warn('traveljournal:place-cancel');
  }, true);
  var placeTries = 0;
  function retryPlace() {
    if (bindPlace() || placeTries >= 40) {
      return;
    }
    placeTries += 1;
    setTimeout(retryPlace, 200);
  }
  retryPlace();
  window.traveljournalInvalidateSize = function() {
    var map = findMap();
    if (!map) {
      return;
    }
    try {
      map.invalidateSize({animate: false});
      if (window.traveljournalDrawStayLinks) {
        window.traveljournalDrawStayLinks();
      }
    } catch (err) {}
  };
  window.traveljournalFitOverviewNow = function() {
    window.traveljournalKeepFocus = false;
    if (window.traveljournalFitOverview) {
      window.traveljournalFitOverview();
      return;
    }
    window.traveljournalInvalidateSize();
  };
})();
"""

_INVALIDATE_JS = "if (window.traveljournalInvalidateSize) traveljournalInvalidateSize();"
_CAPTURE_VIEW_JS = "window.traveljournalCaptureView ? traveljournalCaptureView() : null;"
_KEEP_FOCUS_JS = "window.traveljournalKeepFocus = true;"


def parse_map_view(value: object) -> tuple[float, float, float] | None:
    """Parse Leaflet center/zoom from a WebEngine ``runJavaScript`` result."""

    if isinstance(value, dict):
        try:
            lat = float(value["lat"])
            lon = float(value.get("lng", value.get("lon")))
            zoom = float(value["zoom"])
        except (KeyError, TypeError, ValueError):
            return None
        return lat, lon, zoom
    if isinstance(value, (list, tuple)) and len(value) >= 3:
        try:
            return float(value[0]), float(value[1]), float(value[2])
        except (TypeError, ValueError):
            return None
    return None


def restore_map_view_js(lat: float, lon: float, zoom: float) -> str:
    """Leaflet ``setView`` that also blocks Folium's overview ``fitBounds``."""

    return (
        "if (window.traveljournalRestoreView) "
        f"traveljournalRestoreView({lat:.10f}, {lon:.10f}, {zoom:.6f}); "
        "else { window.traveljournalKeepFocus = true; }"
    )


def mark_cover_js(group_key: str) -> str:
    payload = json.dumps(group_key, ensure_ascii=True)
    return (
        "if (window.traveljournalMarkCover) traveljournalMarkCover(" + payload + ");"
    )


_FIT_OVERVIEW_JS = """
(function() {
  function run() {
    if (window.traveljournalFitOverviewNow) {
      window.traveljournalFitOverviewNow();
      return true;
    }
    if (window.traveljournalFitOverview) {
      window.traveljournalKeepFocus = false;
      window.traveljournalFitOverview();
      return true;
    }
    if (window.traveljournalInvalidateSize) {
      window.traveljournalInvalidateSize();
    }
    return false;
  }
  if (run()) {
    return;
  }
  var n = 0;
  var timer = setInterval(function() {
    n += 1;
    if (run() || n > 40) {
      clearInterval(timer);
    }
  }, 100);
})();
"""


def publish_map_display(html_path: Path, seq: int) -> Path:
    """Copy ``map.html`` to a unique name so WebEngine cannot reuse a stale document."""

    dest = html_path.with_name(f"map-{int(seq)}.html")
    dest.write_bytes(html_path.read_bytes())
    target = dest.resolve()
    for old in html_path.parent.glob("map-*.html"):
        try:
            if old.resolve() != target:
                old.unlink()
        except OSError:
            continue
    return dest


class MapJsBridge(QObject):
    expand_requested = Signal(str)
    media_requested = Signal(int)
    sort_status_requested = Signal(int, str)
    section_closed = Signal()
    reserve_changed = Signal(bool)
    map_settings_changed = Signal(bool, bool, bool, bool)
    place_requested = Signal(float, float)
    place_cancelled = Signal()

    @Slot(str)
    def expand(self, group_key: str) -> None:
        if group_key:
            self.expand_requested.emit(group_key)

    @Slot(int)
    def openMedia(self, source_file_id: int) -> None:
        if source_file_id:
            self.media_requested.emit(int(source_file_id))

    @Slot(int, str)
    def setSortStatus(self, source_file_id: int, status: str) -> None:
        if source_file_id:
            self.sort_status_requested.emit(int(source_file_id), status or "")

    @Slot()
    def sectionClosed(self) -> None:
        self.section_closed.emit()

    @Slot(bool)
    def setShowReserve(self, show: bool) -> None:
        self.reserve_changed.emit(bool(show))

    @Slot(bool, bool, bool, bool)
    def saveMapSettings(
        self, photo_cones: bool, show_reserve: bool, sat_labels: bool, sat_streets: bool
    ) -> None:
        self.map_settings_changed.emit(
            bool(photo_cones), bool(show_reserve), bool(sat_labels), bool(sat_streets)
        )

    @Slot(float, float)
    def place(self, lat: float, lng: float) -> None:
        self.place_requested.emit(float(lat), float(lng))

    @Slot()
    def cancelPlace(self) -> None:
        self.place_cancelled.emit()


def _map_flags_bootstrap_js(workspace: Workspace) -> str:
    if workspace.current is None:
        return ""
    cones = "true" if workspace.map_show_photo_cones() else "false"
    reserve = "true" if workspace.map_show_reserve() else "false"
    sat_labels = "true" if workspace.map_show_sat_labels() else "false"
    sat_streets = "true" if workspace.map_show_sat_streets() else "false"
    zoom = clamp_thumb_zoom(workspace.map_thumb_zoom())
    return (
        f"window.traveljournalMapFlags={{cones:{cones},reserve:{reserve},"
        f"satLabels:{sat_labels},satStreets:{sat_streets}}};"
        f"window.traveljournalThumbZoom={zoom};"
        f"if(window.traveljournalApplyStoredMapFlags){{"
        f"window.traveljournalApplyStoredMapFlags({cones},{reserve},{sat_labels},{sat_streets});}}"
        f"if(window.traveljournalSetThumbZoom){{window.traveljournalSetThumbZoom({zoom});}}"
    )


def _webchannel_bootstrap_js() -> str:
    qfile = QFile(":/qtwebchannel/qwebchannel.js")
    if not qfile.open(QIODevice.OpenModeFlag.ReadOnly | QIODevice.OpenModeFlag.Text):
        return ""
    source = bytes(qfile.readAll()).decode("utf-8")
    qfile.close()
    return (
        source
        + """
if (typeof qt !== 'undefined' && typeof QWebChannel !== 'undefined') {
  new QWebChannel(qt.webChannelTransport, function(channel) {
    window.tjBridge = channel.objects.tjBridge;
    if (window.traveljournalShowReserve && window.tjBridge.setShowReserve) {
      window.tjBridge.setShowReserve(!!window.traveljournalShowReserve());
    }
  });
}
"""
    )


if QWebEnginePage is not None:

    class MapEnginePage(QWebEnginePage):
        expand_requested = Signal(str)
        media_requested = Signal(int)
        sort_status_requested = Signal(int, str)
        place_requested = Signal(float, float)
        place_cancelled = Signal()

        def acceptNavigationRequest(self, url, nav_type, is_main_frame):  # type: ignore[no-untyped-def]
            key = parse_map_bridge_url(url.toString())
            if key is not None:
                self.expand_requested.emit(key)
                return False
            media_id = parse_map_media_url(url.toString())
            if media_id is not None:
                self.media_requested.emit(media_id)
                return False
            sort_hit = parse_map_sort_url(url.toString())
            if sort_hit is not None:
                self.sort_status_requested.emit(sort_hit[0], sort_hit[1])
                return False
            if is_main_frame:
                parsed = urlparse(url.toString())
                if parsed.scheme in {"http", "https"}:
                    QDesktopServices.openUrl(url)
                    return False
            return super().acceptNavigationRequest(url, nav_type, is_main_frame)

        def javaScriptConsoleMessage(self, level, message, lineNumber, sourceID):  # type: ignore[no-untyped-def]
            if parse_map_place_cancel_console(message):
                self.place_cancelled.emit()
                return
            placed = parse_map_place_console(message)
            if placed is not None:
                self.place_requested.emit(placed[0], placed[1])
                return
            key = parse_map_expand_console(message)
            if key is not None:
                self.expand_requested.emit(key)
                return
            media_id = parse_map_media_console(message)
            if media_id is not None:
                self.media_requested.emit(media_id)
                return
            sort_hit = parse_map_sort_console(message)
            if sort_hit is not None:
                self.sort_status_requested.emit(sort_hit[0], sort_hit[1])
                return
            super().javaScriptConsoleMessage(level, message, lineNumber, sourceID)

else:  # pragma: no cover
    MapEnginePage = None  # type: ignore[misc, assignment]


class MapView(QWidget):
    status_message = Signal(str)
    open_in_timeline = Signal(str)
    rating_changed = Signal(object)
    insert_section = Signal(object)

    def __init__(self, workspace: Workspace, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.workspace = workspace
        self._web: QWebEngineView | None = None
        self._bridge: MapJsBridge | None = None
        self._channel: object | None = None
        self._pool = QThreadPool.globalInstance()
        self._generation = 0
        self._preparing = False
        self._shown_html: Path | None = None
        self._desired_seq = 0
        self._loaded_seq = 0
        self._pending_url: QUrl | None = None
        self._display_html: Path | None = None
        self._pending_result: MapRenderResult | None = None
        self._load_token = 0
        self._map_focus_armed = False
        self._fit_overview_on_load = False
        self._last_expand_key = ""
        self._last_expand_at = 0.0
        self._last_media_id = 0
        self._last_media_at = 0.0
        self._detail_items: list[GalleryItem] = []
        self._detail_group_key = ""
        self._pending_focus = ""
        self._requested_focus = ""
        self._restore_view: tuple[float, float, float] | None = None
        self._place_view: tuple[float, float, float] | None = None
        self._placed_strip_key = ""
        self._placing_key = ""
        self._placing_move = False
        self._pending_detail_key = ""
        self._pending_detail_media = 0
        self._notes_group_key = ""
        self._notes_title = ""
        self._notes_baseline = ""
        self._notes_loading = False
        self._invalidate_timer = QTimer(self)
        self._invalidate_timer.setSingleShot(True)
        self._invalidate_timer.setInterval(80)
        self._invalidate_timer.timeout.connect(self._invalidate_map_size)

        root = QVBoxLayout(self)
        root.setContentsMargins(32, 28, 32, 28)
        root.setSpacing(12)

        title = QLabel("Karte")
        title.setObjectName("pageTitle")
        self._subtitle = QLabel(
            "Titelbilder der Tage, Transfers und Aufenthalte. "
            "Einfachklick in der Leiste zentriert, Doppelklick öffnet den Eintrag in der Timeline. "
            "Rechtsklick auf eine Abschnittskarte: Platzieren, Verschieben oder Zentrieren."
        )
        self._subtitle.setObjectName("pageSubtitle")
        self._subtitle.setWordWrap(True)
        root.addWidget(title)
        root.addWidget(self._subtitle)

        toolbar = QHBoxLayout()
        refresh = QPushButton("Karte aktualisieren")
        refresh.clicked.connect(self._force_refresh)
        self._thumb_zoom = ThumbZoomSlider(self, value=self.workspace.map_thumb_zoom())
        self._thumb_zoom.zoom_changed.connect(self._on_thumb_zoom)
        toolbar.addWidget(refresh)
        toolbar.addSpacing(16)
        toolbar.addWidget(self._thumb_zoom)
        toolbar.addStretch(1)
        root.addLayout(toolbar)

        self._stack = QStackedWidget()
        self._message = QLabel("Bitte ein Projekt öffnen.")
        self._message.setObjectName("pageSubtitle")
        self._message.setWordWrap(True)
        self._stack.addWidget(self._message)

        self._side = QWidget()
        self._side.setObjectName("mapEntrySide")
        self._side.setMinimumWidth(260)
        self._side.setMaximumWidth(380)
        self._side.setFixedWidth(300)
        side_layout = QVBoxLayout(self._side)
        side_layout.setContentsMargins(0, 0, 0, 0)
        side_layout.setSpacing(8)
        notes_label = QLabel("Tagebucheintrag")
        notes_label.setObjectName("pageSubtitle")
        self._notes_edit = QPlainTextEdit()
        self._notes_edit.setObjectName("mapNotesEdit")
        self._notes_edit.setPlaceholderText("Tagebucheintrag der fokussierten Abschnittskarte")
        self._notes_edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._notes_edit.textChanged.connect(self._on_notes_changed)
        self._notes_actions = QWidget()
        self._notes_actions.setObjectName("mapNotesActions")
        actions_layout = QHBoxLayout(self._notes_actions)
        actions_layout.setContentsMargins(0, 0, 0, 0)
        actions_layout.setSpacing(6)
        self._notes_save = QPushButton("Speichern")
        self._notes_save.setObjectName("primary")
        self._notes_cancel = QPushButton("Abbrechen")
        self._notes_cancel.setObjectName("mapNotesCancel")
        self._notes_discard = QPushButton("Verwerfen")
        self._notes_discard.setObjectName("mapNotesDiscard")
        self._notes_save.clicked.connect(self._save_focused_notes)
        self._notes_cancel.clicked.connect(self._cancel_focused_notes)
        self._notes_discard.clicked.connect(self._discard_focused_notes)
        for button in (self._notes_save, self._notes_cancel, self._notes_discard):
            button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            actions_layout.addWidget(button)
        self._notes_actions.hide()
        self._map_frame = QWidget()
        self._map_frame.setObjectName("mapFrame")
        self._map_grid = QGridLayout(self._map_frame)
        self._map_grid.setContentsMargins(0, 0, 0, 0)
        self._map_grid.setSpacing(0)
        self._youtube = YouTubeThumbsRow(
            self._map_frame,
            vertical=True,
            thumb_size=MAP_YOUTUBE_THUMB_SIZE,
        )
        self._youtube.setObjectName("mapYoutubeOverlay")
        self._youtube.set_urls(())
        self._map_grid.addWidget(
            self._youtube,
            0,
            0,
            Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignRight,
        )
        side_layout.addWidget(notes_label)
        side_layout.addWidget(self._notes_edit, 1)
        side_layout.addWidget(self._notes_actions)

        self._timeline = MapTimelineStrip()
        self._timeline.focus_changed.connect(self._on_timeline_focus)
        self._timeline.open_in_timeline.connect(self.open_in_timeline.emit)
        self._timeline.place_requested.connect(self._start_place_mode)
        self._timeline.zoom_requested.connect(self._zoom_to_cover)
        self._timeline.add_between.connect(self.insert_section.emit)
        self._web_host = QWidget()
        self._web_layout = QVBoxLayout(self._web_host)
        self._web_layout.setContentsMargins(0, 0, 0, 0)
        self._web_layout.setSpacing(6)
        self._map_row = QHBoxLayout()
        self._map_row.setContentsMargins(0, 0, 0, 0)
        self._map_row.setSpacing(12)
        self._map_row.addWidget(self._map_frame, 1)
        self._map_row.addWidget(self._side)
        self._web_layout.addLayout(self._map_row, 1)
        self._web_layout.addWidget(self._timeline)
        self._stack.addWidget(self._web_host)
        root.addWidget(self._stack, 1)

    def refresh(self, *, force: bool = False) -> None:
        self._show_cached_or_prepare(force=force)

    def focus_group(self, group_key: str) -> None:
        """Center the strip on ``group_key`` after the map is shown (from Timeline)."""

        self._requested_focus = group_key
        if (
            group_key
            and self.isVisible()
            and self._stack.currentWidget() is self._web_host
            and self._timeline.card(group_key) is not None
        ):
            self._apply_requested_focus()

    def focus_group_media(self, group_key: str, source_file_id: int) -> None:
        """Open the section detail and pan to the media after the map is shown."""

        self._requested_focus = group_key
        self._pending_detail_key = group_key
        self._pending_detail_media = int(source_file_id) if source_file_id else 0
        if (
            group_key
            and self.isVisible()
            and self._stack.currentWidget() is self._web_host
            and self._timeline.card(group_key) is not None
        ):
            self._apply_requested_focus()
            self._open_pending_detail()
            self._requested_focus = ""
            self._arm_map_focus()

    def prepare_in_background(self, *, force: bool = False) -> None:
        """Warm ``cache/map.html`` after import or project open. Does not block the GUI."""

        if self.workspace.current is None:
            return
        if not force and self.workspace.load_cached_map() is not None:
            return
        self._start_worker(force=force)

    def clear(self) -> None:
        self._generation += 1
        self._preparing = False
        self._shown_html = None
        self._desired_seq = 0
        self._loaded_seq = 0
        self._pending_url = None
        self._display_html = None
        self._pending_result = None
        self._map_focus_armed = False
        self._fit_overview_on_load = False
        self._detail_items = []
        self._detail_group_key = ""
        self._pending_focus = ""
        self._requested_focus = ""
        self._restore_view = None
        self._place_view = None
        self._placed_strip_key = ""
        self._placing_key = ""
        self._placing_move = False
        self._pending_detail_key = ""
        self._pending_detail_media = 0
        self._clear_entry_panel()
        self._timeline.set_cards(())
        self._timeline.setVisible(False)
        if self.workspace.current is None:
            self._show_message("Bitte ein Projekt öffnen.")
            return
        self._show_message("Index wird geladen…")

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802
        super().showEvent(event)
        pending = self._pending_result
        self._pending_result = None
        if pending is not None:
            self._apply_result(pending)
            return
        self._load_html_if_needed()
        self._schedule_invalidate()

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._schedule_invalidate()

    def hideEvent(self, event: QHideEvent) -> None:  # noqa: N802
        self._flush_notes_save()
        super().hideEvent(event)

    def _force_refresh(self) -> None:
        self._show_cached_or_prepare(force=True)

    def _show_cached_or_prepare(self, *, force: bool) -> None:
        if self.workspace.current is None:
            self._show_message("Bitte ein Projekt öffnen.")
            return
        if not force:
            cached = self.workspace.load_cached_map()
            if cached is not None:
                self._apply_result(cached)
                return
        self._show_busy("Karte wird vorbereitet…" if not force else "Karte wird aktualisiert…")
        self._start_worker(force=force)

    def _start_worker(self, *, force: bool) -> None:
        opened = self.workspace.current
        if opened is None:
            return
        if self._preparing and not force:
            return
        self._generation += 1
        generation = self._generation
        self._preparing = True
        worker = MapRenderRunnable(opened, force=force, host=self)
        directory = opened.directory
        worker.signals.finished.connect(lambda result: self._on_prepared(generation, directory, result))
        worker.signals.failed.connect(lambda message: self._on_prepare_failed(generation, message))
        self._pool.start(worker)

    def _on_prepared(self, generation: int, directory: Path, result: object) -> None:
        if generation != self._generation:
            return
        self._preparing = False
        current = self.workspace.current
        if current is None or current.directory != directory:
            return
        if not isinstance(result, MapRenderResult):
            return
        if not self.isVisible():
            self._pending_result = result
            return
        self._pending_result = None
        self._apply_result(result)

    def _on_prepare_failed(self, generation: int, message: str) -> None:
        if generation != self._generation:
            return
        self._preparing = False
        if not self.isVisible():
            return
        self._show_busy(message)
        self.status_message.emit(f"Karte: {message}")

    def _apply_result(self, result: MapRenderResult) -> None:
        self._subtitle.setText(result.summary_line())
        if result.empty or result.html_path is None:
            self._shown_html = None
            self._desired_seq = 0
            self._loaded_seq = 0
            self._pending_url = None
            self._display_html = None
            self._timeline.set_cards(())
            self._clear_entry_panel()
            self._show_message(result.summary_line())
            self.status_message.emit("Karte: keine GPS-Daten")
            return
        html_path = result.html_path.resolve()
        if QWebEngineView is None:
            self._shown_html = None
            self._desired_seq = 0
            self._show_message(f"Qt WebEngine ist nicht installiert. Die Karte liegt unter:\n{html_path}")
            return
        self._ensure_web()
        assert self._web is not None
        self._shown_html = html_path
        self._desired_seq = result.render_seq
        already_loaded = self._loaded_seq == result.render_seq and (
            self._stack.currentWidget() is self._web_host
        )
        self._stack.setCurrentWidget(self._web_host)
        if already_loaded:
            self._install_page_hooks()
            self._reload_timeline(arm_focus=not self._fit_overview_on_load)
            self._schedule_invalidate()
            if self._restore_view is not None:
                QTimer.singleShot(50, self._restore_placed_view)
                QTimer.singleShot(280, self._restore_placed_view)
                QTimer.singleShot(400, self._finish_restore_view)
            elif self._pending_detail_key:
                QTimer.singleShot(80, self._open_pending_detail)
        else:
            self._fit_overview_on_load = (
                not bool(self._requested_focus) and self._restore_view is None
            )
            self._map_focus_armed = False
            self._last_expand_key = ""
            self._detail_group_key = ""
            self._clear_entry_panel()
            self._reload_timeline(arm_focus=False)
            self._load_html_if_needed()
        self.status_message.emit(result.summary_line())

    def _ensure_web(self) -> None:
        if self._web is not None or QWebEngineView is None:
            return
        self._web = QWebEngineView(self._map_frame)
        self._map_grid.addWidget(self._web, 0, 0)
        self._youtube.raise_()
        if MapEnginePage is not None:
            page = MapEnginePage(self._web)
            page.expand_requested.connect(self._on_expand_group)
            page.media_requested.connect(self._on_open_media)
            page.sort_status_requested.connect(self._on_sort_status)
            page.place_requested.connect(self._on_map_place)
            page.place_cancelled.connect(self._cancel_place_mode)
            self._web.setPage(page)
            if QWebChannel is not None:
                self._bridge = MapJsBridge(page)
                self._bridge.expand_requested.connect(self._on_expand_group)
                self._bridge.media_requested.connect(self._on_open_media)
                self._bridge.sort_status_requested.connect(self._on_sort_status)
                self._bridge.section_closed.connect(self._on_section_closed)
                self._bridge.reserve_changed.connect(self._timeline.set_show_reserve)
                self._bridge.map_settings_changed.connect(self._on_map_settings_changed)
                self._bridge.place_requested.connect(self._on_map_place)
                self._bridge.place_cancelled.connect(self._cancel_place_mode)
                channel = QWebChannel(page)
                channel.registerObject("tjBridge", self._bridge)
                page.setWebChannel(channel)
                self._channel = channel
            self._web.loadFinished.connect(self._on_web_loaded)
        self._web.installEventFilter(self)
        settings = self._web.settings()
        if QWebEngineSettings is not None:
            settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)
            settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)

    def _on_web_loaded(self, ok: bool) -> None:
        if self._web is None:
            return
        pending = self._pending_url
        if pending is not None:
            self._pending_url = None
            self._web.setUrl(pending)
            return
        if not ok or self._shown_html is None or self._display_html is None:
            return
        local = self._web.url().toLocalFile()
        if not local:
            return
        try:
            loaded = Path(local).resolve()
        except OSError:
            loaded = Path(local)
        try:
            expected = self._display_html.resolve()
        except OSError:
            expected = self._display_html
        if loaded != expected:
            return
        self._loaded_seq = self._desired_seq
        self._install_page_hooks()
        self._schedule_invalidate()
        if self._restore_view is not None:
            QTimer.singleShot(50, self._restore_placed_view)
            QTimer.singleShot(280, self._restore_placed_view)
            QTimer.singleShot(400, self._finish_restore_view)
            return
        if self._requested_focus:
            QTimer.singleShot(50, self._apply_requested_focus)
            QTimer.singleShot(280, self._apply_requested_focus)
            QTimer.singleShot(400, self._finish_requested_focus)
            return
        if self._fit_overview_on_load:
            QTimer.singleShot(50, self._fit_map_overview)
            QTimer.singleShot(280, self._fit_map_overview)
            QTimer.singleShot(400, self._finish_overview_load)
            return
        QTimer.singleShot(0, self._arm_map_focus)

    def _install_page_hooks(self) -> None:
        if self._web is None:
            return
        if self._restore_view is not None:
            self._web.page().runJavaScript(_KEEP_FOCUS_JS)
        flags = _map_flags_bootstrap_js(self.workspace)
        if flags:
            self._web.page().runJavaScript(flags)
        script = _webchannel_bootstrap_js()
        if script:
            self._web.page().runJavaScript(script)
        self._web.page().runJavaScript(MAP_PAGE_SETUP_JS)
        if self._restore_view is not None:
            lat, lon, zoom = self._restore_view
            self._web.page().runJavaScript(restore_map_view_js(lat, lon, zoom))
        if self._placing_key:
            self._run_js("if (window.traveljournalSetPlaceMode) traveljournalSetPlaceMode(true);")
        self._apply_map_thumb_zoom()

    def _reload_timeline(self, *, arm_focus: bool) -> None:
        self._map_focus_armed = False
        self._flush_notes_save()
        self._notes_group_key = ""
        if self.workspace.current is None:
            self._timeline.set_cards(())
            self._timeline.setVisible(False)
            self._clear_entry_panel()
            return
        try:
            cards = self.workspace.map_timeline_cards()
        except Exception as exc:  # noqa: BLE001 - keep the map usable
            self.status_message.emit(f"Karte: Timeline {exc}")
            cards = ()
        self._timeline.set_show_reserve(self.workspace.map_show_reserve())
        self._timeline.set_cards(cards)
        self._timeline.setVisible(bool(cards))
        if not cards:
            self._clear_entry_panel()
        if self._placed_strip_key:
            key = self._placed_strip_key
            QTimer.singleShot(0, lambda k=key: self._highlight_placed_card(k))
        elif self._requested_focus:
            QTimer.singleShot(0, self._apply_requested_focus)
        elif arm_focus:
            QTimer.singleShot(0, self._arm_map_focus)

    def _load_html_if_needed(self) -> None:
        if self._web is None or self._shown_html is None:
            return
        if not self.isVisible() or self._stack.currentWidget() is not self._web_host:
            return
        if self._loaded_seq == self._desired_seq and self._pending_url is None:
            return
        self._load_token += 1
        token = self._load_token
        QTimer.singleShot(0, lambda: self._load_html(token))

    def _load_html(self, token: int) -> None:
        if token != self._load_token or self._web is None or self._shown_html is None:
            return
        if not self.isVisible():
            return
        try:
            display = publish_map_display(self._shown_html, self._desired_seq)
        except OSError:
            display = self._shown_html
        self._display_html = display
        self._pending_url = QUrl.fromLocalFile(str(display.resolve()))
        self._web.setUrl(QUrl("about:blank"))

    def _schedule_invalidate(self) -> None:
        if self._web is None or self._stack.currentWidget() is not self._web_host:
            return
        self._invalidate_timer.start()

    def _invalidate_map_size(self) -> None:
        self._run_js(_INVALIDATE_JS)

    def _fit_map_overview(self) -> None:
        if self._requested_focus or self._restore_view is not None:
            return
        self._pending_focus = ""
        self._run_js(_FIT_OVERVIEW_JS)

    def _arm_map_focus(self) -> None:
        self._map_focus_armed = True

    def _finish_overview_load(self) -> None:
        self._fit_overview_on_load = False
        self._arm_map_focus()

    def _apply_requested_focus(self) -> None:
        key = self._requested_focus
        if not key:
            return
        if self._timeline.card(key) is None:
            return
        self._map_focus_armed = True
        skip_pan = self._pending_detail_media > 0
        self._timeline.center_on(key, emit=not skip_pan)
        if skip_pan:
            self._load_entry_panel(key)
            return
        self._pending_focus = key
        self._apply_pending_focus()

    def _finish_requested_focus(self) -> None:
        self._apply_requested_focus()
        self._fit_overview_on_load = False
        self._arm_map_focus()
        self._open_pending_detail()
        if self._requested_focus and self._timeline.card(self._requested_focus) is not None:
            self._requested_focus = ""

    def _restore_placed_view(self) -> None:
        view = self._restore_view
        if view is None:
            return
        lat, lon, zoom = view
        self._run_js(restore_map_view_js(lat, lon, zoom))
        if self._placed_strip_key:
            self._run_js(mark_cover_js(self._placed_strip_key))

    def _finish_restore_view(self) -> None:
        self._restore_placed_view()
        key = self._placed_strip_key
        self._placed_strip_key = ""
        self._restore_view = None
        self._place_view = None
        self._fit_overview_on_load = False
        self._arm_map_focus()
        self._highlight_placed_card(key)
        if key:
            self._run_js(mark_cover_js(key))

    def _highlight_placed_card(self, group_key: str) -> None:
        if not group_key or self._timeline.card(group_key) is None:
            return
        self._timeline.center_on(group_key, emit=False)
        self._load_entry_panel(group_key)

    def _store_place_view(self, view: object) -> None:
        parsed = parse_map_view(view)
        if parsed is not None:
            self._place_view = parsed

    def _refresh_after_place(self, view: object) -> None:
        if not self._placed_strip_key:
            return
        self._restore_view = parse_map_view(view) or self._place_view
        self.refresh(force=True)

    def _on_thumb_zoom(self, percent: int) -> None:
        self.workspace.set_map_thumb_zoom(percent)
        self._apply_map_thumb_zoom()

    def _apply_map_thumb_zoom(self) -> None:
        zoom = clamp_thumb_zoom(self.workspace.map_thumb_zoom())
        self._run_js(
            f"window.traveljournalThumbZoom={zoom};"
            f"if(window.traveljournalSetThumbZoom){{window.traveljournalSetThumbZoom({zoom});}}"
        )

    def _run_js(self, script: str) -> None:
        if self._web is None or self._stack.currentWidget() is not self._web_host:
            return
        self._web.page().runJavaScript(script)

    def _on_map_settings_changed(
        self, photo_cones: bool, show_reserve: bool, sat_labels: bool, sat_streets: bool
    ) -> None:
        self.workspace.set_map_display_flags(
            photo_cones=photo_cones,
            show_reserve=show_reserve,
            sat_labels=sat_labels,
            sat_streets=sat_streets,
        )
        self._timeline.set_show_reserve(show_reserve)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
        if (
            self._placing_key
            and event.type() == QEvent.Type.KeyPress
            and isinstance(event, QKeyEvent)
            and event.key() == Qt.Key.Key_Escape
        ):
            self._cancel_place_mode()
            return True
        return super().eventFilter(watched, event)

    def _start_place_mode(self, group_key: str) -> None:
        kind, raw = parse_group_key(group_key)
        if kind != "section" or not isinstance(raw, int) or raw <= 0:
            return
        card = self._timeline.card(group_key)
        self._placing_key = group_key
        self._placing_move = card is not None and not card.needs_pin
        if self._web is not None:
            self._web.setCursor(Qt.CursorShape.CrossCursor)
            self._web.page().runJavaScript(_CAPTURE_VIEW_JS, self._store_place_view)
        self._run_js("if (window.traveljournalSetPlaceMode) traveljournalSetPlaceMode(true);")
        if self._placing_move:
            self.status_message.emit("Klick auf die Karte verschiebt den Ort. Esc bricht ab.")
        else:
            self.status_message.emit("Klick auf die Karte setzt den Ort. Esc bricht ab.")

    def _cancel_place_mode(self) -> None:
        was_placing = bool(self._placing_key)
        moving = self._placing_move
        self._placing_key = ""
        self._placing_move = False
        self._run_js("if (window.traveljournalSetPlaceMode) traveljournalSetPlaceMode(false);")
        if self._web is not None:
            self._web.unsetCursor()
        if was_placing:
            self.status_message.emit("Verschieben abgebrochen." if moving else "Platzieren abgebrochen.")

    def _on_map_place(self, latitude: float, longitude: float) -> None:
        key = self._placing_key
        moving = self._placing_move
        if not key:
            return
        kind, raw = parse_group_key(key)
        if kind != "section" or not isinstance(raw, int) or raw <= 0:
            self._cancel_place_mode()
            return
        try:
            self.workspace.set_section_pin(raw, latitude, longitude)
        except ProjectError as exc:
            QMessageBox.warning(self, "Karte", str(exc))
            return
        self._placing_key = ""
        self._placing_move = False
        self._run_js("if (window.traveljournalSetPlaceMode) traveljournalSetPlaceMode(false);")
        if self._web is not None:
            self._web.unsetCursor()
        self._requested_focus = ""
        self._fit_overview_on_load = False
        self._placed_strip_key = key
        if self._web is None or self._stack.currentWidget() is not self._web_host:
            self._restore_view = self._place_view
            self.refresh(force=True)
        else:
            self._web.page().runJavaScript(_CAPTURE_VIEW_JS, self._refresh_after_place)
        self.status_message.emit("Ort verschoben." if moving else "Ort dem Abschnitt zugeordnet.")

    def _zoom_to_cover(self, group_key: str) -> None:
        card = self._timeline.card(group_key)
        if card is None or card.latitude is None or card.longitude is None:
            return
        self._timeline.center_on(group_key, emit=False)
        payload = json.dumps(
            {
                "lat": card.latitude,
                "lon": card.longitude,
                "key": group_key,
                "zoom": COVER_FOCUS_ZOOM,
            },
            ensure_ascii=True,
        )
        self._run_js(
            "(function(p){if(window.traveljournalZoomToCover)"
            "traveljournalZoomToCover(p.lat,p.lon,p.key,p.zoom);})(" + payload + ");"
        )

    def _on_timeline_focus(self, group_key: str) -> None:
        previous = self._notes_group_key
        if not self._load_entry_panel(group_key):
            if previous:
                QTimer.singleShot(0, lambda key=previous: self._timeline.center_on(key, emit=False))
            return
        if not self._map_focus_armed:
            return
        if not group_key or group_key == self._last_expand_key:
            return
        self._pending_focus = group_key
        self._apply_pending_focus()

    def _clear_entry_panel(self) -> None:
        self._notes_group_key = ""
        self._notes_title = ""
        self._notes_baseline = ""
        self._notes_loading = True
        self._notes_edit.clear()
        self._notes_edit.setEnabled(False)
        self._notes_loading = False
        self._notes_actions.hide()
        self._youtube.set_urls(())

    def _load_entry_panel(self, group_key: str) -> bool:
        if group_key == self._notes_group_key:
            return True
        if self._notes_are_dirty() and not self._confirm_leave_notes():
            return False
        card = self._timeline.card(group_key) if group_key else None
        if card is None:
            self._clear_entry_panel()
            return True
        kind, _raw = parse_group_key(card.group_key)
        editable = kind in {"section", "day"}
        self._notes_group_key = card.group_key
        self._notes_title = card.stored_title
        self._notes_baseline = card.notes
        self._notes_loading = True
        self._notes_edit.setEnabled(editable)
        self._notes_edit.setPlainText(card.notes)
        if kind == "day":
            self._notes_edit.setPlaceholderText("Tagebucheintrag — aus importierten Texten vorbefüllt")
        elif kind == "section":
            self._notes_edit.setPlaceholderText("Tagebucheintrag für diesen Abschnitt")
        else:
            self._notes_edit.setPlaceholderText("Kein Tagebucheintrag für diesen Eintrag")
        self._notes_loading = False
        self._sync_notes_actions()
        self._youtube.set_urls(card.youtube_urls)
        return True

    def _notes_are_dirty(self) -> bool:
        return (
            bool(self._notes_group_key)
            and self._notes_edit.isEnabled()
            and not self._notes_loading
            and self._notes_edit.toPlainText() != self._notes_baseline
        )

    def _sync_notes_actions(self) -> None:
        self._notes_actions.setVisible(self._notes_are_dirty())

    def _on_notes_changed(self) -> None:
        if self._notes_loading:
            return
        self._sync_notes_actions()

    def _flush_notes_save(self) -> None:
        if self._notes_are_dirty():
            self._save_focused_notes()

    def _ask_dirty_notes(self) -> str:
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle("Tagebucheintrag")
        box.setText("Der Tagebucheintrag wurde geändert.")
        box.setInformativeText("Speichern, die Änderung verwerfen oder bei diesem Eintrag bleiben?")
        save = box.addButton("Speichern", QMessageBox.ButtonRole.AcceptRole)
        discard = box.addButton("Verwerfen", QMessageBox.ButtonRole.DestructiveRole)
        cancel = box.addButton("Abbrechen", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(save)
        box.setEscapeButton(cancel)
        box.exec()
        clicked = box.clickedButton()
        if clicked == save:
            return "save"
        if clicked == discard:
            return "discard"
        return "cancel"

    def _confirm_leave_notes(self) -> bool:
        choice = self._ask_dirty_notes()
        if choice == "save":
            self._save_focused_notes()
            return not self._notes_are_dirty()
        return choice == "discard"

    def _cancel_focused_notes(self) -> None:
        self._notes_loading = True
        self._notes_edit.setPlainText(self._notes_baseline)
        self._notes_loading = False
        self._sync_notes_actions()

    def _discard_focused_notes(self) -> None:
        self._notes_loading = True
        self._notes_edit.setPlainText("")
        self._notes_loading = False
        self._save_focused_notes()

    def _save_focused_notes(self) -> None:
        key = self._notes_group_key
        kind, raw_id = parse_group_key(key)
        if kind not in {"section", "day"} or not isinstance(raw_id, int):
            return
        notes = self._notes_edit.toPlainText()
        title = self._notes_title
        if self.workspace.current is not None:
            try:
                if kind == "section":
                    self.workspace.save_section_text(raw_id, title=title, notes=notes)
                else:
                    self.workspace.save_day_text(raw_id, title=title, notes=notes)
            except Exception as exc:  # noqa: BLE001 - keep the map usable
                self.status_message.emit(f"Karte: {exc}")
                self._sync_notes_actions()
                return
        self._timeline.update_card_notes(key, notes)
        self._notes_baseline = notes
        self._sync_notes_actions()

    def _apply_pending_focus(self) -> None:
        group_key = self._pending_focus
        if not group_key or self._web is None:
            return
        if self._stack.currentWidget() is not self._web_host:
            return
        if group_key == self._last_expand_key:
            return
        card = self._timeline.card(group_key)
        if card is None or card.latitude is None or card.longitude is None:
            return
        payload = json.dumps(
            {
                "lat": card.latitude,
                "lon": card.longitude,
                "key": group_key,
                "offsetY": 0,
            },
            ensure_ascii=True,
        )
        self._run_js(
            "(function(p){if(window.traveljournalFocusCover)"
            "traveljournalFocusCover(p.lat,p.lon,p.key,p.offsetY);})(" + payload + ");"
        )

    def _on_expand_group(self, group_key: str, *, focus_source_id: int = 0) -> None:
        if self._web is None or not group_key:
            return
        now = monotonic()
        same = group_key == self._last_expand_key and now - self._last_expand_at < 0.4
        if same and not focus_source_id:
            return
        if same and focus_source_id and group_key == self._detail_group_key:
            self._focus_detail_media(focus_source_id)
            return
        self._last_expand_key = group_key
        self._last_expand_at = now
        try:
            payload = self.workspace.map_group_detail(group_key)
            self._detail_group_key = group_key
            self._detail_items = []
        except Exception as exc:  # noqa: BLE001 - show load errors in the status bar
            self.status_message.emit(f"Karte: {exc}")
            return
        if focus_source_id:
            payload["focus_source_id"] = int(focus_source_id)
        encoded = json.dumps(payload, ensure_ascii=True)
        self._timeline.center_on(group_key, emit=not bool(focus_source_id))
        self._run_js(f"if (window.traveljournalShowDetail) traveljournalShowDetail({encoded});")
        if focus_source_id:
            QTimer.singleShot(80, lambda sid=focus_source_id: self._focus_detail_media(sid))
            QTimer.singleShot(280, lambda sid=focus_source_id: self._focus_detail_media(sid))

    def _open_pending_detail(self) -> None:
        key = self._pending_detail_key
        media_id = self._pending_detail_media
        if not key:
            return
        self._pending_detail_key = ""
        self._pending_detail_media = 0
        self._on_expand_group(key, focus_source_id=media_id)

    def _focus_detail_media(self, source_file_id: int) -> None:
        if not source_file_id:
            return
        self._run_js(
            f"if (window.traveljournalFocusMedia) traveljournalFocusMedia({int(source_file_id)});"
        )

    def _on_section_closed(self) -> None:
        self._detail_items = []
        self._detail_group_key = ""
        self._last_expand_key = ""
        self._schedule_invalidate()

    def _on_open_media(self, source_file_id: int) -> None:
        now = monotonic()
        if source_file_id == self._last_media_id and now - self._last_media_at < 0.4:
            return
        self._last_media_id = source_file_id
        self._last_media_at = now
        host = self.window()
        if host is not None:
            for inspector in host.findChildren(MediaInspectorWindow):
                if inspector.item().source_file_id == source_file_id:
                    inspector.raise_()
                    inspector.activateWindow()
                    return
        items = list(self._detail_items)
        if not items and self._detail_group_key:
            items = self.workspace.map_group_gallery_items(self._detail_group_key)
            self._detail_items = items
        current = next((item for item in items if item.source_file_id == source_file_id), None)
        if current is None:
            fallback = self.workspace.gallery_items_for_ids([source_file_id])
            if not fallback:
                self.status_message.emit("Karte: Medium nicht gefunden")
                return
            current = fallback[0]
            items = fallback
        window = MediaInspectorWindow(
            current,
            items=items or [current],
            workspace=self.workspace,
            parent=host,
        )
        window.rating_changed.connect(self._on_inspector_rating)
        window.park_changed.connect(self._on_inspector_park)
        window.show()
        window.raise_()
        window.activateWindow()

    def apply_media_rating(self, item: object) -> None:
        """Keep the open detail view in sync with ratings from Medien or Timeline."""

        if not isinstance(item, GalleryItem) or not self._detail_group_key:
            return
        self._detail_items = [
            item if existing.source_file_id == item.source_file_id else existing
            for existing in self._detail_items
        ]
        status = json.dumps(item.sort_status or "")
        source_id = int(item.source_file_id)
        self._run_js(f"if (window.traveljournalApplySort) traveljournalApplySort({source_id}, {status});")

    def _on_sort_status(self, source_file_id: int, status: str) -> None:
        next_status = status if status in SORT_STATUSES else None
        try:
            self.workspace.set_sort_status(source_file_id, next_status)
        except Exception as error:  # noqa: BLE001
            self.status_message.emit(f"Karte: {error}")
            return
        updated = self._rated_detail_item(source_file_id, next_status)
        if updated is not None:
            self.rating_changed.emit(updated)

    def _on_inspector_rating(self, item: object) -> None:
        if not isinstance(item, GalleryItem):
            return
        self._detail_items = [
            item if existing.source_file_id == item.source_file_id else existing
            for existing in self._detail_items
        ]
        self.rating_changed.emit(item)
        status = json.dumps(item.sort_status or "")
        source_id = int(item.source_file_id)
        self._run_js(f"if (window.traveljournalApplySort) traveljournalApplySort({source_id}, {status});")

    def _on_inspector_park(self, item: object) -> None:
        if not isinstance(item, GalleryItem):
            return
        self.refresh(force=True)
        self.rating_changed.emit(item)
        self.status_message.emit("Medium im Pool." if item.parked else "Medium zurückgeholt.")

    def _rated_detail_item(self, source_file_id: int, status: str | None) -> GalleryItem | None:
        current = next((item for item in self._detail_items if item.source_file_id == source_file_id), None)
        if current is None:
            found = self.workspace.gallery_items_for_ids([source_file_id])
            current = found[0] if found else None
        if current is None:
            return None
        updated = replace(current, sort_status=status, is_favorite=status == SORT_FAVORITE)
        self._detail_items = [
            updated if item.source_file_id == source_file_id else item for item in self._detail_items
        ]
        return updated

    def _show_busy(self, text: str) -> None:
        self.status_message.emit(text)
        if self._shown_html is None or self._web is None:
            self._show_message(text)
            return
        self._subtitle.setText(text)

    def _show_message(self, text: str) -> None:
        self._message.setText(text)
        self._stack.setCurrentWidget(self._message)
