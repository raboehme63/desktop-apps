"""GUI smoke test. Requires an offscreen Qt platform plugin."""

from __future__ import annotations

import os
from pathlib import Path


def test_main_window_starts() -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QScrollArea

    from traveljournal.ui.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    assert window.windowTitle() == "Reisetagebuch R1.0.0"
    assert window.stack.count() == 7
    titles = [action.text() for action in window.menuBar().actions()]
    assert "Projekt" in titles
    assert window._settings_action is not None
    assert not window._settings_action.isEnabled()
    headers = [
        window.import_view.table.horizontalHeaderItem(index).text()
        for index in range(window.import_view.table.columnCount())
    ]
    assert headers == ["Datei", "Typ", "Aufnahmezeit", "GPS", "Kamera / Pilot"]
    assert "matched" in window.import_view._stat_labels
    assert window.import_view._stat_labels["matched"].text() == "0"
    assert window.import_view._stat_labels["unlocated"].text() == "0"
    assert window.import_view._preview_image is not None
    assert "Mouseover" in window.import_view._preview_meta.text()
    assert window.project_view.name_label.text() == "–"
    assert not window.project_view.name_edit.isEnabled()
    assert window.project_view.load_progress.format() == "Bereit"
    assert window._load_progress.isHidden()
    assert not window.import_view.is_loading_index
    assert isinstance(window.timeline_view._scroll, QScrollArea)
    assert window.timeline_view._media_tabs.count() == 4
    assert window.timeline_view._media_tabs.tabText(0) == "Alle"
    assert window.timeline_view._media_tabs.tabText(1) == "Favoriten"
    _ = app


def test_app_window_title_includes_version() -> None:
    from traveljournal.__about__ import app_window_title

    assert app_window_title() == "Reisetagebuch R1.0.0"
    assert app_window_title("Alpen 2025") == "Reisetagebuch R1.0.0 - Alpen 2025"
    assert app_window_title("  ") == "Reisetagebuch R1.0.0"


def test_new_project_dialog_preview_and_values(tmp_path: Path) -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from travelcore.exceptions import ProjectError
    from traveljournal.views.project_view import NewProjectDialog

    app = QApplication.instance() or QApplication([])
    dialog = NewProjectDialog(initial_parent=tmp_path)
    assert dialog.dir_edit.text() == str(tmp_path)
    dialog.name_edit.setText("Italien: 2025")
    parent, name = dialog.values()
    assert name == "Italien: 2025"
    assert parent == tmp_path
    assert dialog.preview_label.text() == str(tmp_path / "Italien 2025")
    dialog.name_edit.setText("")
    try:
        dialog.values()
    except ProjectError as exc:
        assert "Projektnamen" in str(exc)
    else:
        raise AssertionError("expected ProjectError")
    _ = app


def test_format_local_datetime_uses_local_time_not_utc() -> None:
    from datetime import UTC, datetime

    from traveljournal.views.project_view import format_local_datetime

    utc = datetime(2026, 8, 26, 14, 49, 0, tzinfo=UTC)
    naive = datetime(2026, 8, 26, 14, 49, 0)
    expected = utc.astimezone().strftime("%Y-%m-%d %H:%M:%S")
    assert format_local_datetime(utc) == expected
    assert format_local_datetime(naive) == expected


def test_format_import_status() -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from traveljournal.views.import_view import format_import_status

    assert format_import_status(0, 0, "Verzeichnis wird durchsucht…") == "Verzeichnis wird durchsucht…"
    assert format_import_status(0, 12, "12 Dateien gefunden") == "12 Dateien gefunden"
    assert (
        format_import_status(3, 12, "Analysiere DSC_0123.jpg") == "Analysiere DSC_0123.jpg · 3 von 12 (25 %)"
    )
    assert format_import_status(2, 4, "", r"C:\fotos\flug.igc") == "flug.igc · 2 von 4 (50 %)"


def test_progress_bar_format_uses_qt_percent_placeholder() -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from traveljournal.views.import_view import progress_bar_format

    assert progress_bar_format("Analysiere spur.GPX") == "Analysiere spur.GPX  %v von %m (%p %)"
    assert "%%" not in progress_bar_format("Datei 100% fertig")


