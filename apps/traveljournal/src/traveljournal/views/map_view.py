"""Interactive project map. Original media files are never written."""

from __future__ import annotations

import json
from pathlib import Path
from time import monotonic
from urllib.parse import parse_qs, unquote, urlparse

from PySide6.QtCore import QFile, QIODevice, QObject, QThreadPool, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices
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
})();
"""


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
        self._last_expand_key = ""
        self._last_expand_at = 0.0
        self._last_media_id = 0
        self._last_media_at = 0.0
        self._detail_items: list[GalleryItem] = []
        self._pending_focus = ""

        root = QVBoxLayout(self)
        root.setContentsMargins(32, 28, 32, 28)
        root.setSpacing(12)

        title = QLabel("Karte")
        title.setObjectName("pageTitle")
        self._subtitle = QLabel(
            "Titelbilder der Reiseabschnitte und Resttage. "
            "Die Leiste unter der Karte folgt dem Reiseverlauf."
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
        self._timeline.fit_all_requested.connect(self._fit_overview)
        self._web_host = QWidget()
        self._web_layout = QVBoxLayout(self._web_host)
        self._web_layout.setContentsMargins(0, 0, 0, 0)
        self._web_layout.setSpacing(6)
        self._web_layout.addWidget(self._youtube)
        self._web_layout.addWidget(self._timeline)
        self._stack.addWidget(self._web_host)
        root.addWidget(self._stack, 1)

    def refresh(self) -> None:
        self._show_cached_or_prepare(force=False)

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
        self._detail_items = []
        self._pending_focus = ""
        self._youtube.set_urls(())
        self._timeline.set_cards(())
        self._timeline.setVisible(False)
        if self.workspace.current is None:
            self._show_message("Bitte ein Projekt öffnen.")
            return
        self._show_message("Index wird geladen…")

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
        self._show_message("Karte wird vorbereitet…" if not force else "Karte wird aktualisiert…")
        self.status_message.emit(self._message.text())
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
        worker = MapRenderRunnable(opened, force=force)
        directory = opened.directory
        worker.signals.finished.connect(
            lambda result: self._on_prepared(generation, directory, result)
        )
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
            return
        self._apply_result(result)

    def _on_prepare_failed(self, generation: int, message: str) -> None:
        if generation != self._generation:
            return
        self._preparing = False
        if not self.isVisible():
            return
        self._show_message(message)
        self.status_message.emit(f"Karte: {message}")

    def _apply_result(self, result: MapRenderResult) -> None:
        self._subtitle.setText(result.summary_line())
        if result.empty or result.html_path is None:
            self._shown_html = None
            self._timeline.set_cards(())
            self._show_message(result.summary_line())
            self.status_message.emit("Karte: keine GPS-Daten")
            return
        html_path = result.html_path.resolve()
        if QWebEngineView is None:
            self._shown_html = None
            self._show_message(f"Qt WebEngine ist nicht installiert. Die Karte liegt unter:\n{html_path}")
            return
        self._ensure_web()
        assert self._web is not None
        same_page = (
            self._shown_html is not None
            and self._shown_html == html_path
            and self._stack.currentWidget() is self._web_host
        )
        if not same_page or not result.from_cache:
            self._web.setUrl(QUrl.fromLocalFile(str(html_path)))
        else:
            self._install_page_hooks()
        self._shown_html = html_path
        self._stack.setCurrentWidget(self._web_host)
        self._reload_timeline()
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
        if not ok or self._web is None:
            return
        self._install_page_hooks()
        QTimer.singleShot(250, self._apply_pending_focus)

    def _install_page_hooks(self) -> None:
        if self._web is None:
            return
        script = _webchannel_bootstrap_js()
        if script:
            self._web.page().runJavaScript(script)
        self._web.page().runJavaScript(MAP_PAGE_SETUP_JS)

    def _reload_timeline(self) -> None:
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

    def _run_js(self, script: str) -> None:
        if self._web is None or self._stack.currentWidget() is not self._web_host:
            return
        self._web.page().runJavaScript(script)

    def _fit_overview(self) -> None:
        self._run_js("if (window.traveljournalFitOverview) traveljournalFitOverview();")

    def _on_timeline_focus(self, group_key: str) -> None:
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
            self._detail_items = self.workspace.map_group_gallery_items(group_key)
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
        self._last_expand_key = ""
        self._youtube.set_urls(())
        key = self._timeline.focused_key()
        if key:
            self._pending_focus = key
            self._apply_pending_focus()

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
        current = next((item for item in items if item.source_file_id == source_file_id), None)
        if current is None:
            fallback = [
                item
                for item in self.workspace.gallery_items()
                if item.source_file_id == source_file_id
            ]
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

    def _show_message(self, text: str) -> None:
        self._message.setText(text)
        self._stack.setCurrentWidget(self._message)
