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
    assert window.windowTitle() == "Reisetagebuch R1.1.0"
    assert window.stack.count() == 6
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
    from traveljournal.ui.sidebar import NAV_ITEMS

    assert [label for _, label in NAV_ITEMS] == [
        "Projekt",
        "Import",
        "Medien",
        "Timeline",
        "Karte",
        "Export",
    ]
    assert list(window.sidebar._buttons) == [key for key, _ in NAV_ITEMS]
    window.sidebar.set_collapsed(False)
    assert 96 <= window.sidebar.width() < 220
    assert not window.sidebar._buttons["map"].icon().isNull()
    assert not window.sidebar._collapse.icon().isNull()
    assert window.sidebar._collapse.toolTip() == "Navigation einklappen"
    assert window.sidebar._collapse.width() <= 16
    window.show()
    app.processEvents()
    collapse = window.sidebar._collapse
    assert collapse.x() + collapse.width() == window.sidebar.width()
    assert abs(collapse.geometry().center().y() - window.sidebar.height() // 2) <= 1
    window.sidebar.set_collapsed(True)
    assert window.sidebar.is_collapsed()
    assert 44 <= window.sidebar.width() <= 56
    assert window.sidebar._buttons["map"].text() == ""
    assert not window.sidebar._buttons["map"].icon().isNull()
    assert window.sidebar._collapse.toolTip() == "Navigation ausklappen"
    window.sidebar.set_collapsed(False)
    assert window.sidebar._buttons["map"].text() == "Karte"
    assert window.photos_view._media_tabs.count() == 4
    assert window.photos_view._media_tabs.tabText(0) == "Alle"
    assert window.photos_view._media_tabs.tabText(3) == "Aussortiert"
    assert window.timeline_view._trip_title.placeholderText() == "Titel der Reise"
    assert not window.timeline_view._trip_title.isEnabled()
    _ = app


def test_app_window_title_includes_version() -> None:
    from traveljournal.__about__ import app_window_title

    assert app_window_title() == "Reisetagebuch R1.1.0"
    assert app_window_title("Alpen 2025") == "Reisetagebuch R1.1.0 - Alpen 2025"
    assert app_window_title("  ") == "Reisetagebuch R1.1.0"


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
    assert widget.entry_kind() == "day"
    assert widget._kind_combo.currentData() == "day"
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


def test_entry_widget_section_has_to_map_button() -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from datetime import UTC, datetime

    from PySide6.QtWidgets import QApplication, QPushButton

    from travelcore.timeline.types import TimelineDay, TimelineEntry, TimelineSection
    from traveljournal.views.timeline_view import EntryWidget

    app = QApplication.instance() or QApplication([])
    stamp = datetime(2025, 5, 15, 8, 0, tzinfo=UTC)
    section = TimelineSection(
        id=7,
        kind="stay",
        mode=None,
        title="Bozen",
        notes=None,
        started_at=stamp,
        ended_at=stamp,
        location_name=None,
        location_from=None,
        location_to=None,
        origin="manual",
    )
    widget = EntryWidget(TimelineEntry(started_at=stamp, section=section))
    button = widget.findChild(QPushButton, "entryToMap")
    assert button is not None
    assert button.isEnabled()
    keys: list[str] = []
    widget.open_on_map.connect(keys.append)
    button.click()
    assert keys == ["section:7"]

    pending = TimelineSection(
        id=-1,
        kind="stay",
        mode=None,
        title="Neu",
        notes=None,
        started_at=stamp,
        ended_at=stamp,
        location_name=None,
        location_from=None,
        location_to=None,
        origin="manual",
    )
    unsaved = EntryWidget(TimelineEntry(started_at=stamp, section=pending))
    pending_btn = unsaved.findChild(QPushButton, "entryToMap")
    assert pending_btn is not None
    assert not pending_btn.isEnabled()

    day = TimelineDay(
        id=1,
        day_index=0,
        date=stamp.date(),
        title=None,
        notes=None,
        origin="auto",
        photos=(),
    )
    leftover = EntryWidget(TimelineEntry(started_at=stamp, leftover_day=day))
    day_btn = leftover.findChild(QPushButton, "entryToMap")
    assert day_btn is not None
    assert day_btn.isEnabled()
    day_keys: list[str] = []
    leftover.open_on_map.connect(day_keys.append)
    day_btn.click()
    assert day_keys == ["day:1"]
    _ = app


def test_map_view_focus_group_centers_section_card() -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from travelcore.maps.groups import MapTimelineCard
    from travelcore.timeline.sections import KIND_STAY
    from traveljournal.services.workspace import Workspace
    from traveljournal.views.map_view import MapView
    from traveljournal.widgets.entry_links import YouTubeThumbLabel

    app = QApplication.instance() or QApplication([])
    view = MapView(Workspace())
    view._stack.setCurrentWidget(view._web_host)
    view._timeline.set_cards(
        (
            MapTimelineCard(
                group_key="section:1",
                title="Eins",
                time_label="am 01.05.2025",
                latitude=46.0,
                longitude=11.0,
                card_kind=KIND_STAY,
                notes="Erster Text",
            ),
            MapTimelineCard(
                group_key="section:7",
                title="Sieben",
                time_label="am 02.05.2025",
                latitude=47.0,
                longitude=12.0,
                card_kind=KIND_STAY,
                notes="Zweiter Text",
                youtube_urls=(
                    "https://youtu.be/dQw4w9WgXcQ",
                    "https://youtu.be/aaaaaaaaaaa",
                ),
            ),
        )
    )
    view.resize(800, 500)
    view.show()
    app.processEvents()
    view.focus_group("section:7")
    app.processEvents()
    assert view._timeline.focused_key() == "section:7"
    assert view._notes_edit.toPlainText() == "Zweiter Text"
    assert view._notes_actions.isHidden()
    assert view._youtube.isVisible()
    thumbs = view._youtube.findChildren(YouTubeThumbLabel)
    assert len(thumbs) == 2
    assert view._youtube.parent() is view._map_frame
    app.processEvents()
    bottom = max(thumb.y() for thumb in thumbs)
    top = min(thumb.y() for thumb in thumbs)
    assert bottom > top
    first = next(thumb for thumb in thumbs if thumb.toolTip() == "https://youtu.be/dQw4w9WgXcQ")
    second = next(thumb for thumb in thumbs if thumb.toolTip() == "https://youtu.be/aaaaaaaaaaa")
    assert first.y() >= second.y()
    _ = app


def test_map_notes_edit_shows_save_cancel_discard() -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from travelcore.maps.groups import MapTimelineCard
    from travelcore.timeline.sections import KIND_STAY
    from traveljournal.services.workspace import Workspace
    from traveljournal.views.map_view import MapView

    app = QApplication.instance() or QApplication([])
    view = MapView(Workspace())
    view._timeline.set_cards(
        (
            MapTimelineCard(
                group_key="section:1",
                title="Eins",
                time_label="am 01.05.2025",
                latitude=46.0,
                longitude=11.0,
                card_kind=KIND_STAY,
                notes="Original",
            ),
        )
    )
    view._load_entry_panel("section:1")
    assert view._notes_actions.isHidden()
    view._notes_edit.setPlainText("Geändert")
    assert not view._notes_actions.isHidden()
    assert view._notes_save.text() == "Speichern"
    assert view._notes_cancel.text() == "Abbrechen"
    assert view._notes_discard.text() == "Verwerfen"
    view._notes_cancel.click()
    assert view._notes_edit.toPlainText() == "Original"
    assert view._notes_actions.isHidden()
    view._notes_edit.setPlainText("Nochmals")
    view._notes_save.click()
    assert view._notes_edit.toPlainText() == "Nochmals"
    assert view._timeline.card("section:1").notes == "Nochmals"
    assert view._notes_actions.isHidden()
    view._notes_edit.setPlainText("Weg damit")
    view._notes_discard.click()
    assert view._notes_edit.toPlainText() == ""
    assert view._timeline.card("section:1").notes == ""
    assert view._notes_actions.isHidden()
    _ = app


def test_map_notes_switch_card_opens_save_dialog(monkeypatch) -> None:  # noqa: ANN001
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QMessageBox

    from travelcore.maps.groups import MapTimelineCard
    from travelcore.timeline.sections import KIND_STAY
    from traveljournal.services.workspace import Workspace
    from traveljournal.views.map_view import MapView

    app = QApplication.instance() or QApplication([])
    cards = (
        MapTimelineCard(
            group_key="section:1",
            title="Eins",
            time_label="am 01.05.2025",
            latitude=46.0,
            longitude=11.0,
            card_kind=KIND_STAY,
            notes="Eins-Text",
        ),
        MapTimelineCard(
            group_key="section:7",
            title="Sieben",
            time_label="am 02.05.2025",
            latitude=47.0,
            longitude=12.0,
            card_kind=KIND_STAY,
            notes="Sieben-Text",
        ),
    )
    labels: list[str] = []

    def fake_exec(self: QMessageBox) -> int:
        labels.extend(button.text() for button in self.buttons())
        return 0

    monkeypatch.setattr(QMessageBox, "exec", fake_exec)
    view = MapView(Workspace())
    view._timeline.set_cards(cards)
    view._load_entry_panel("section:1")
    view._notes_edit.setPlainText("Geändert")
    assert view._ask_dirty_notes() == "cancel"
    assert set(labels) == {"Speichern", "Abbrechen", "Verwerfen"}

    monkeypatch.setattr(view, "_ask_dirty_notes", lambda: "cancel")
    view._timeline.center_on("section:7")
    app.processEvents()
    assert view._notes_group_key == "section:1"
    assert view._notes_edit.toPlainText() == "Geändert"
    assert view._timeline.focused_key() == "section:1"

    monkeypatch.setattr(view, "_ask_dirty_notes", lambda: "save")
    view._timeline.center_on("section:7")
    app.processEvents()
    assert view._timeline.card("section:1").notes == "Geändert"
    assert view._notes_group_key == "section:7"
    assert view._notes_edit.toPlainText() == "Sieben-Text"

    view._notes_edit.setPlainText("Nur im Editor")
    monkeypatch.setattr(view, "_ask_dirty_notes", lambda: "discard")
    view._timeline.center_on("section:1")
    app.processEvents()
    assert view._timeline.card("section:7").notes == "Sieben-Text"
    assert view._notes_group_key == "section:1"
    assert view._notes_edit.toPlainText() == "Geändert"
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


def test_photos_view_media_tab_filters_favorites(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from datetime import UTC, datetime

    from PySide6.QtWidgets import QApplication

    from travelcore.media.gallery import GalleryItem
    from traveljournal.services import workspace as workspace_mod
    from traveljournal.services.workspace import Workspace
    from traveljournal.views.photos_view import PhotosView
    from traveljournal.widgets.media_tabs import media_tab_index

    monkeypatch.setattr(workspace_mod, "_UI_CONFIG_PATH", tmp_path / "config.json")
    app = QApplication.instance() or QApplication([])
    view = PhotosView(Workspace())
    stamp = datetime(2025, 5, 15, 8, 0, tzinfo=UTC)

    def item(name: str, source_file_id: int, *, favorite: bool) -> GalleryItem:
        return GalleryItem(
            source_file_id=source_file_id,
            path=name,
            filename=name,
            extension=".jpg",
            captured_at=stamp,
            timezone_unknown=False,
            gps_latitude=None,
            gps_longitude=None,
            camera=None,
            is_favorite=favorite,
            used_in_journal=False,
            thumbnail_path=Path("."),
            sort_status="favorite" if favorite else None,
        )

    view._items = [
        item("normal.jpg", 1, favorite=False),
        item("fav.jpg", 2, favorite=True),
    ]
    view._apply_filters()
    assert [row.filename for row in view.gallery.items()] == ["normal.jpg", "fav.jpg"]
    view._media_tabs.setCurrentIndex(media_tab_index("favorite"))
    assert [row.filename for row in view.gallery.items()] == ["fav.jpg"]
    _ = app


def test_photos_rating_applies_to_timeline_gallery(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from datetime import UTC, datetime

    from PySide6.QtWidgets import QApplication

    from travelcore.media.gallery import GalleryItem
    from travelcore.timeline.types import TimelineDay, TimelineEntry, TimelinePhoto
    from traveljournal.services import workspace as workspace_mod
    from traveljournal.services.workspace import Workspace
    from traveljournal.views.timeline_view import EntryWidget, TimelineView

    monkeypatch.setattr(workspace_mod, "_UI_CONFIG_PATH", tmp_path / "config.json")
    app = QApplication.instance() or QApplication([])
    stamp = datetime(2025, 5, 15, 8, 0, tzinfo=UTC)
    photo = TimelinePhoto(
        source_file_id=7,
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
        sort_status=None,
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
    timeline = TimelineView(Workspace())
    block = EntryWidget(TimelineEntry(started_at=stamp, leftover_day=day), parent=timeline)
    timeline._blocks = [block]
    rated = GalleryItem(
        source_file_id=7,
        path="foto.jpg",
        filename="foto.jpg",
        extension=".jpg",
        captured_at=stamp,
        timezone_unknown=False,
        gps_latitude=None,
        gps_longitude=None,
        camera=None,
        is_favorite=True,
        used_in_journal=False,
        thumbnail_path=Path("."),
        sort_status="favorite",
    )
    timeline.apply_media_rating(rated)
    assert timeline._media_ratings_stale
    shown = block.gallery.items()
    assert len(shown) == 1
    assert shown[0].sort_status == "favorite"
    assert shown[0].is_favorite is True
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


def test_timeline_save_button_only_when_dirty(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from datetime import UTC, datetime

    from PySide6.QtWidgets import QApplication

    from travelcore.timeline.types import PendingSectionSpec, TimelineDay, TimelineEntry, TimelinePhoto
    from traveljournal.services import workspace as workspace_mod
    from traveljournal.services.workspace import Workspace
    from traveljournal.views.timeline_view import EntryWidget, TimelineView

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
    view = TimelineView(Workspace())
    assert not view._save_button.isEnabled()
    view._loaded_trip_title = "Reise"
    view._trip_title.setEnabled(True)
    view._trip_title.setText("Reise")
    assert not view._save_button.isEnabled()
    view._trip_title.setText("Alpen 2025")
    assert view._save_button.isEnabled()
    view._trip_title.setText("Reise")
    assert not view._save_button.isEnabled()
    block = EntryWidget(TimelineEntry(started_at=stamp, leftover_day=day), parent=view)
    block.content_changed.connect(view._update_save_button)
    view._blocks = [block]
    view._update_save_button()
    assert not view._save_button.isEnabled()
    block.notes_edit.setPlainText("Abend in Bozen")
    assert view._save_button.isEnabled()
    block.notes_edit.setPlainText("")
    assert not view._save_button.isEnabled()
    block._youtube_urls = ["https://www.youtube.com/watch?v=aaaaaaaaaaa"]
    view._update_save_button()
    assert view._save_button.isEnabled()
    block._youtube_urls = list(block.youtube_from_db())
    view._update_save_button()
    assert not view._save_button.isEnabled()
    view._pending.append(PendingSectionSpec(local_id=-1, source_file_ids=(1,), kind="stay"))
    view._update_save_button()
    assert view._save_button.isEnabled()
    view._pending.clear()
    view._update_save_button()
    assert not view._save_button.isEnabled()
    _ = app


def test_timeline_leave_without_prompt_when_only_text_dirty(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from datetime import UTC, datetime

    from PySide6.QtWidgets import QApplication

    from travelcore.timeline.types import TimelineDay, TimelineEntry, TimelinePhoto
    from traveljournal.services import workspace as workspace_mod
    from traveljournal.services.workspace import Workspace
    from traveljournal.views.timeline_view import EntryWidget, TimelineView

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
    view = TimelineView(Workspace())
    block = EntryWidget(TimelineEntry(started_at=stamp, leftover_day=day), parent=view)
    block.content_changed.connect(view._update_save_button)
    view._blocks = [block]
    block.notes_edit.setPlainText("Abend in Bozen")
    assert view._save_button.isEnabled()
    assert view.confirm_leave() is True
    assert view._save_button.isEnabled()
    assert block.is_dirty()
    _ = app


def test_scroll_offset_to_widget_top_uses_host_not_page_chrome() -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget

    from traveljournal.views.timeline_view import scroll_offset_to_widget_top

    app = QApplication.instance() or QApplication([])
    page = QWidget()
    layout = QVBoxLayout(page)
    chrome = QLabel("Reisetitel")
    chrome.setFixedHeight(90)
    layout.addWidget(chrome)
    host = QWidget()
    host_layout = QVBoxLayout(host)
    host_layout.setContentsMargins(0, 0, 0, 0)
    host_layout.setSpacing(16)
    first = QLabel("eins")
    first.setFixedHeight(400)
    second = QLabel("zwei")
    second.setFixedHeight(400)
    host_layout.addWidget(first)
    host_layout.addWidget(second)
    layout.addWidget(host)
    page.resize(480, 320)
    page.show()
    app.processEvents()
    first_offset = scroll_offset_to_widget_top(host, first, padding=12)
    second_offset = scroll_offset_to_widget_top(host, second, padding=12)
    assert first_offset == 0
    assert second_offset == 400 + 16 - 12
    _ = app


def test_reveal_group_puts_section_top_at_list_top() -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from datetime import UTC, datetime

    from PySide6.QtWidgets import QApplication

    from travelcore.timeline.types import TimelineDay, TimelineEntry, TimelinePhoto
    from traveljournal.services.workspace import Workspace
    from traveljournal.views.timeline_view import (
        EntryWidget,
        TimelineView,
        scroll_offset_to_widget_top,
    )

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

    def day(day_id: int) -> TimelineDay:
        return TimelineDay(
            id=day_id,
            day_index=day_id - 1,
            date=stamp.date(),
            title=None,
            notes=None,
            origin="auto",
            photos=(photo,),
        )

    workspace = Workspace()
    view = TimelineView(workspace)
    view.resize(720, 420)
    view._empty.setVisible(False)
    first = EntryWidget(TimelineEntry(started_at=stamp, leftover_day=day(1)), parent=view._host)
    second = EntryWidget(TimelineEntry(started_at=stamp, leftover_day=day(2)), parent=view._host)
    first.setMinimumHeight(520)
    second.setMinimumHeight(520)
    stretch = view._host_layout.takeAt(view._host_layout.count() - 1)
    view._host_layout.addWidget(first)
    view._host_layout.addWidget(second)
    if stretch is not None:
        view._host_layout.addItem(stretch)
    view._blocks = [first, second]
    view._host.setMinimumHeight(1200)
    view.show()
    view._host.adjustSize()
    app.processEvents()
    assert view._block_for_group_key("day:2") is second
    view._pending_reveal = second
    view._apply_pending_reveal()
    bar = view._scroll.verticalScrollBar()
    expected = scroll_offset_to_widget_top(view._host, second)
    assert bar.maximum() >= expected
    assert bar.value() == expected
    assert expected > 0
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


def test_inspector_map_opens_thumbnail_then_original_on_double_click(tmp_path: Path) -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from jpeg_fixtures import write_plain_jpeg
    from PySide6.QtWidgets import QApplication

    from travelcore.media.gallery import GalleryItem
    from traveljournal.widgets.media_inspector import MediaInspectorWindow

    app = QApplication.instance() or QApplication([])
    original = write_plain_jpeg(tmp_path / "foto.jpg", size=(200, 150))
    thumb = write_plain_jpeg(tmp_path / "thumb.jpg", size=(40, 30))
    item = GalleryItem(
        source_file_id=1,
        path=str(original),
        filename="foto.jpg",
        extension=".jpg",
        captured_at=None,
        timezone_unknown=False,
        gps_latitude=None,
        gps_longitude=None,
        camera=None,
        is_favorite=False,
        used_in_journal=False,
        thumbnail_path=thumb,
        sort_status=None,
    )
    window = MediaInspectorWindow(item, thumbnail_first=True)
    assert "Vorschau" in window.windowTitle()
    assert not window.showing_original()
    assert window._image.source().width() == 40
    window._on_photo_double_click()
    assert window.showing_original()
    assert "Vorschau" not in window.windowTitle()
    assert window._image.source().width() == 200
    _ = app


def test_parse_map_bridge_url_reads_group_key() -> None:
    from traveljournal.views.map_view import (
        MAP_PAGE_SETUP_JS,
        parse_map_bridge_url,
        parse_map_expand_console,
        parse_map_media_console,
        parse_map_media_url,
    )

    assert parse_map_bridge_url("traveljournal://expand?key=section%3A12") == "section:12"
    assert parse_map_bridge_url("https://traveljournal.local/expand?key=section%3A12") == "section:12"
    assert parse_map_bridge_url("https://example.com") is None
    assert parse_map_expand_console("traveljournal:expand:day:4") == "day:4"
    assert parse_map_expand_console("JS: traveljournal:expand:section:1") == "section:1"
    assert parse_map_expand_console("leaflet ready") is None
    assert parse_map_media_url("https://traveljournal.local/media?id=9") == 9
    assert parse_map_media_console("traveljournal:media:9") == 9
    assert parse_map_media_console("traveljournal:expand:day:4") is None
    assert "pointerup" in MAP_PAGE_SETUP_JS
    assert "zoom: {animate: false}" in MAP_PAGE_SETUP_JS


def test_map_view_refresh_uses_disk_cache_without_rebuild(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from gpx_fixtures import write_gpx
    from PySide6.QtWidgets import QApplication

    from travelcore.database.models import Project
    from travelcore.database.project_store import ProjectStore
    from travelcore.maps.cache import FoliumMapBackend
    from travelcore.media.indexer import FileIndexer
    from traveljournal.services.workspace import Workspace
    from traveljournal.views.map_view import MapView

    app = QApplication.instance() or QApplication([])
    store = ProjectStore()
    opened = store.create(tmp_path / "reise_karte", "Karte")
    source = tmp_path / "media"
    source.mkdir()
    write_gpx(
        source / "spur.gpx",
        [
            (46.0, 11.0, 260.0, "2025-05-15T13:31:50Z"),
            (46.2, 11.2, 280.0, "2025-05-15T13:32:10Z"),
        ],
    )
    with opened.session_factory() as session:
        project = session.get(Project, opened.project_id)
        assert project is not None
        FileIndexer().index(session, project, source, generate_thumbnails=False)
        session.commit()

    workspace = Workspace()
    workspace.current = opened
    calls = {"n": 0}
    original = FoliumMapBackend.render

    def wrapped(self, scene, output_html):  # noqa: ANN001
        calls["n"] += 1
        return original(self, scene, output_html)

    monkeypatch.setattr("travelcore.maps.cache.FoliumMapBackend.render", wrapped)
    first = workspace.render_map()
    assert not first.from_cache
    assert calls["n"] == 1
    view = MapView(workspace)
    view.refresh()
    view.refresh()
    assert calls["n"] == 1
    assert "1 Titelbilder" in view._subtitle.text()
    assert len(view._timeline.cards()) == 1
    assert view._timeline.cards()[0].group_key.startswith("loose:")
    view.resize(900, 640)
    view.show()
    app.processEvents()
    assert view._timeline.isVisible()
    assert view._timeline.parent() is view._web_host
    _ = app


def test_publish_map_display_writes_unique_file(tmp_path: Path) -> None:
    from traveljournal.views.map_view import publish_map_display

    html = tmp_path / "map.html"
    html.write_text("<html>one</html>", encoding="utf-8")
    first = publish_map_display(html, 1)
    assert first.name == "map-1.html"
    assert first.read_text(encoding="utf-8") == "<html>one</html>"
    html.write_text("<html>two</html>", encoding="utf-8")
    second = publish_map_display(html, 2)
    assert second.name == "map-2.html"
    assert second.read_text(encoding="utf-8") == "<html>two</html>"
    assert not first.is_file()


def test_map_view_applies_prepared_result_when_shown(tmp_path: Path) -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from gpx_fixtures import write_gpx
    from PySide6.QtWidgets import QApplication

    from travelcore.database.models import Project
    from travelcore.database.project_store import ProjectStore
    from travelcore.media.indexer import FileIndexer
    from traveljournal.services.workspace import Workspace
    from traveljournal.views.map_view import MapView

    app = QApplication.instance() or QApplication([])
    store = ProjectStore()
    opened = store.create(tmp_path / "reise_karte_pending", "Karte")
    source = tmp_path / "media"
    source.mkdir()
    write_gpx(
        source / "spur.gpx",
        [
            (46.0, 11.0, 260.0, "2025-05-15T13:31:50Z"),
            (46.2, 11.2, 280.0, "2025-05-15T13:32:10Z"),
        ],
    )
    with opened.session_factory() as session:
        project = session.get(Project, opened.project_id)
        assert project is not None
        FileIndexer().index(session, project, source, generate_thumbnails=False)
        session.commit()

    workspace = Workspace()
    workspace.current = opened
    result = workspace.render_map()
    view = MapView(workspace)
    view._on_prepared(view._generation, opened.directory, result)
    assert view._pending_result is result
    assert view._stack.currentWidget() is view._message
    view.show()
    app.processEvents()
    assert view._pending_result is None
    assert "1 Titelbilder" in view._subtitle.text()
    assert view._stack.currentWidget() is view._web_host
    assert view._desired_seq == result.render_seq
    rebuilt = workspace.render_map(force=True)
    assert not rebuilt.from_cache
    assert rebuilt.render_seq != result.render_seq
    view._apply_result(rebuilt)
    assert view._desired_seq == rebuilt.render_seq
    assert view._loaded_seq != rebuilt.render_seq
    _ = app


def test_map_timeline_strip_centers_first_card() -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QEvent, QPointF, QRectF, Qt
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtWidgets import QApplication

    from travelcore.maps.groups import MapTimelineCard
    from travelcore.timeline.sections import KIND_DAY, KIND_MOVEMENT, KIND_STAY
    from traveljournal.widgets.map_timeline import (
        CARD_HEIGHT,
        CARD_IDLE_SCALE,
        CARD_WIDTH,
        MapTimelineStrip,
        cover_dest_rect,
        hexagon_cut,
        nearest_card_index,
        transfer_hexagon_path,
    )

    dest = cover_dest_rect(QRectF(0, 0, 100, 50), 200, 200)
    assert dest.width() == 100
    assert dest.height() == 100
    assert dest.left() <= 0
    assert dest.right() >= 100
    assert dest.top() <= 0
    assert dest.bottom() >= 50

    assert nearest_card_index([], 0) is None
    assert nearest_card_index([10, 100, 220], 90) == 1

    hex_rect = QRectF(0, 0, CARD_WIDTH, CARD_HEIGHT)
    hex_path = transfer_hexagon_path(hex_rect)
    cut = hexagon_cut(hex_rect)
    assert cut == min(CARD_HEIGHT * 0.28, CARD_WIDTH * 0.22)
    bounds = hex_path.boundingRect()
    assert abs(bounds.width() - CARD_WIDTH) < 0.51
    assert abs(bounds.height() - CARD_HEIGHT) < 0.51
    assert hex_path.contains(QPointF(1, CARD_HEIGHT / 2))
    assert not hex_path.contains(QPointF(1, 10))
    assert hex_path.contains(QPointF(CARD_WIDTH / 2, CARD_HEIGHT - 8))
    assert hexagon_cut(QRectF()) == 0.0

    app = QApplication.instance() or QApplication([])
    strip = MapTimelineStrip()
    strip.resize(640, 180)
    strip.show()
    app.processEvents()
    focused: list[str] = []
    strip.focus_changed.connect(focused.append)
    strip.set_cards(
        (
            MapTimelineCard(
                group_key="section:1",
                title="Eins",
                time_label="am 01.05.2025",
                latitude=46.0,
                longitude=11.0,
                card_kind=KIND_STAY,
                photo_count=2,
                photo_reserve_count=1,
                track_count=1,
                igc_count=2,
                igc_reserve_count=1,
                youtube_count=3,
            ),
            MapTimelineCard(
                group_key="section:2",
                title="Zwei",
                time_label="am 02.05.2025",
                latitude=47.0,
                longitude=12.0,
                card_kind=KIND_MOVEMENT,
            ),
            MapTimelineCard(
                group_key="day:3",
                title="Drei",
                time_label="am 03.05.2025",
                latitude=48.0,
                longitude=13.0,
                card_kind=KIND_DAY,
            ),
        )
    )
    strip.show()
    app.processEvents()
    assert focused == ["section:1"]
    assert strip.focused_key() == "section:1"
    assert strip._widgets[0].property("focused") is True
    assert strip._widgets[1].property("focused") is False
    titles = [widget.card.title for widget in strip._widgets]
    assert titles == ["Eins", "Zwei", "Drei"]
    assert strip.show_reserve() is False
    assert strip._widgets[0].card.visible_counts(show_reserve=False) == (2, 1, 2, 3)
    strip.set_show_reserve(True)
    assert strip.show_reserve() is True
    assert strip._widgets[0].card.visible_counts(show_reserve=True) == (3, 1, 3, 3)
    idle_w = round(CARD_WIDTH * CARD_IDLE_SCALE)
    idle_h = round(CARD_HEIGHT * CARD_IDLE_SCALE)
    assert strip._widgets[0].width() == CARD_WIDTH
    assert strip._widgets[0].height() == CARD_HEIGHT
    assert strip._widgets[1].width() == idle_w
    assert strip._widgets[1].height() == idle_h
    assert strip._widgets[2].width() == idle_w
    assert strip._widgets[2].height() == idle_h
    assert strip._widgets[2].property("cardKind") == KIND_DAY
    strip.center_on("section:2")
    app.processEvents()
    assert focused[-1] == "section:2"
    assert strip.focused_key() == "section:2"
    assert strip._widgets[1].width() == CARD_WIDTH
    assert strip._widgets[1].height() == CARD_HEIGHT
    assert strip._widgets[0].width() == idle_w
    assert strip._widgets[0].height() == idle_h
    lines = [child for child in strip._inner.children() if child.objectName() == "mapTimelineLine"]
    assert len(lines) == 2
    again = len(focused)
    strip.center_on("section:2")
    app.processEvents()
    assert focused[-1] == "section:2"
    assert len(focused) == again + 1
    opened: list[str] = []
    strip.open_in_timeline.connect(opened.append)
    strip._widgets[0].mouseDoubleClickEvent(
        QMouseEvent(
            QEvent.Type.MouseButtonDblClick,
            QPointF(20, 20),
            QPointF(20, 20),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
    )
    assert opened == ["section:1"]
    _ = app