def test_file_preview_text_includes_heading_and_35mm() -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from datetime import UTC, datetime

    from travelcore.database.models import SourceFile
    from traveljournal.views.import_view import file_preview_text

    row = SourceFile(
        id=1,
        project_id=1,
        path=r"C:\media\foto.jpg",
        filename="foto.jpg",
        file_kind="photo",
        extension=".jpg",
        size_bytes=2048,
        imported_at=datetime(2025, 5, 15, 12, 0, tzinfo=UTC),
        status="ok",
        timezone_unknown=True,
        camera="Canon EOS R6",
        heading_degrees=123.5,
        heading_ref="T",
        focal_length_35mm=24.0,
    )
    text = file_preview_text(row, dhv_url="https://example.test/flight")
    assert "foto.jpg" in text
    assert "123.5" in text
    assert "geografisch Nord" in text
    assert "24" in text
    assert "Canon EOS R6" in text
    assert "https://example.test/flight" in text


def test_import_browse_start_uses_config_roots(tmp_path: Path) -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from traveljournal.views.import_view import import_browse_start

    current = tmp_path / "current"
    source = tmp_path / "source"
    projects = tmp_path / "projects"
    current.mkdir()
    source.mkdir()
    projects.mkdir()
    assert import_browse_start(str(current), source_root=str(source), projects_root=projects) == str(current)
    assert import_browse_start("", source_root=str(source), projects_root=projects) == str(source)
    assert import_browse_start("", source_root=None, projects_root=projects) == str(projects)
    assert import_browse_start("missing", source_root=None, projects_root=None) == ""


def test_youtube_links_dialog_add_and_delete() -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from traveljournal.widgets.entry_links import YouTubeLinksDialog

    app = QApplication.instance() or QApplication([])
    dialog = YouTubeLinksDialog(["https://youtu.be/abcdefghijk"])
    assert dialog.urls() == ["https://youtu.be/abcdefghijk"]
    dialog._remove_at(0)
    assert dialog.urls() == []
    dialog._url_edit.setText("https://www.youtube.com/watch?v=xyzxyzxyzxy")
    dialog._add_current()
    assert dialog.urls() == ["https://www.youtube.com/watch?v=xyzxyzxyzxy"]
    dialog._url_edit.setText("https://www.youtube.com/watch?v=xyzxyzxyzxy")
    dialog._add_current()
    assert dialog.urls() == ["https://www.youtube.com/watch?v=xyzxyzxyzxy"]
    _ = app


def test_gallery_rating_hotspots() -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QPoint, QRect
    from PySide6.QtWidgets import QApplication

    from traveljournal.widgets.gallery import hit_rating, rating_hotspots

    app = QApplication.instance() or QApplication([])
    cell = QRect(0, 0, 184, 214)
    spots = rating_hotspots(cell)
    assert set(spots) == {"favorite", "reserve", "rejected"}
    favorite = spots["favorite"]
    assert hit_rating(cell, favorite.center()) == "favorite"
    assert hit_rating(cell, QPoint(8, 8)) is None
    _ = app


def test_entry_widget_separates_tracks_from_media() -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from datetime import UTC, datetime
    from pathlib import Path

    from PySide6.QtWidgets import QApplication

    from travelcore.timeline.types import TimelineDay, TimelineEntry, TimelinePhoto
    from traveljournal.views.timeline_view import EntryWidget, split_media_and_tracks

    app = QApplication.instance() or QApplication([])
    photo = TimelinePhoto(
        source_file_id=1,
        filename="foto.jpg",
        path="foto.jpg",
        thumbnail_path=Path("."),
        captured_at=datetime(2025, 5, 15, 8, 0, tzinfo=UTC),
        used_in_journal=False,
        is_cover=False,
        is_favorite=False,
        gps_latitude=None,
        gps_longitude=None,
        file_kind="photo",
    )
    track = TimelinePhoto(
        source_file_id=2,
        filename="flug.igc",
        path="flug.igc",
        thumbnail_path=Path("."),
        captured_at=datetime(2025, 5, 15, 9, 0, tzinfo=UTC),
        used_in_journal=False,
        is_cover=False,
        is_favorite=False,
        gps_latitude=None,
        gps_longitude=None,
        file_kind="gps",
    )
    media, tracks = split_media_and_tracks((photo, track))
    assert [item.filename for item in media] == ["foto.jpg"]
    assert [item.filename for item in tracks] == ["flug.igc"]
    day = TimelineDay(
        id=1,
        day_index=0,
        date=photo.captured_at.date() if photo.captured_at is not None else None,
        title=None,
        notes=None,
        origin="auto",
        photos=(photo, track),
    )
    widget = EntryWidget(TimelineEntry(started_at=photo.captured_at, leftover_day=day))
    assert [item.filename for item in widget.gallery.items()] == ["foto.jpg"]
    assert [item.filename for item in widget.track_gallery.items()] == ["flug.igc"]
    assert widget._cover_thumb.isHidden()
    _ = app


