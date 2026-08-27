"""Interactive project map. Original media files are never written."""

from __future__ import annotations

import json
from pathlib import Path
from time import monotonic
from urllib.parse import parse_qs, unquote, urlparse

from PySide6.QtCore import QFile, QIODevice, QObject, QThreadPool, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices, QResizeEvent, QShowEvent
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from travelcore.maps import MapRenderResult
from travelcore.media.gallery import GalleryItem
from traveljournal.services.workers import MapRenderRunnable
from traveljournal.services.workspace import Workspace
from traveljournal.widgets.entry_links import YouTubeThumbsRow
from traveljournal.widgets.map_timeline import MapTimelineStrip
from traveljournal.widgets.media_inspector import MediaInspectorWindow

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


def parse_map_expand_console(message: str) -> str | None:
    """Return the group key from a ``traveljournal:expand:…`` console line."""

    text = message.strip()
    idx = text.find(_EXPAND_CONSOLE_PREFIX)
    if idx < 0:
        return None
    key = text[idx + len(_EXPAND_CONSOLE_PREFIX) :].strip()
    return key or None


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
    section_closed = Signal()

    @Slot(str)
    def expand(self, group_key: str) -> None:
        if group_key:
            self.expand_requested.emit(group_key)

    @Slot(int)
    def openMedia(self, source_file_id: int) -> None:
        if source_file_id:
            self.media_requested.emit(int(source_file_id))

    @Slot()
    def sectionClosed(self) -> None:
        self.section_closed.emit()


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
  });
}
"""
    )


if QWebEnginePage is not None:

    class MapEnginePage(QWebEnginePage):
        expand_requested = Signal(str)
        media_requested = Signal(int)

        def acceptNavigationRequest(self, url, nav_type, is_main_frame):  # type: ignore[no-untyped-def]
            key = parse_map_bridge_url(url.toString())
            if key is not None:
                self.expand_requested.emit(key)
                return False
            media_id = parse_map_media_url(url.toString())
            if media_id is not None:
                self.media_requested.emit(media_id)
                return False
            if is_main_frame:
                parsed = urlparse(url.toString())
                if parsed.scheme in {"http", "https"}:
                    QDesktopServices.openUrl(url)
                    return False
            return super().acceptNavigationRequest(url, nav_type, is_main_frame)

        def javaScriptConsoleMessage(self, level, message, lineNumber, sourceID):  # type: ignore[no-untyped-def]
            key = parse_map_expand_console(message)
            if key is not None:
                self.expand_requested.emit(key)
                return
            media_id = parse_map_media_console(message)
            if media_id is not None:
                self.media_requested.emit(media_id)
                return
            super().javaScriptConsoleMessage(level, message, lineNumber, sourceID)

else:  # pragma: no cover
    MapEnginePage = None  # type: ignore[misc, assignment]


class MapView(QWidget):
    status_message = Signal(str)
    open_in_timeline = Signal(str)

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
            "Einfachklick in der Leiste zentriert, Doppelklick öffnet den Eintrag in der Timeline."
        )
        self._subtitle.setObjectName("pageSubtitle")
        self._subtitle.setWordWrap(True)
        root.addWidget(title)
        root.addWidget(self._subtitle)

        toolbar = QHBoxLayout()
        refresh = QPushButton("Karte aktualisieren")
        refresh.clicked.connect(self._force_refresh)
        toolbar.addWidget(refresh)
        toolbar.addStretch(1)
        root.addLayout(toolbar)

        self._stack = QStackedWidget()
        self._message = QLabel("Bitte ein Projekt öffnen.")
        self._message.setObjectName("pageSubtitle")
        self._message.setWordWrap(True)
        self._stack.addWidget(self._message)

        self._youtube = YouTubeThumbsRow()
        self._youtube.set_urls(())
        self._timeline = MapTimelineStrip()
        self._timeline.focus_changed.connect(self._on_timeline_focus)
        self._timeline.open_in_timeline.connect(self.open_in_timeline.emit)
        self._web_host = QWidget()
        self._web_layout = QVBoxLayout(self._web_host)
        self._web_layout.setContentsMargins(0, 0, 0, 0)
        self._web_layout.setSpacing(6)
        self._web_layout.addWidget(self._youtube)
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
        self._youtube.set_urls(())
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
        else:
            self._fit_overview_on_load = not bool(self._requested_focus)
            self._map_focus_armed = False
            self._last_expand_key = ""
            self._detail_group_key = ""
            self._youtube.set_urls(())
            self._reload_timeline(arm_focus=False)
            self._load_html_if_needed()
        self.status_message.emit(result.summary_line())

    def _ensure_web(self) -> None:
        if self._web is not None or QWebEngineView is None:
            return
        self._web = QWebEngineView(self._web_host)
        self._web_layout.insertWidget(0, self._web, 1)
        if MapEnginePage is not None:
            page = MapEnginePage(self._web)
            page.expand_requested.connect(self._on_expand_group)
            page.media_requested.connect(self._on_open_media)
            self._web.setPage(page)
            if QWebChannel is not None:
                self._bridge = MapJsBridge(page)
                self._bridge.expand_requested.connect(self._on_expand_group)
                self._bridge.media_requested.connect(self._on_open_media)
                self._bridge.section_closed.connect(self._on_section_closed)
                channel = QWebChannel(page)
                channel.registerObject("tjBridge", self._bridge)
                page.setWebChannel(channel)
                self._channel = channel
            self._web.loadFinished.connect(self._on_web_loaded)
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
        script = _webchannel_bootstrap_js()
        if script:
            self._web.page().runJavaScript(script)
        self._web.page().runJavaScript(MAP_PAGE_SETUP_JS)

    def _reload_timeline(self, *, arm_focus: bool) -> None:
        self._map_focus_armed = False
        if self.workspace.current is None:
            self._timeline.set_cards(())
            self._timeline.setVisible(False)
            return
        try:
            cards = self.workspace.map_timeline_cards()
        except Exception as exc:  # noqa: BLE001 - keep the map usable
            self.status_message.emit(f"Karte: Timeline {exc}")
            cards = ()
        self._timeline.set_cards(cards)
        self._timeline.setVisible(bool(cards))
        if self._requested_focus:
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
        if self._requested_focus:
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
        self._timeline.center_on(key)
        self._pending_focus = key
        self._apply_pending_focus()

    def _finish_requested_focus(self) -> None:
        self._apply_requested_focus()
        self._fit_overview_on_load = False
        self._arm_map_focus()
        if self._requested_focus and self._timeline.card(self._requested_focus) is not None:
            self._requested_focus = ""

    def _run_js(self, script: str) -> None:
        if self._web is None or self._stack.currentWidget() is not self._web_host:
            return
        self._web.page().runJavaScript(script)

    def _on_timeline_focus(self, group_key: str) -> None:
        if not self._map_focus_armed:
            return
        if not group_key or group_key == self._last_expand_key:
            return
        self._pending_focus = group_key
        self._apply_pending_focus()

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

    def _on_expand_group(self, group_key: str) -> None:
        if self._web is None or not group_key:
            return
        now = monotonic()
        if group_key == self._last_expand_key and now - self._last_expand_at < 0.4:
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
        encoded = json.dumps(payload, ensure_ascii=True)
        urls = payload.get("youtube_urls")
        youtube = [item for item in urls if isinstance(item, str)] if isinstance(urls, list) else []
        self._youtube.set_urls(youtube)
        self._timeline.center_on(group_key)
        self._run_js(f"if (window.traveljournalShowDetail) traveljournalShowDetail({encoded});")

    def _on_section_closed(self) -> None:
        self._detail_items = []
        self._detail_group_key = ""
        self._last_expand_key = ""
        self._youtube.set_urls(())
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
        window.show()
        window.raise_()
        window.activateWindow()

    def _show_busy(self, text: str) -> None:
        self.status_message.emit(text)
        if self._shown_html is None or self._web is None:
            self._show_message(text)
            return
        self._subtitle.setText(text)

    def _show_message(self, text: str) -> None:
        self._message.setText(text)
        self._stack.setCurrentWidget(self._message)