def test_entry_widget_track_can_be_cover(tmp_path: Path) -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from datetime import UTC, datetime

    from jpeg_fixtures import write_plain_jpeg
    from PySide6.QtWidgets import QApplication

    from travelcore.timeline.types import TimelineDay, TimelineEntry, TimelinePhoto
    from traveljournal.views.timeline_view import EntryWidget
    from traveljournal.widgets.gallery import can_be_cover

    app = QApplication.instance() or QApplication([])
    thumb = write_plain_jpeg(tmp_path / "spur.jpg", size=(48, 48))
    stamp = datetime(2025, 5, 15, 8, 0, tzinfo=UTC)
    track = TimelinePhoto(
        source_file_id=2,
        filename="spur.gpx",
        path="spur.gpx",
        thumbnail_path=thumb,
        captured_at=stamp,
        used_in_journal=False,
        is_cover=False,
        is_favorite=False,
        gps_latitude=None,
        gps_longitude=None,
        file_kind="gps",
    )
    day = TimelineDay(
        id=1,
        day_index=0,
        date=stamp.date(),
        title="Bozen",
        notes=None,
        origin="auto",
        cover_source_file_id=2,
        photos=(track,),
    )
    widget = EntryWidget(TimelineEntry(started_at=stamp, leftover_day=day))
    items = widget.track_gallery.items()
    assert len(items) == 1
    assert can_be_cover(items[0])
    assert items[0].is_entry_cover
    assert widget.track_gallery._show_cover
    assert not widget._cover_thumb.isHidden()
    assert not widget._cover_thumb.pixmap().isNull()
    _ = app


def test_entry_widget_shows_cover_in_heading(tmp_path: Path) -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from datetime import UTC, datetime

    from jpeg_fixtures import write_plain_jpeg
    from PySide6.QtWidgets import QApplication

    from travelcore.timeline.types import TimelineDay, TimelineEntry, TimelinePhoto
    from traveljournal.views.timeline_view import EntryWidget

    app = QApplication.instance() or QApplication([])
    thumb = write_plain_jpeg(tmp_path / "cover.jpg", size=(48, 48))
    stamp = datetime(2025, 5, 15, 8, 0, tzinfo=UTC)
    photo = TimelinePhoto(
        source_file_id=1,
        filename="cover.jpg",
        path=str(thumb),
        thumbnail_path=thumb,
        captured_at=stamp,
        used_in_journal=False,
        is_cover=False,
        is_favorite=False,
        gps_latitude=None,
        gps_longitude=None,
        file_kind="photo",
    )
    day = TimelineDay(
        id=1,
        day_index=0,
        date=stamp.date(),
        title="Bozen",
        notes=None,
        origin="auto",
        cover_source_file_id=1,
        photos=(photo,),
    )
    widget = EntryWidget(TimelineEntry(started_at=stamp, leftover_day=day))
    assert not widget._cover_thumb.isHidden()
    assert not widget._cover_thumb.pixmap().isNull()
    _ = app


def test_entry_widget_media_tab_filters_favorites() -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from datetime import UTC, datetime

    from PySide6.QtWidgets import QApplication

    from travelcore.timeline.types import TimelineDay, TimelineEntry, TimelinePhoto
    from traveljournal.views.timeline_view import EntryWidget, media_tab_index

    app = QApplication.instance() or QApplication([])
    stamp = datetime(2025, 5, 15, 8, 0, tzinfo=UTC)
    normal = TimelinePhoto(
        source_file_id=1,
        filename="normal.jpg",
        path="normal.jpg",
        thumbnail_path=Path("."),
        captured_at=stamp,
        used_in_journal=False,
        is_cover=False,
        is_favorite=False,
        gps_latitude=None,
        gps_longitude=None,
        file_kind="photo",
    )
    favorite = TimelinePhoto(
        source_file_id=2,
        filename="fav.jpg",
        path="fav.jpg",
        thumbnail_path=Path("."),
        captured_at=stamp,
        used_in_journal=False,
        is_cover=False,
        is_favorite=True,
        gps_latitude=None,
        gps_longitude=None,
        file_kind="photo",
        sort_status="favorite",
    )
    day = TimelineDay(
        id=1,
        day_index=0,
        date=stamp.date(),
        title=None,
        notes=None,
        origin="auto",
        photos=(normal, favorite),
    )
    widget = EntryWidget(TimelineEntry(started_at=stamp, leftover_day=day))
    assert [item.filename for item in widget.gallery.items()] == ["normal.jpg", "fav.jpg"]
    widget.set_media_tab(media_tab_index("favorite"))
    assert [item.filename for item in widget.gallery.items()] == ["fav.jpg"]
    _ = app


def test_media_tabs_change_only_on_click() -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtGui import QWheelEvent
    from PySide6.QtWidgets import QApplication

    from traveljournal.views.timeline_view import ClickTabBar

    app = QApplication.instance() or QApplication([])
    bar = ClickTabBar()
    bar.addTab("Alle")
    bar.addTab("Favoriten")
    bar.setCurrentIndex(0)
    bar.resize(280, 32)
    bar.wheelEvent(
        QWheelEvent(
            QPointF(20, 10),
            QPointF(20, 10),
            QPoint(0, 0),
            QPoint(0, 120),
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
            Qt.ScrollPhase.NoScrollPhase,
            False,
        )
    )
    assert bar.currentIndex() == 0
    bar.setCurrentIndex(1)
    assert bar.currentIndex() == 1
    _ = app


def test_timeline_global_register_applies_to_all_days(tmp_path: Path, monkeypatch) -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from datetime import UTC, datetime

    from PySide6.QtWidgets import QApplication

    from travelcore.timeline.types import TimelineDay, TimelineEntry, TimelinePhoto
    from traveljournal.services import workspace as workspace_mod
    from traveljournal.services.workspace import Workspace
    from traveljournal.views.timeline_view import EntryWidget, TimelineView, media_tab_index

    monkeypatch.setattr(workspace_mod, "_UI_CONFIG_PATH", tmp_path / "config.json")
    app = QApplication.instance() or QApplication([])
    stamp = datetime(2025, 5, 15, 8, 0, tzinfo=UTC)
    photo = TimelinePhoto(
        source_file_id=1,
        filename="foto.jpg",
        path="foto.jpg",
        thumbnail_path=Path("."),
        captured_at=stamp,
        used_in_journal=False,
        is_cover=False,
        is_favorite=False,
        gps_latitude=None,
        gps_longitude=None,
        file_kind="photo",
    )
    day = TimelineDay(
        id=1,
        day_index=0,
        date=stamp.date(),
        title=None,
        notes=None,
        origin="auto",
        photos=(photo,),
    )
    workspace = Workspace()
    view = TimelineView(workspace)
    first = EntryWidget(TimelineEntry(started_at=stamp, leftover_day=day), parent=view)
    second = EntryWidget(TimelineEntry(started_at=stamp, leftover_day=day), parent=view)
    view._blocks = [first, second]
    view._propagate_media_tab(media_tab_index("reserve"), persist=True)
    assert view._media_tabs.currentIndex() == media_tab_index("reserve")
    assert first._media_tabs.currentIndex() == media_tab_index("reserve")
    assert second._media_tabs.currentIndex() == media_tab_index("reserve")
    assert workspace.timeline_media_tab() == "reserve"
    view.confirm_leave()
    assert workspace.timeline_media_tab() == "reserve"
    _ = app


def test_media_inspector_shows_original_and_ratings(tmp_path: Path) -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from jpeg_fixtures import write_plain_jpeg
    from PySide6.QtWidgets import QApplication

    from travelcore.media.gallery import GalleryItem
    from traveljournal.widgets.media_inspector import MediaInspectorWindow, load_media_pixmap

    app = QApplication.instance() or QApplication([])
    jpeg = write_plain_jpeg(tmp_path / "foto.jpg", size=(40, 30))
    item = GalleryItem(
        source_file_id=1,
        path=str(jpeg),
        filename="foto.jpg",
        extension=".jpg",
        captured_at=None,
        timezone_unknown=False,
        gps_latitude=None,
        gps_longitude=None,
        camera=None,
        is_favorite=False,
        used_in_journal=False,
        thumbnail_path=Path("."),
        sort_status=None,
    )
    window = MediaInspectorWindow(item)
    assert window.windowTitle() == "foto.jpg"
    assert window.extra_host.objectName() == "inspectorExtra"
    assert not window.extra_host.isVisible()
    assert set(window._rating_buttons) == {"favorite", "reserve", "rejected"}
    assert window._rotate_left.text() == "↺"
    pixmap = load_media_pixmap(item)
    assert not pixmap.isNull()
    assert pixmap.width() >= 40
    _ = app


def test_media_inspector_rotates_display_without_writing_original(tmp_path: Path) -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from jpeg_fixtures import write_plain_jpeg
    from PySide6.QtWidgets import QApplication

    from travelcore.media.gallery import GalleryItem
    from traveljournal.widgets.media_inspector import MediaInspectorWindow, load_media_pixmap

    app = QApplication.instance() or QApplication([])
    jpeg = write_plain_jpeg(tmp_path / "quer.jpg", size=(40, 20))
    original_mtime = jpeg.stat().st_mtime
    item = GalleryItem(
        source_file_id=1,
        path=str(jpeg),
        filename="quer.jpg",
        extension=".jpg",
        captured_at=None,
        timezone_unknown=False,
        gps_latitude=None,
        gps_longitude=None,
        camera=None,
        is_favorite=False,
        used_in_journal=False,
        thumbnail_path=Path("."),
        sort_status=None,
    )
    window = MediaInspectorWindow(item)
    fitted = load_media_pixmap(item)
    assert fitted.width() >= fitted.height()
    window._rotate(90)
    assert window.item().rotation_degrees == 90
    rotated = load_media_pixmap(window.item())
    assert rotated.height() >= rotated.width()
    assert jpeg.stat().st_mtime == original_mtime
    _ = app


def test_media_inspector_browses_section_sequence(tmp_path: Path) -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from jpeg_fixtures import write_plain_jpeg
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QKeyEvent
    from PySide6.QtWidgets import QApplication

    from travelcore.media.gallery import GalleryItem
    from traveljournal.widgets.media_inspector import MediaInspectorWindow

    app = QApplication.instance() or QApplication([])
    first_path = write_plain_jpeg(tmp_path / "eins.jpg", size=(40, 30))
    second_path = write_plain_jpeg(tmp_path / "zwei.jpg", size=(40, 30))

    def make_item(source_file_id: int, path: Path, filename: str) -> GalleryItem:
        return GalleryItem(
            source_file_id=source_file_id,
            path=str(path),
            filename=filename,
            extension=".jpg",
            captured_at=None,
            timezone_unknown=False,
            gps_latitude=None,
            gps_longitude=None,
            camera=None,
            is_favorite=False,
            used_in_journal=False,
            thumbnail_path=Path("."),
            sort_status=None,
        )

    first = make_item(1, first_path, "eins.jpg")
    second = make_item(2, second_path, "zwei.jpg")
    window = MediaInspectorWindow(second, items=[first, second])
    assert window.item().filename == "zwei.jpg"
    assert window.windowTitle() == "zwei.jpg · 2 von 2"
    window.step(1)
    assert window.item().filename == "eins.jpg"
    assert window.windowTitle() == "eins.jpg · 1 von 2"
    QApplication.sendEvent(
        window,
        QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Right, Qt.KeyboardModifier.NoModifier),
    )
    assert window.item().filename == "zwei.jpg"
    window._image.side_clicked.emit(-1)
    assert window.item().filename == "eins.jpg"
    _ = app


def test_inspector_keeps_photo_aspect_on_resize() -> None:
    from PySide6.QtCore import QSize

    from traveljournal.widgets.media_inspector import size_keeping_photo_aspect

    wider = size_keeping_photo_aspect(QSize(800, 600), QSize(1000, 620), QSize(400, 300), QSize(20, 100))
    assert wider.width() == 1000
    assert wider.height() == 835
    taller = size_keeping_photo_aspect(QSize(800, 600), QSize(810, 800), QSize(400, 300), QSize(20, 100))
    assert taller.height() == 800
    assert taller.width() == 953


def test_inspector_allows_free_window_resize(tmp_path: Path) -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from jpeg_fixtures import write_plain_jpeg
    from PySide6.QtCore import QSize
    from PySide6.QtWidgets import QApplication

    from travelcore.media.gallery import GalleryItem
    from traveljournal.widgets.media_inspector import MediaInspectorWindow

    app = QApplication.instance() or QApplication([])
    jpeg = write_plain_jpeg(tmp_path / "foto.jpg", size=(40, 30))
    item = GalleryItem(
        source_file_id=1,
        path=str(jpeg),
        filename="foto.jpg",
        extension=".jpg",
        captured_at=None,
        timezone_unknown=False,
        gps_latitude=None,
        gps_longitude=None,
        camera=None,
        is_favorite=False,
        used_in_journal=False,
        thumbnail_path=Path("."),
        sort_status=None,
    )
    window = MediaInspectorWindow(item)
    window.resize(1200, 480)
    assert window.size() == QSize(1200, 480)
    window.resize(640, 900)
    assert window.size() == QSize(640, 900)
    _ = app


def test_media_inspector_zoom_arrows_and_fit(tmp_path: Path) -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from jpeg_fixtures import write_plain_jpeg
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtWidgets import QApplication

    from travelcore.media.gallery import GalleryItem
    from traveljournal.widgets.media_inspector import MediaInspectorWindow

    app = QApplication.instance() or QApplication([])
    first = write_plain_jpeg(tmp_path / "eins.jpg", size=(80, 60))
    second = write_plain_jpeg(tmp_path / "zwei.jpg", size=(80, 60))

    def make_item(source_file_id: int, path: Path, filename: str) -> GalleryItem:
        return GalleryItem(
            source_file_id=source_file_id,
            path=str(path),
            filename=filename,
            extension=".jpg",
            captured_at=None,
            timezone_unknown=False,
            gps_latitude=None,
            gps_longitude=None,
            camera=None,
            is_favorite=False,
            used_in_journal=False,
            thumbnail_path=Path("."),
            sort_status=None,
        )

    window = MediaInspectorWindow(
        make_item(1, first, "eins.jpg"),
        items=[make_item(1, first, "eins.jpg"), make_item(2, second, "zwei.jpg")],
    )
    canvas = window._image
    canvas.resize(400, 300)
    assert window._size_grip.objectName() == "inspectorSizeGrip"
    assert canvas.nav_side_at(10) == -1
    assert canvas.nav_side_at(200) == 0
    assert canvas.nav_side_at(390) == 1
    canvas._update_hover(12)
    assert canvas._hover_side == -1
    canvas.zoom_at(2.0, QPointF(200, 150))
    assert canvas.zoom == 2.0
    canvas.reset_view()
    assert canvas.zoom == 1.0
    canvas.zoom_at(3.0, QPointF(200, 150))
    assert canvas.zoom == 3.0
    canvas.mouseDoubleClickEvent(
        QMouseEvent(
            QEvent.Type.MouseButtonDblClick,
            QPointF(200, 150),
            QPointF(200, 150),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
    )
    assert canvas.zoom == 1.0
    _ = app
