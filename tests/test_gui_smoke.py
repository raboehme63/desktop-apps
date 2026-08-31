"""GUI smoke test. Requires an offscreen Qt platform plugin."""

from __future__ import annotations

import os
from pathlib import Path


def test_main_window_starts(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtGui import QKeySequence
    from PySide6.QtWidgets import QApplication, QLabel, QScrollArea, QWidget

    from traveljournal.services import workspace as workspace_mod
    from traveljournal.ui.main_window import MainWindow

    monkeypatch.setattr(workspace_mod, "_CONFIG_DIR", tmp_path)
    monkeypatch.setattr(workspace_mod, "_UI_CONFIG_PATH", tmp_path / "config.json")

    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    assert window.windowTitle() == "Reisetagebuch R3.1.0"
    assert window.stack.count() == 6
    titles = [action.text() for action in window.menuBar().actions()]
    assert "Projekt" in titles
    assert "Bearbeiten" in titles
    assert "Hilfe" in titles
    help_menu = next(action.menu() for action in window.menuBar().actions() if action.text() == "Hilfe")
    help_items = [action.text() for action in help_menu.actions()]
    assert "Verkehrsmittelsymbole…" in help_items
    from travelcore.timeline.symbols import TRANSPORT_SYMBOLS
    from traveljournal.views.help_dialog import HelpDialog

    help_dialog = HelpDialog(window)
    assert help_dialog.windowTitle() == "Hilfe"
    assert help_dialog.objectName() == "helpDialog"
    for item in TRANSPORT_SYMBOLS:
        row = help_dialog.findChild(QWidget, f"helpSymbol-{item.key}")
        assert row is not None
        assert item.label in row.findChild(QLabel, "fieldCaption").text()
        assert item.summary in row.findChild(QLabel, "pageSubtitle").text()
        icon = row.findChild(QLabel, "helpSymbolIcon")
        assert icon is not None
        assert not icon.pixmap().isNull()
    help_dialog.close()
    assert window._undo_action.shortcut() == QKeySequence.StandardKey.Undo
    assert window._redo_action.shortcut() == QKeySequence.StandardKey.Redo
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
    assert window.import_view._sync_button.text() == "Synchronisieren"
    assert "Mouseover" in window.import_view._preview_meta.text()
    assert window.project_view.name_label.text() == "–"
    assert not window.project_view.name_edit.isEnabled()
    assert not window.project_view.country_picker.isEnabled()
    assert not window.project_view.start_edit.isEnabled()
    assert not window.project_view.end_edit.isEnabled()
    assert window.project_view.duration_label.text() == "Dauer: –"
    assert window.project_view.load_progress.format() == "Bereit"
    assert window._load_progress.isHidden()
    assert not window.import_view.is_loading_index
    assert isinstance(window.timeline_view._scroll, QScrollArea)
    assert window.timeline_view._media_tabs.count() == 4
    assert window.timeline_view._media_tabs.tabText(0) == "Alle"
    assert window.timeline_view._media_tabs.tabText(1) == "Favoriten"
    assert window.timeline_view._thumb_zoom.value() == 100
    assert window.map_view._thumb_zoom.value() == 100
    assert window.photos_view._thumb_zoom.value() == 100
    assert window.import_view._thumb_zoom.value() == 100
    assert window.timeline_view._pool_toggle.isCheckable()
    assert not window.timeline_view._pool_toggle.isChecked()
    assert window.timeline_view._pool_toggle.objectName() == "poolCollapse"
    assert window.timeline_view._pool_toggle.text() == ""
    assert not window.timeline_view._pool_toggle.icon().isNull()
    assert window.timeline_view._pool_toggle.toolTip() == "Medienpool ausklappen"
    assert window.timeline_view._pool_toggle.width() <= 16
    assert window.timeline_view._pool_pane.isHidden()
    from traveljournal.ui.sidebar import NAV_ITEMS

    assert [label for _, label in NAV_ITEMS] == [
        "Projekt",
        "Import",
        "Medien",
        "Timeline",
        "Karte",
        "Export",
    ]
    assert window.export_view._product_buttons["travelbook"].isChecked()
    assert window.export_view._product_buttons["travelbook"].text() == "Travelbook"
    assert not hasattr(window.export_view, "_format_buttons")
    assert window.export_view.findChild(QLabel, "pageTitle") is None
    assert window.export_view._mode_buttons["export"].isChecked()
    assert window.export_view._mode_buttons["export"].text() == "Vorschau"
    assert window.export_view._mode_buttons["edit"].text() == "Editiermodus"
    assert window.export_view._add_spread_button.isHidden()
    assert window.export_view._remove_spread_button.isHidden()
    assert window.export_view._save_template_button.isHidden()
    assert window.export_view._tray.isHidden()
    assert window.export_view._page_size_id == "a4-portrait"
    assert window.export_view._page_buttons["a4-portrait"].isChecked()
    assert window.export_view._page_buttons["a4-portrait"].text() == "DIN A4 Hochformat"
    assert list(window.export_view._layout_buttons) == [f"photos_{index}" for index in range(1, 9)]
    assert window.export_view._layout_buttons["photos_1"].text() == "1"
    assert window.export_view._layout_buttons["photos_4"].toolTip() == "4 Fotos"
    assert not any(button.isChecked() for button in window.export_view._layout_buttons.values())
    assert not window.export_view._layout_row_host.isHidden()
    assert window.export_view._overlap_button.objectName() == "exportSpreadOverlap"
    assert window.export_view._overlap_button.text() == "Über die Mitte"
    assert not window.export_view._overlap_button.isChecked()
    assert not window.export_view._manage_layouts_button.isHidden()
    assert window.export_view._manage_layouts_button.text() == "Vorlagen…"
    window.export_view._layout_buttons["photos_4"].click()
    app.processEvents()
    assert window.export_view._photo_layout_id == "photos_4"
    assert window.export_view._layout_buttons["photos_4"].isChecked()
    assert "4 Fotos" in window.export_view._choices_summary.text()
    assert not window.export_view._preview.isHidden()
    assert not window.export_view._size_row_host.isHidden()
    assert not window.export_view._choices_body.isHidden()
    window.export_view._collapse_button.click()
    app.processEvents()
    assert window.export_view._choices_body.isHidden()
    window.export_view._collapse_button.click()
    app.processEvents()
    assert not window.export_view._choices_body.isHidden()
    window.export_view._mode_buttons["edit"].click()
    app.processEvents()
    assert not window.export_view._add_spread_button.isHidden()
    assert not window.export_view._save_template_button.isHidden()
    assert not window.export_view._save_template_button.isEnabled()
    assert not window.export_view._tray.isHidden()
    window.export_view._mode_buttons["export"].click()
    app.processEvents()
    assert window.export_view._add_spread_button.isHidden()
    assert window.export_view._tray.isHidden()
    assert window.export_view._preview._indicator.text() == "Cover"
    assert not window.export_view._preview._prev.isEnabled()
    assert not window.export_view._preview._first.isEnabled()
    assert window.export_view._preview._next.isEnabled()
    assert window.export_view._preview._last.isEnabled()
    assert window.export_view._preview._goto_button.text() == "Gehe zu"
    window.export_view._preview._next.click()
    app.processEvents()
    assert window.export_view._preview._indicator.text() == "Titelseite"
    assert window.export_view._preview._leaves[1].variant == "title"
    assert window.export_view._preview._recto._center_title.text() == "Reise"
    window.export_view._preview._next.click()
    app.processEvents()
    assert window.export_view._preview._indicator.text().startswith("1–2/")
    assert window.export_view._preview._leaves[2].variant == "summary"
    assert window.export_view._preview._leaves[2].metrics == ()
    from traveljournal.views.export_view import ExportFormatDialog
    from traveljournal.views.photo_templates_dialog import PhotoTemplateDialog

    format_dialog = ExportFormatDialog("travelbook", window)
    assert "html" in format_dialog._buttons
    assert "pdf" in format_dialog._buttons
    assert "cewe" in format_dialog._buttons
    assert "video" not in format_dialog._buttons
    assert format_dialog._buttons["html"].isChecked()
    assert format_dialog._quality_host.isHidden()
    assert format_dialog._cewe_note.isHidden()
    format_dialog._buttons["cewe"].click()
    app.processEvents()
    assert not format_dialog._cewe_note.isHidden()
    assert format_dialog._quality_host.isHidden()
    format_dialog._buttons["html"].click()
    app.processEvents()
    assert format_dialog._cewe_note.isHidden()
    format_dialog._buttons["pdf"].click()
    app.processEvents()
    assert not format_dialog._quality_host.isHidden()
    assert list(format_dialog._quality_buttons) == ["screen", "print", "magazine"]
    assert format_dialog._quality_buttons["print"].isChecked()
    assert format_dialog._quality_buttons["magazine"].text() == "Beste Qualität"
    format_dialog._quality_buttons["magazine"].click()
    app.processEvents()
    assert format_dialog.selected_quality() == "magazine"
    assert "300 dpi" in format_dialog._quality_note.text()
    format_dialog.close()
    interactive_formats = ExportFormatDialog("travelbook-interactive", window)
    assert list(interactive_formats._buttons) == ["html"]
    assert interactive_formats._quality_host.isHidden()
    interactive_formats.close()
    templates = PhotoTemplateDialog(
        page_size_id="a4-portrait",
        page_size_label="DIN A4 Hochformat",
        width_mm=210,
        height_mm=297,
        current_frames=(),
        parent=window,
    )
    assert templates.windowTitle() == "Fotoseiten-Vorlagen"
    assert templates._list.count() == 8
    assert not templates._save_button.isEnabled()
    templates._list.setCurrentRow(0)
    app.processEvents()
    assert not templates._delete_button.isEnabled()
    templates.close()
    window.export_view._product_buttons["travelbook-interactive"].click()
    app.processEvents()
    assert window.export_view._product_id == "travelbook-interactive"
    assert window.export_view._preview.isHidden()
    assert window.export_view._size_row_host.isHidden()
    assert window.export_view._layout_row_host.isHidden()
    assert window.export_view._manage_layouts_button.isHidden()
    window.export_view._product_buttons["travelbook"].click()
    app.processEvents()
    assert not window.export_view._size_row_host.isHidden()
    assert not window.export_view._layout_row_host.isHidden()
    assert list(window.sidebar._buttons) == [key for key, _ in NAV_ITEMS]
    window.sidebar.set_collapsed(False)
    assert 96 <= window.sidebar.width() < 220
    assert not window.sidebar._buttons["map"].icon().isNull()
    assert not window.sidebar._collapse.icon().isNull()
    assert window.sidebar._collapse.toolTip() == "Navigation einklappen"
    assert window.sidebar._collapse.width() <= 16
    window.show()
    app.processEvents()
    window._show_page("export")
    app.processEvents()
    preview = window.export_view._preview
    cover = preview._cover
    assert preview.height() > window.height() * 0.45
    assert cover.isVisible()
    assert cover.height() > 0
    assert abs(cover.width() / cover.height() - 210 / 297) < 0.04
    window.export_view._page_buttons["a4-landscape"].click()
    app.processEvents()
    assert cover.width() > cover.height()
    assert abs(cover.width() / cover.height() - 297 / 210) < 0.04
    assert window.export_view._photo_layout_id == ""
    assert not window.export_view._layout_buttons["photos_4"].isChecked()
    window.export_view._page_buttons["a4-portrait"].click()
    app.processEvents()
    assert window.export_view._photo_layout_id == "photos_4"
    assert window.export_view._layout_buttons["photos_4"].isChecked()
    window._show_page("project")
    app.processEvents()
    collapse = window.sidebar._collapse
    assert collapse.x() + collapse.width() == window.sidebar.width()
    assert abs(collapse.geometry().center().y() - window.sidebar.height() // 2) <= 1
    pool_toggle = window.timeline_view._pool_toggle
    assert pool_toggle.x() + pool_toggle.width() == window.timeline_view.width()
    window.sidebar.set_collapsed(True)
    assert window.sidebar.is_collapsed()
    assert 44 <= window.sidebar.width() <= 56
    assert window.sidebar._buttons["map"].text() == ""
    assert not window.sidebar._buttons["map"].icon().isNull()
    assert window.sidebar._collapse.toolTip() == "Navigation ausklappen"
    window.sidebar.set_collapsed(False)
    assert window.sidebar._buttons["map"].text() == "Karte"
    assert window.photos_view._pool_toggle.isCheckable()
    assert not window.photos_view._pool_toggle.isChecked()
    assert window.photos_view._pool_toggle.objectName() == "poolCollapse"
    assert window.photos_view._pool_toggle.toolTip() == "Medienpool ausklappen"
    assert window.photos_view._pool_pane.isHidden()
    assert window.photos_view._media_tabs.count() == 4
    assert window.photos_view._media_tabs.tabText(0) == "Alle"
    assert window.photos_view._media_tabs.tabText(3) == "Aussortiert"
    from PySide6.QtWidgets import QPushButton

    photo_buttons = [child.text() for child in window.photos_view.findChildren(QPushButton)]
    assert "Dubletten stapeln" in photo_buttons
    assert "Ähnliche gruppieren" in photo_buttons
    assert "Auswahl gruppieren" in photo_buttons
    assert "Qualität prüfen" in photo_buttons
    assert window.photos_view._filter_btn.text() == "Filtern"
    assert window.photos_view._filter_panel.isHidden()
    assert window.photos_view.progress.format() == "Bereit"
    assert window.photos_view._quality_btn.isEnabled()
    assert not window.photos_view._group_selected_btn.isEnabled()
    assert window.photos_view._pool_pane._tabs.count() == 4
    assert window.photos_view._pool_pane._tabs.tabText(1) == "Favoriten"
    assert not window.photos_view._show_rejected.isHidden()
    assert not window.photos_view._show_rejected.isChecked()
    assert not window.timeline_view._show_rejected.isHidden()
    assert not window.timeline_view._show_rejected.isChecked()
    assert window.timeline_view._trip_title.placeholderText() == "Titel der Reise"
    assert not window.timeline_view._trip_title.isEnabled()
    _ = app


def test_pdf_export_asks_save_as_path(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QFileDialog

    from traveljournal.services import workspace as workspace_mod
    from traveljournal.ui.main_window import MainWindow

    monkeypatch.setattr(workspace_mod, "_CONFIG_DIR", tmp_path)
    monkeypatch.setattr(workspace_mod, "_UI_CONFIG_PATH", tmp_path / "config.json")
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    suggested = tmp_path / "exports" / "reise.pdf"
    chosen = tmp_path / "Dokumente" / "Alpen"
    monkeypatch.setattr(
        QFileDialog,
        "getSaveFileName",
        lambda *args, **kwargs: (str(chosen), "PDF (*.pdf)"),
    )
    path = window.export_view._choose_pdf_destination(suggested)
    assert path == tmp_path / "Dokumente" / "Alpen.pdf"
    assert suggested.parent.is_dir()
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args, **kwargs: ("", ""))
    assert window.export_view._choose_pdf_destination(suggested) is None
    _ = app


def test_spread_overlap_shows_gutter_hairline(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from traveljournal.services import workspace as workspace_mod
    from traveljournal.ui.main_window import MainWindow

    monkeypatch.setattr(workspace_mod, "_CONFIG_DIR", tmp_path)
    monkeypatch.setattr(workspace_mod, "_UI_CONFIG_PATH", tmp_path / "config.json")
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.resize(1200, 800)
    window.show()
    window._show_page("export")
    app.processEvents()
    preview = window.export_view._preview
    preview._next.click()
    preview._next.click()
    app.processEvents()
    assert preview._indicator.text().startswith("1–2/")
    assert preview._gutter_line.isHidden()
    window.export_view._overlap_button.click()
    app.processEvents()
    assert window.export_view._spread_overlap
    assert "Über die Mitte" in window.export_view._choices_summary.text()
    assert not preview._gutter_line.isHidden()
    assert preview._gutter_line.width() == 1
    assert preview._gutter_line.height() == preview._verso.height()
    preview._prev.click()
    preview._prev.click()
    app.processEvents()
    assert preview._indicator.text() == "Cover"
    assert preview._gutter_line.isHidden()
    preview._next.click()
    preview._next.click()
    app.processEvents()
    window.export_view._product_buttons["travelbook-interactive"].click()
    app.processEvents()
    assert not window.export_view._overlap_button.isVisible()
    _ = app


def test_country_picker_adds_flag_and_shape() -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QLabel

    from traveljournal.widgets.country_picker import CountryPicker

    app = QApplication.instance() or QApplication([])
    picker = CountryPicker()
    picker.set_codes(["IT"])
    picker.search.setText("Slowenien")
    picker._add_from_field()
    app.processEvents()
    assert picker.codes() == ("IT", "SI")
    rows = [
        item.widget()
        for item in (picker._list.itemAt(index) for index in range(picker._list.count()))
        if item is not None and item.widget() is not None and item.widget().objectName() == "countryRow"
    ]
    assert len(rows) == 2
    names = [row.findChild(QLabel, "countryRowName").text() for row in rows]
    assert names == ["Italien", "Slowenien"]
    pixmaps = [label.pixmap() for row in rows for label in row.findChildren(QLabel)]
    assert sum(1 for pixmap in pixmaps if pixmap is not None and not pixmap.isNull()) >= 4
    picker.deleteLater()


def test_project_span_edits_update_duration() -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QDate
    from PySide6.QtWidgets import QApplication

    from traveljournal.services.workspace import Workspace
    from traveljournal.views.project_view import ProjectView

    app = QApplication.instance() or QApplication([])
    view = ProjectView(Workspace())
    assert not view.start_edit.isEnabled()
    assert view.duration_label.text() == "Dauer: –"
    view.start_edit.setEnabled(True)
    view.end_edit.setEnabled(True)
    view.start_edit.setDate(QDate(2025, 5, 15))
    view.end_edit.setDate(QDate(2025, 5, 16))
    app.processEvents()
    assert view.duration_label.text() == "Dauer: 2 Tage"
    view.deleteLater()


def test_summary_countries_stack_evenly_with_flag_in_outline() -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QLabel, QWidget

    from traveljournal.widgets.book_preview import _NAME_FLAG, _PageSheet

    app = QApplication.instance() or QApplication([])
    sheet = _PageSheet()
    sheet.resize(360, 520)
    sheet.set_summary(("IT", "AT", "SI"), (("3", "Tage"),))
    sheet.show()
    app.processEvents()
    items = [child for child in sheet.findChildren(QWidget) if child.objectName() == "bookCountryItem"]
    marks = [child for child in sheet.findChildren(QWidget) if child.objectName() == "bookCountryMark"]
    assert len(items) == 3
    assert len(marks) == 3
    names = [item.findChild(QLabel, "bookCountryName").text() for item in items]
    assert names == ["ITALIEN", "ÖSTERREICH", "SLOWENIEN"]
    stretches = []
    for index in range(sheet._countries_host.count()):
        widget = sheet._countries_host.itemAt(index).widget()
        if widget is not None and widget.objectName() == "bookCountryItem":
            stretches.append(sheet._countries_host.stretch(index))
    assert stretches == [0, 0, 0]
    for item in items:
        mark = item.findChild(QWidget, "bookCountryMark")
        name = item.findChild(QLabel, "bookCountryName")
        flag = item.findChild(QLabel, "bookCountryFlag")
        assert mark is not None
        assert name is not None
        assert flag is not None
        assert not flag.pixmap().isNull()
        assert flag.size() == _NAME_FLAG
        assert flag.x() >= name.x() + name.width() - 2
        assert abs(flag.y() - name.y()) <= 8
        assert name.y() - (mark.y() + mark.height()) <= 8
    sheet.close()


def test_book_preview_jumps_to_ends_and_page() -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from traveljournal.widgets.book_preview import BookPreview, leaf_index_for_page, leaves_from_snapshot

    app = QApplication.instance() or QApplication([])
    leaves = leaves_from_snapshot(None)
    assert leaf_index_for_page(leaves, 1) == 2
    assert leaf_index_for_page(leaves, 2) == 2
    assert leaf_index_for_page(leaves, 3) is None
    preview = BookPreview()
    preview.set_leaves(leaves)
    assert preview._indicator.text() == "Cover"
    assert not preview._first.isEnabled()
    preview._last.click()
    app.processEvents()
    assert preview._indicator.text().startswith("1–2/")
    assert not preview._last.isEnabled()
    preview._first.click()
    app.processEvents()
    assert preview._indicator.text() == "Cover"
    preview._goto.setValue(2)
    preview._goto_button.click()
    app.processEvents()
    assert preview._indicator.text().startswith("1–2/")
    assert preview.go_to_page(99) is False
    preview.close()
    _ = app


def test_fitted_sheet_keeps_page_aspect() -> None:
    from PySide6.QtCore import QSize

    from traveljournal.widgets.book_preview import fitted_sheet_size

    cover = fitted_sheet_size(QSize(800, 600), 210, 297, page_count=1)
    assert cover.height() == 600
    assert abs(cover.width() / cover.height() - 210 / 297) < 0.01
    spread = fitted_sheet_size(QSize(800, 600), 210, 297, page_count=2, gutter=8)
    assert abs(spread.width() / spread.height() - 210 / 297) < 0.01
    assert 2 * spread.width() + 8 <= 800
    assert spread.height() <= 600
    landscape = fitted_sheet_size(QSize(600, 800), 297, 210, page_count=1)
    assert landscape.width() == 600
    assert abs(landscape.width() / landscape.height() - 297 / 210) < 0.01


def test_section_intro_shows_country_journal_and_dates(tmp_path: Path) -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from datetime import UTC, date, datetime

    from jpeg_fixtures import write_plain_jpeg
    from PySide6.QtWidgets import QApplication, QLabel, QWidget

    from travelcore.timeline.types import TimelineEntry, TimelinePhoto, TimelineSection, TimelineSnapshot
    from traveljournal.widgets.book_preview import (
        BookPreview,
        _span_fracs,
        leaf_index_for_page,
        leaves_from_snapshot,
    )

    app = QApplication.instance() or QApplication([])
    started = datetime(2025, 7, 17, 12, 0, tzinfo=UTC)
    cover_path = write_plain_jpeg(tmp_path / "cover.jpg", size=(80, 60))
    extra_path = write_plain_jpeg(tmp_path / "extra.jpg", size=(80, 60))
    cover_photo = TimelinePhoto(
        source_file_id=1,
        filename="cover.jpg",
        path=str(cover_path),
        thumbnail_path=cover_path,
        captured_at=started,
        used_in_journal=True,
        is_cover=True,
        is_favorite=False,
        gps_latitude=47.767,
        gps_longitude=12.167,
        file_kind="photo",
    )
    extra_photo = TimelinePhoto(
        source_file_id=2,
        filename="extra.jpg",
        path=str(extra_path),
        thumbnail_path=extra_path,
        captured_at=started,
        used_in_journal=True,
        is_cover=False,
        is_favorite=False,
        gps_latitude=47.767,
        gps_longitude=12.167,
        file_kind="photo",
    )
    section = TimelineSection(
        id=1,
        kind="day",
        mode=None,
        title="Hochries Flug #2",
        notes="Start an der Bergstation, dann thermisch Richtung Chiemsee.",
        started_at=started,
        ended_at=started,
        location_name=None,
        location_from=None,
        location_to=None,
        origin="manual",
        cover_source_file_id=1,
        pin_latitude=47.767,
        pin_longitude=12.167,
        items=(cover_photo, extra_photo),
    )
    snapshot = TimelineSnapshot(
        trip_id=1,
        title="Alpen",
        origin="manual",
        countries=("DE", "IT"),
        start_date=date(2025, 7, 1),
        end_date=date(2025, 7, 31),
        entries=(TimelineEntry(started_at=started, section=section),),
    )
    leaves = leaves_from_snapshot(snapshot)
    assert leaves[1].indicator == "Titelseite"
    assert leaves[2].indicator == "1–2/4"
    assert leaves[2].first_page == 1
    intro = leaves[-1]
    assert intro.variant == "section"
    assert intro.indicator == "3–4/4"
    assert intro.first_page == 3
    assert leaf_index_for_page(leaves, 3) == 3
    assert leaf_index_for_page(leaves, 4) == 3
    assert intro.country == "DE"
    assert intro.left_title == "Hochries Flug #2"
    assert intro.left_kicker == "Tag"
    assert intro.notes.startswith("Start an der Bergstation")
    assert intro.dates == "17.07.2025"
    assert intro.span_start == 16 / 30
    assert intro.span_end == 16 / 30
    assert intro.left_image == cover_path
    assert intro.photos == (cover_path, extra_path)
    assert intro.latitude == 47.767
    assert intro.longitude == 12.167
    assert _span_fracs(started, started, date(2025, 7, 1), date(2025, 7, 31)) == (16 / 30, 16 / 30)

    stay_start = datetime(2025, 7, 17, tzinfo=UTC)
    stay_end = datetime(2025, 7, 19, tzinfo=UTC)
    stay = TimelineSection(
        id=2,
        kind="stay",
        mode=None,
        title="Chiemsee",
        notes="",
        started_at=stay_start,
        ended_at=stay_end,
        location_name=None,
        location_from=None,
        location_to=None,
        origin="manual",
        pin_latitude=47.85,
        pin_longitude=12.4,
    )
    stay_snapshot = TimelineSnapshot(
        trip_id=1,
        title="Alpen",
        origin="manual",
        countries=("DE",),
        start_date=date(2025, 7, 1),
        end_date=date(2025, 7, 31),
        entries=(TimelineEntry(started_at=stay_start, section=stay),),
    )
    stay_leaf = leaves_from_snapshot(stay_snapshot)[-1]
    assert stay_leaf.left_kicker == "Aufenthalt"
    assert stay_leaf.dates == "17.07.2025 bis 19.07.2025"
    assert stay_leaf.span_start == 16 / 30
    assert stay_leaf.span_end == 18 / 30

    preview = BookPreview()
    preview.resize(900, 640)
    preview.set_leaves(leaves)
    preview._go(len(leaves) - 1)
    preview.show()
    app.processEvents()
    sheet = preview._verso
    assert sheet._stack.currentIndex() == 4
    assert sheet._section_title.text() == "HOCHRIES FLUG #2"
    assert sheet._section_country.text() == "DEUTSCHLAND"
    assert sheet._section_dates.text() == "17.07.2025"
    assert sheet._section_notes.text().startswith("Start an der Bergstation")
    assert sheet._section_notes_box.isVisible()
    assert sheet._section_span._label == "17.07.2025"
    locators = [child for child in sheet.findChildren(QWidget) if child.objectName() == "bookSectionLocator"]
    assert len(locators) == 1
    cover = sheet.findChild(QLabel, "bookSectionCover")
    assert cover is not None
    assert cover.isVisible()
    assert not cover.pixmap().isNull()
    left = sheet.findChild(QWidget, "bookSectionPlaceLeft")
    assert left is not None
    assert cover.x() >= left.x() + left.width() - 4
    flag = sheet.findChild(QLabel, "bookSectionFlag")
    assert flag is not None
    assert not flag.pixmap().isNull()
    assert flag.x() < cover.x()
    assert flag.y() >= locators[0].y()
    source = cover._source
    shown = cover.pixmap()
    assert abs(shown.width() / shown.height() - source.width() / source.height()) < 0.05
    assert preview._recto._stack.currentIndex() == 5
    assert len(preview._recto._photo_canvas.elements()) == 2

    preview.set_leaves(leaves_from_snapshot(stay_snapshot))
    preview._go(len(preview._leaves) - 1)
    app.processEvents()
    assert preview._verso._section_notes.text() == ""
    assert preview._verso._section_notes_box.isVisible()
    assert preview._verso._section_span._label == "17.07.2025 bis 19.07.2025"
    assert preview._verso._section_dates.text() == "17.07.2025 bis 19.07.2025"
    preview.close()


def test_photo_page_canvas_add_and_delete(tmp_path: Path) -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from jpeg_fixtures import write_plain_jpeg
    from PySide6.QtWidgets import QApplication

    from travelcore.export.document import add_photo_element, remove_element
    from travelcore.export.geometry import Frame
    from traveljournal.widgets.photo_canvas import BookMedia, PhotoPageCanvas

    app = QApplication.instance() or QApplication([])
    path = write_plain_jpeg(tmp_path / "shot.jpg", size=(80, 60))
    media = (BookMedia(source_file_id=7, thumbnail_path=path, width=80, height=60),)
    canvas = PhotoPageCanvas()
    canvas.resize(400, 560)
    canvas.set_editable(True)
    canvas.set_page((), media)
    canvas._set_elements(add_photo_element((), 7, frame=Frame(10, 10, 40, 30)))
    assert len(canvas.elements()) == 1
    assert canvas.elements()[0].source_file_id == 7
    canvas._set_elements(remove_element(canvas.elements(), canvas.elements()[0].id))
    assert canvas.elements() == ()
    canvas.close()
    _ = app


def test_photo_page_canvas_uses_letterboxed_thumb_aspect() -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtGui import QColor, QPainter, QPixmap
    from PySide6.QtWidgets import QApplication

    from travelcore.export.geometry import Crop, map_rect_to_contained, source_rect
    from traveljournal.widgets.photo_canvas import BookMedia, _preview_image_size

    app = QApplication.instance() or QApplication([])
    fill = QColor(18, 21, 28)
    landscape = QPixmap(32, 32)
    landscape.fill(fill)
    painter = QPainter(landscape)
    painter.fillRect(0, 4, 32, 24, QColor(200, 40, 40))
    painter.end()
    portrait = QPixmap(32, 32)
    portrait.fill(fill)
    painter = QPainter(portrait)
    painter.fillRect(4, 0, 24, 32, QColor(40, 40, 200))
    painter.end()
    media = BookMedia(source_file_id=1, thumbnail_path=Path("."), width=80, height=60)
    assert _preview_image_size(landscape, media) == (80.0, 60.0)
    assert _preview_image_size(portrait, media) == (60.0, 80.0)
    sx, sy, sw, sh = source_rect(80, 60, 100, 100, Crop())
    _mx, _my, mw, mh = map_rect_to_contained(80, 60, 32, 32, sx, sy, sw, sh)
    assert abs(mw / mh - 1.0) < 1e-6
    _ = app


def test_photo_page_canvas_nudge_zoom_and_angle(tmp_path: Path) -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from jpeg_fixtures import write_plain_jpeg
    from PySide6.QtWidgets import QApplication

    from travelcore.export.document import add_photo_element
    from travelcore.export.geometry import Frame
    from traveljournal.widgets.photo_canvas import BookMedia, PhotoPageCanvas

    app = QApplication.instance() or QApplication([])
    path = write_plain_jpeg(tmp_path / "shot.jpg", size=(80, 60))
    media = (BookMedia(source_file_id=7, thumbnail_path=path, width=80, height=60),)
    canvas = PhotoPageCanvas()
    canvas.resize(400, 560)
    canvas.set_editable(True)
    canvas.set_page(add_photo_element((), 7, frame=Frame(10, 10, 40, 30)), media)
    item = canvas._items()[0]
    item.setSelected(True)
    item._nudge_angle(3)
    canvas._commit_item(item)
    assert canvas.elements()[0].crop.angle == 3
    item._nudge_scale(1)
    canvas._commit_item(item)
    assert canvas.elements()[0].crop.scale > 1.0
    canvas.close()
    _ = app


def test_app_window_title_includes_version() -> None:
    from traveljournal.__about__ import app_window_title

    assert app_window_title() == "Reisetagebuch R3.1.0"
    assert app_window_title("Alpen 2025") == "Reisetagebuch R3.1.0 - Alpen 2025"
    assert app_window_title("  ") == "Reisetagebuch R3.1.0"


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


def test_source_sync_dialog_defaults_to_timeline() -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QLabel

    from travelcore.media.purge import SourceSyncPlan
    from traveljournal.views.import_view import SourceSyncDialog

    app = QApplication.instance() or QApplication([])
    plan = SourceSyncPlan(
        new_count=2,
        missing_count=1,
        present_count=4,
        new_names=("neu.jpg", "spur.gpx"),
        missing_names=("alt.jpg",),
    )
    dialog = SourceSyncDialog(plan)
    labels = [widget.text() for widget in dialog.findChildren(QLabel)]
    assert any("2 neue Dateien" in text for text in labels)
    assert any("nicht mehr im Ordner" in text for text in labels)
    assert dialog._timeline.isChecked()
    assert not dialog.park_new_media()
    dialog._pool.click()
    assert dialog.park_new_media()
    _ = app


def test_source_sync_dialog_hides_destination_without_new_files() -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from travelcore.media.purge import SourceSyncPlan
    from traveljournal.views.import_view import SourceSyncDialog

    app = QApplication.instance() or QApplication([])
    plan = SourceSyncPlan(
        new_count=0,
        missing_count=2,
        present_count=1,
        new_names=(),
        missing_names=("a.jpg", "b.jpg"),
    )
    dialog = SourceSyncDialog(plan)
    assert dialog._pool.isHidden()
    assert not dialog.park_new_media()
    _ = app


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


def test_import_view_thumb_zoom_scales_preview(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from traveljournal.services import workspace as workspace_mod
    from traveljournal.services.workspace import Workspace
    from traveljournal.views.import_view import ImportView
    from traveljournal.widgets.thumb_zoom import import_preview_size

    monkeypatch.setattr(workspace_mod, "_UI_CONFIG_PATH", tmp_path / "config.json")
    app = QApplication.instance() or QApplication([])
    workspace = Workspace()
    view = ImportView(workspace)
    assert view._preview_image.minimumHeight() == import_preview_size(100)
    view._on_thumb_zoom(50)
    assert view._preview_image.minimumHeight() == import_preview_size(50)
    assert view._preview_card.maximumWidth() == 380
    view._on_thumb_zoom(200)
    assert view._preview_image.minimumHeight() == import_preview_size(200)
    assert view._preview_card.maximumWidth() > 380
    assert workspace.import_thumb_zoom() == 200
    _ = app


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


def test_empty_section_dialog_shows_am_or_von_bis() -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from datetime import date

    from PySide6.QtCore import QDate
    from PySide6.QtWidgets import QApplication

    from travelcore.timeline.sections import KIND_DAY, KIND_STAY
    from traveljournal.views.timeline_view import EmptySectionDialog

    app = QApplication.instance() or QApplication([])
    dialog = EmptySectionDialog(date(2025, 8, 20))
    assert dialog.kind.currentData() == KIND_DAY
    assert not dialog.date_edit.isHidden()
    assert dialog.from_edit.isHidden()
    assert dialog.until_edit.isHidden()
    values = dialog.values()
    assert values["started_at"].date() == date(2025, 8, 20)
    assert values["ended_at"] == values["started_at"]
    dialog.kind.setCurrentIndex(1)
    assert dialog.kind.currentData() == KIND_STAY
    assert dialog.date_edit.isHidden()
    assert not dialog.from_edit.isHidden()
    assert not dialog.until_edit.isHidden()
    dialog.from_edit.setDate(QDate(2025, 8, 1))
    dialog.until_edit.setDate(QDate(2025, 8, 10))
    values = dialog.values()
    assert values["started_at"].date() == date(2025, 8, 1)
    assert values["ended_at"].date() == date(2025, 8, 10)
    gapped = EmptySectionDialog(date(2025, 5, 15), until=date(2025, 5, 19))
    assert gapped.date_edit.date() == QDate(2025, 5, 15)
    assert gapped.from_edit.date() == QDate(2025, 5, 15)
    assert gapped.until_edit.date() == QDate(2025, 5, 19)
    gapped.kind.setCurrentIndex(1)
    stay = gapped.values()
    assert stay["started_at"].date() == date(2025, 5, 15)
    assert stay["ended_at"].date() == date(2025, 5, 19)
    _ = app


def test_settings_dialog_has_scrollbar() -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QScrollArea

    from travelcore.project_settings import ProjectSettings
    from traveljournal.views.settings_dialog import SettingsDialog

    app = QApplication.instance() or QApplication([])
    dialog = SettingsDialog(ProjectSettings())
    dialog.resize(560, 280)
    dialog.show()
    app.processEvents()
    assert isinstance(dialog._scroll, QScrollArea)
    assert dialog._scroll.widgetResizable()
    assert dialog._scroll.verticalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAsNeeded
    body = dialog._scroll.widget()
    assert body is not None
    assert body.sizeHint().height() > 280
    _ = app


def test_section_span_dialog_tag_vs_range() -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from datetime import UTC, date, datetime

    from PySide6.QtWidgets import QApplication

    from travelcore.timeline.sections import KIND_DAY, KIND_STAY
    from travelcore.timeline.types import TimelineEntry, TimelineSection
    from traveljournal.views.timeline_view import EntryWidget, SectionSpanDialog

    app = QApplication.instance() or QApplication([])
    noon = datetime(2025, 5, 14, 12, 0, tzinfo=UTC)
    tag_dialog = SectionSpanDialog(KIND_DAY, noon, noon)
    assert tag_dialog.windowTitle() == "Datum"
    assert not tag_dialog.date_edit.isHidden()
    assert tag_dialog.from_edit.isHidden()
    assert tag_dialog.until_edit.isHidden()
    tag_dialog.show()
    app.processEvents()
    assert tag_dialog.width() >= 360
    assert tag_dialog.date_edit.width() >= 160
    started, ended = tag_dialog.span()
    assert started.date() == date(2025, 5, 14)
    assert ended == started
    stay_dialog = SectionSpanDialog(
        KIND_STAY,
        datetime(2025, 8, 1, tzinfo=UTC),
        datetime(2025, 8, 10, tzinfo=UTC),
    )
    assert stay_dialog.windowTitle() == "Zeitraum"
    assert stay_dialog.date_edit.isHidden()
    assert not stay_dialog.from_edit.isHidden()
    assert not stay_dialog.until_edit.isHidden()
    stay_dialog.show()
    app.processEvents()
    assert stay_dialog.width() >= 360
    started, ended = stay_dialog.span()
    assert started.date() == date(2025, 8, 1)
    assert ended.date() == date(2025, 8, 10)
    tag_section = TimelineSection(
        id=3,
        kind=KIND_DAY,
        mode=None,
        title="Tag",
        notes=None,
        started_at=noon,
        ended_at=noon,
        location_name=None,
        location_from=None,
        location_to=None,
        origin="manual",
    )
    stay_section = TimelineSection(
        id=4,
        kind=KIND_STAY,
        mode=None,
        title="Aufenthalt",
        notes=None,
        started_at=noon,
        ended_at=noon,
        location_name=None,
        location_from=None,
        location_to=None,
        origin="manual",
    )
    tag_labels = [
        action.text()
        for action in EntryWidget(TimelineEntry(started_at=noon, section=tag_section))._entry_menu.actions()
    ]
    stay_labels = [
        action.text()
        for action in EntryWidget(TimelineEntry(started_at=noon, section=stay_section))._entry_menu.actions()
    ]
    assert "Datum…" in tag_labels
    assert "Zeitraum…" not in tag_labels
    assert "Zeitraum…" in stay_labels
    assert "Datum…" not in stay_labels
    _ = app


def test_gallery_cluster_hotspots() -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from pathlib import Path

    from PySide6.QtCore import QPoint, QRect
    from PySide6.QtWidgets import QApplication

    from travelcore.media.gallery import GalleryItem
    from traveljournal.widgets.gallery import cluster_hotspots, hit_cluster

    app = QApplication.instance() or QApplication([])
    item = GalleryItem(
        source_file_id=1,
        path="foto.jpg",
        filename="foto.jpg",
        extension=".jpg",
        captured_at=None,
        timezone_unknown=True,
        gps_latitude=None,
        gps_longitude=None,
        camera=None,
        is_favorite=False,
        used_in_journal=False,
        thumbnail_path=Path("missing.jpg"),
        stack_id=4,
        stack_size=3,
        is_stack_key=True,
        group_id=8,
        group_size=5,
        is_group_key=True,
        group_status="accepted",
    )
    cell = QRect(0, 0, 184, 214)
    spots = cluster_hotspots(cell, item)
    assert set(spots) == {"stack", "group"}
    assert hit_cluster(cell, item, spots["stack"].center()) == "stack"
    assert hit_cluster(cell, item, spots["group"].center()) == "group"
    assert hit_cluster(cell, item, QPoint(8, 80)) is None
    from dataclasses import replace

    from traveljournal.widgets.gallery import group_badge_color

    suggested = replace(item, source_file_id=2, group_status="suggested", is_group_key=False)
    other = replace(suggested, source_file_id=3, group_id=9, group_size=2)
    assert group_badge_color(item).name() == "#2eb8a0"
    assert group_badge_color(suggested).name() == group_badge_color(
        replace(suggested, source_file_id=4)
    ).name()
    assert group_badge_color(suggested).name() != group_badge_color(other).name()
    _ = app


def test_gallery_quality_ampel() -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from dataclasses import replace
    from pathlib import Path

    from PySide6.QtCore import QRect, Qt
    from PySide6.QtWidgets import QApplication

    from travelcore.media.gallery import GalleryItem
    from traveljournal.widgets.gallery import GalleryModel, quality_hotspot, quality_light_color

    app = QApplication.instance() or QApplication([])
    item = GalleryItem(
        source_file_id=1,
        path="foto.jpg",
        filename="foto.jpg",
        extension=".jpg",
        captured_at=None,
        timezone_unknown=True,
        gps_latitude=None,
        gps_longitude=None,
        camera=None,
        is_favorite=False,
        used_in_journal=False,
        thumbnail_path=Path("missing.jpg"),
        quality_light="green",
        quality_tooltip="Qualität gut",
    )
    cell = QRect(0, 0, 184, 214)
    disc = quality_hotspot(cell)
    assert disc.x() < cell.center().x()
    assert quality_light_color(item.quality_light).name() == "#2eb8a0"
    assert quality_light_color("yellow").name() == "#d4a017"
    assert quality_light_color("red").name() == "#d94a4a"
    assert quality_light_color(None) is None
    model = GalleryModel()
    model.set_items(
        [
            item,
            replace(
                item,
                source_file_id=2,
                quality_light="red",
                quality_tooltip="Qualität schwach\nAuflösung schwach",
            ),
        ]
    )
    assert model.data(model.index(0, 0), Qt.ItemDataRole.ToolTipRole) == "Qualität gut"
    assert "Auflösung schwach" in model.data(model.index(1, 0), Qt.ItemDataRole.ToolTipRole)
    _ = app


def test_gallery_context_menu_group_actions() -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from pathlib import Path

    from PySide6.QtWidgets import QApplication

    from travelcore.media.gallery import GalleryItem
    from traveljournal.widgets.gallery import GalleryView

    app = QApplication.instance() or QApplication([])

    def _item(source_id: int, name: str, *, group_id: int | None = None) -> GalleryItem:
        return GalleryItem(
            source_file_id=source_id,
            path=name,
            filename=name,
            extension=".jpg",
            captured_at=None,
            timezone_unknown=True,
            gps_latitude=None,
            gps_longitude=None,
            camera=None,
            is_favorite=False,
            used_in_journal=False,
            thumbnail_path=Path("missing.jpg"),
            group_id=group_id,
            group_size=2 if group_id is not None else 0,
            group_status="suggested" if group_id is not None else None,
        )

    first = _item(1, "a.jpg")
    second = _item(2, "b.jpg", group_id=8)
    view = GalleryView()
    view.set_multi_select(True)
    view.set_items([first, second])
    view.select_by_source_ids({1})
    menu, group_act, dissolve_act, map_act = view._build_context_menu(first)
    assert group_act.text() == "Gruppieren"
    assert not group_act.isEnabled()
    assert not dissolve_act.isEnabled()
    assert map_act is None
    view.select_by_source_ids({1, 2})
    menu, group_act, dissolve_act, _map_act = view._build_context_menu(second)
    assert group_act.isEnabled()
    assert dissolve_act.isEnabled()
    _ = menu
    _ = app


def test_cluster_inspector_browses_group() -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from dataclasses import replace
    from pathlib import Path
    from unittest.mock import MagicMock

    from PySide6.QtWidgets import QApplication

    from travelcore.media.gallery import GalleryItem
    from traveljournal.widgets.media_inspector import MediaInspectorWindow

    app = QApplication.instance() or QApplication([])

    def _item(source_id: int, name: str, *, grouped: bool = False) -> GalleryItem:
        return GalleryItem(
            source_file_id=source_id,
            path=name,
            filename=name,
            extension=".jpg",
            captured_at=None,
            timezone_unknown=True,
            gps_latitude=None,
            gps_longitude=None,
            camera=None,
            is_favorite=False,
            used_in_journal=False,
            thumbnail_path=Path("missing.jpg"),
            group_id=8 if grouped else None,
            group_size=2 if grouped else 0,
            group_status="suggested" if grouped else None,
        )

    first = _item(1, "a.jpg", grouped=True)
    sibling = _item(2, "b.jpg", grouped=True)
    other = _item(3, "c.jpg")
    workspace = MagicMock()
    workspace.inspector_size.return_value = (800, 600)
    workspace.inspector_maximized.return_value = False
    workspace.cluster_items.return_value = [first, sibling]
    window = MediaInspectorWindow(
        first,
        items=[first, sibling, other],
        workspace=workspace,
        cluster_type="group",
        cluster_id=8,
        cluster_members=[first, sibling],
    )
    assert "a.jpg" in window.windowTitle()
    assert "Gruppe 1 von 2" in window.windowTitle()
    assert not window._key_button.isChecked()
    assert not window.extra_host.isVisible()
    window._key_button.click()
    workspace.set_group_keys.assert_not_called()
    window.step_cluster(1)
    assert "b.jpg" in window.windowTitle()
    assert "Gruppe 2 von 2" in window.windowTitle()
    window.step(1)
    assert "c.jpg" in window.windowTitle()
    assert "Gruppe" not in window.windowTitle()
    window.close()

    keyed = replace(first, is_group_key=True, group_status="accepted")
    other_key = replace(_item(4, "d.jpg", grouped=True), is_group_key=True, group_status="accepted")
    hidden = replace(sibling, group_status="accepted")
    workspace.cluster_items.return_value = [keyed, hidden, other_key]
    accepted = MediaInspectorWindow(
        keyed,
        items=[keyed, hidden, other_key, other],
        workspace=workspace,
        cluster_type="group",
        cluster_id=8,
        cluster_members=[keyed, hidden, other_key],
    )
    accepted.step_cluster(1)
    assert "b.jpg" in accepted.windowTitle()
    accepted.step(1)
    assert "d.jpg" in accepted.windowTitle()
    accepted.step(1)
    assert "c.jpg" in accepted.windowTitle()
    accepted.step(-1)
    assert "d.jpg" in accepted.windowTitle()
    accepted.close()

    only_one_in_gallery = MediaInspectorWindow(
        keyed,
        items=[keyed, other],
        workspace=workspace,
        cluster_type="group",
        cluster_id=8,
        cluster_members=[keyed, hidden, other_key],
    )
    assert only_one_in_gallery._image.cluster_badge_kinds() == ("group",)
    only_one_in_gallery.step(1)
    assert "d.jpg" in only_one_in_gallery.windowTitle()
    only_one_in_gallery.close()
    _ = app


def test_cluster_inspector_stack_ignores_vertical() -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from pathlib import Path
    from unittest.mock import MagicMock

    from PySide6.QtWidgets import QApplication

    from travelcore.media.gallery import GalleryItem
    from traveljournal.widgets.media_inspector import MediaInspectorWindow

    app = QApplication.instance() or QApplication([])

    def _item(source_id: int, name: str, *, stacked: bool = False, key: bool = False) -> GalleryItem:
        return GalleryItem(
            source_file_id=source_id,
            path=name,
            filename=name,
            extension=".jpg",
            captured_at=None,
            timezone_unknown=True,
            gps_latitude=None,
            gps_longitude=None,
            camera=None,
            is_favorite=False,
            used_in_journal=False,
            thumbnail_path=Path("missing.jpg"),
            stack_id=5 if stacked else None,
            stack_size=2 if stacked else 0,
            is_stack_key=key,
        )

    key_photo = _item(1, "a.jpg", stacked=True, key=True)
    copy = _item(2, "b.jpg", stacked=True)
    solo = _item(3, "c.jpg")
    workspace = MagicMock()
    workspace.inspector_size.return_value = (800, 600)
    workspace.inspector_maximized.return_value = False
    workspace.cluster_items.return_value = [key_photo, copy]
    window = MediaInspectorWindow(
        key_photo,
        items=[key_photo, copy, solo],
        workspace=workspace,
        cluster_type="stack",
        cluster_id=5,
        cluster_members=[key_photo, copy],
    )
    assert "a.jpg" in window.windowTitle()
    assert window._image.cluster_badge_kinds() == ("stack",)
    assert window._cluster_prev.isHidden()
    window.step_cluster(1)
    assert "a.jpg" in window.windowTitle()
    window.step(1)
    assert "c.jpg" in window.windowTitle()
    window.close()
    _ = app


def test_cluster_inspector_space_toggles_key() -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from pathlib import Path
    from unittest.mock import MagicMock

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication

    from travelcore.media.gallery import GalleryItem
    from traveljournal.widgets.media_inspector import MediaInspectorWindow

    app = QApplication.instance() or QApplication([])

    def _item(source_id: int, name: str) -> GalleryItem:
        return GalleryItem(
            source_file_id=source_id,
            path=name,
            filename=name,
            extension=".jpg",
            captured_at=None,
            timezone_unknown=True,
            gps_latitude=None,
            gps_longitude=None,
            camera=None,
            is_favorite=False,
            used_in_journal=False,
            thumbnail_path=Path("missing.jpg"),
            group_id=8,
            group_size=2,
            group_status="suggested",
        )

    first = _item(1, "a.jpg")
    hidden = _item(2, "b.jpg")
    workspace = MagicMock()
    workspace.inspector_size.return_value = (800, 600)
    workspace.inspector_maximized.return_value = False
    workspace.cluster_items.return_value = [first, hidden]
    window = MediaInspectorWindow(
        first,
        items=[first],
        workspace=workspace,
        cluster_type="group",
        cluster_id=8,
        cluster_members=[first, hidden],
    )
    window._arm_key_clicks()
    window._rating_buttons["favorite"].setFocus()
    QTest.keyClick(window._rating_buttons["favorite"], Qt.Key.Key_Space)
    workspace.set_group_keys.assert_called_once_with(8, [1])
    window.close()
    _ = app


def test_media_inspector_skips_rejected_unless_checked() -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from pathlib import Path

    from PySide6.QtWidgets import QApplication

    from travelcore.media.gallery import GalleryItem
    from traveljournal.widgets.media_inspector import MediaInspectorWindow

    app = QApplication.instance() or QApplication([])

    class StubWorkspace:
        def __init__(self) -> None:
            self.flag = False

        def inspector_size(self) -> tuple[int, int]:
            return (800, 600)

        def inspector_maximized(self) -> bool:
            return False

        def inspector_show_rejected(self) -> bool:
            return self.flag

        def set_inspector_show_rejected(self, visible: bool) -> None:
            self.flag = bool(visible)

        def set_inspector_geometry(self, width: int, height: int, *, maximized: bool = False) -> None:
            return None

    def _item(source_id: int, name: str, *, rejected: bool = False) -> GalleryItem:
        return GalleryItem(
            source_file_id=source_id,
            path=name,
            filename=name,
            extension=".jpg",
            captured_at=None,
            timezone_unknown=True,
            gps_latitude=None,
            gps_longitude=None,
            camera=None,
            is_favorite=False,
            used_in_journal=False,
            thumbnail_path=Path("missing.jpg"),
            sort_status="rejected" if rejected else None,
        )

    first = _item(1, "a.jpg")
    dropped = _item(2, "b.jpg", rejected=True)
    third = _item(3, "c.jpg")
    workspace = StubWorkspace()
    window = MediaInspectorWindow(first, items=[first, dropped, third], workspace=workspace)
    assert not window._show_rejected.isChecked()
    window.step(1)
    assert window.item().filename == "c.jpg"
    window._show_rejected.setChecked(True)
    assert workspace.flag is True
    window.step(-1)
    assert window.item().filename == "b.jpg"
    window._show_rejected.setChecked(False)
    assert workspace.flag is False
    assert window.item().filename == "c.jpg"
    window.close()
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


def test_thumb_zoom_slider_marks_default() -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from traveljournal.widgets.thumb_zoom import (
        DEFAULT_THUMB_ZOOM,
        ThumbZoomSlider,
        clamp_thumb_zoom,
        gallery_icon_size,
        import_preview_size,
    )

    app = QApplication.instance() or QApplication([])
    assert clamp_thumb_zoom(None) == DEFAULT_THUMB_ZOOM
    assert clamp_thumb_zoom(12) == 50
    assert clamp_thumb_zoom(147) == 145
    assert clamp_thumb_zoom(400) == 200
    assert gallery_icon_size(DEFAULT_THUMB_ZOOM) == 168
    assert gallery_icon_size(50) == 84
    assert import_preview_size(DEFAULT_THUMB_ZOOM) == 240
    assert import_preview_size(50) == 120
    assert import_preview_size(200) == 480
    widget = ThumbZoomSlider()
    assert widget.value() == DEFAULT_THUMB_ZOOM
    assert widget._slider._default == DEFAULT_THUMB_ZOOM
    widget.set_value(150)
    assert widget.value() == 150
    assert widget._value.text() == "150 %"
    _ = app


def test_pool_source_id_payload_roundtrip() -> None:
    from traveljournal.widgets.gallery import decode_pool_source_ids, encode_pool_source_ids

    assert decode_pool_source_ids(encode_pool_source_ids([3, 3, 1, 2])) == [3, 1, 2]
    assert decode_pool_source_ids(b"not-json") == []
    assert decode_pool_source_ids(b"{}") == []


def test_gallery_wraps_to_multiple_columns_when_wide() -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from datetime import UTC, datetime

    from PySide6.QtWidgets import QApplication

    from travelcore.media.gallery import GalleryItem
    from traveljournal.widgets.gallery import GalleryView

    app = QApplication.instance() or QApplication([])
    stamp = datetime(2025, 5, 15, 8, 0, tzinfo=UTC)

    def item(source_file_id: int) -> GalleryItem:
        return GalleryItem(
            source_file_id=source_file_id,
            path=f"{source_file_id}.jpg",
            filename=f"{source_file_id}.jpg",
            extension=".jpg",
            captured_at=stamp,
            timezone_unknown=False,
            gps_latitude=None,
            gps_longitude=None,
            camera=None,
            is_favorite=False,
            used_in_journal=False,
            thumbnail_path=Path("."),
        )

    view = GalleryView()
    view.set_items([item(1), item(2), item(3), item(4)])
    view.setFixedSize(420, 700)
    view.show()
    app.processEvents()
    xs = {view.visualRect(view.model().index(row, 0)).x() for row in range(4)}
    assert len(xs) >= 2
    default = view.gridSize()
    view.set_thumb_zoom(50)
    assert view.gridSize().width() < default.width()
    view.set_thumb_zoom(200)
    assert view.gridSize().width() > default.width()
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
    assert widget._track_tabs.count() == 4
    assert widget._track_tabs.tabText(3) == "Aussortiert"
    assert not widget._track_tabs.isHidden()
    assert widget.track_gallery._show_ratings is True
    assert widget.entry_kind() == "day"
    assert widget._kind_combo.currentData() == "day"
    assert not widget._cover_thumb.isHidden()
    assert widget._cover_thumb.pixmap() is None or widget._cover_thumb.pixmap().isNull()
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
    assert widget._cover_thumb.width() == 168
    _ = app


def test_entry_widget_falls_back_to_first_photo(tmp_path: Path) -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from datetime import UTC, datetime

    from jpeg_fixtures import write_plain_jpeg
    from PySide6.QtWidgets import QApplication

    from travelcore.timeline.types import TimelineDay, TimelineEntry, TimelinePhoto
    from traveljournal.views.timeline_view import EntryWidget

    app = QApplication.instance() or QApplication([])
    thumb = write_plain_jpeg(tmp_path / "erstes.jpg", size=(48, 48))
    stamp = datetime(2025, 5, 15, 8, 0, tzinfo=UTC)
    photo = TimelinePhoto(
        source_file_id=1,
        filename="erstes.jpg",
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
        cover_source_file_id=None,
        photos=(photo,),
    )
    widget = EntryWidget(TimelineEntry(started_at=stamp, leftover_day=day))
    assert not widget._cover_thumb.pixmap().isNull()
    _ = app


def test_entry_widget_header_is_compact() -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from datetime import UTC, datetime

    from PySide6.QtWidgets import QApplication, QLabel

    from travelcore.timeline.types import TimelineDay, TimelineEntry, TimelinePhoto, TimelineSection
    from traveljournal.views.timeline_view import EntryWidget

    app = QApplication.instance() or QApplication([])
    start = datetime(2024, 10, 31, 8, 0, tzinfo=UTC)
    end = datetime(2024, 11, 1, 18, 0, tzinfo=UTC)
    stay = TimelineSection(
        id=3,
        kind="stay",
        mode=None,
        title="Bozen",
        notes="Notiz",
        started_at=start,
        ended_at=end,
        location_name=None,
        location_from=None,
        location_to=None,
        origin="manual",
    )
    widget = EntryWidget(TimelineEntry(started_at=start, section=stay))
    assert widget._date_label.text() == "31.10.2024 - 01.11.2024"
    assert widget.title_edit.text() == "Bozen"
    assert widget._kind_combo.currentData() == "stay"
    widget.show()
    widget.resize(720, 420)
    app.processEvents()
    assert widget.title_edit.y() < widget._kind_combo.y()
    assert abs(widget._date_label.y() - widget._kind_combo.y()) <= 8
    transfer = TimelineSection(
        id=5,
        kind="movement",
        mode=None,
        title="Fahrt",
        notes=None,
        started_at=start,
        ended_at=end,
        location_name=None,
        location_from=None,
        location_to=None,
        origin="manual",
    )
    move = EntryWidget(TimelineEntry(started_at=start, section=transfer))
    move.show()
    move.resize(720, 420)
    app.processEvents()
    assert move.title_edit.y() < move._kind_combo.y()
    assert move._link_strip is not None
    assert move._kind_combo.y() < move._link_strip.y()
    labels = [child.text() for child in widget.findChildren(QLabel)]
    assert "Titel" in labels
    assert all("mitmarkiert" not in text for text in labels)
    assert any(text == "Tagebucheintrag" for text in labels)
    assert any(text == "Keine Medien" for text in labels)
    assert widget._kind_combo.maxVisibleItems() == 3
    widget._kind_combo.showPopup()
    app.processEvents()
    view = widget._kind_combo.view()
    assert view is not None
    assert view.height() >= 3 * max(view.sizeHintForRow(0), 1) - 2
    widget._kind_combo.hidePopup()
    caption_names = {
        child.objectName()
        for child in widget.findChildren(QLabel)
        if child.text() in {"Titel", "Tagebucheintrag", "Keine Medien"}
    }
    assert caption_names == {"fieldCaption"}

    tag = TimelineSection(
        id=4,
        kind="day",
        mode=None,
        title="Ausflug",
        notes=None,
        started_at=start,
        ended_at=start,
        location_name=None,
        location_from=None,
        location_to=None,
        origin="manual",
    )
    day_card = EntryWidget(TimelineEntry(started_at=start, section=tag))
    assert day_card._date_label.text() == "31.10.2024"
    leftover = EntryWidget(
        TimelineEntry(
            started_at=start,
            leftover_day=TimelineDay(
                id=1,
                day_index=0,
                date=start.date(),
                title=None,
                notes=None,
                origin="auto",
                photos=(
                    TimelinePhoto(
                        source_file_id=1,
                        filename="foto.jpg",
                        path="foto.jpg",
                        thumbnail_path=Path("."),
                        captured_at=start,
                        used_in_journal=False,
                        is_cover=False,
                        is_favorite=False,
                        gps_latitude=None,
                        gps_longitude=None,
                        file_kind="photo",
                    ),
                ),
            ),
        )
    )
    assert leftover._date_label.text() == "31.10.2024"
    media = [child for child in leftover.findChildren(QLabel) if child.text().startswith("Medien")]
    assert [child.text() for child in media] == ["Medien (1)"]
    assert all(child.objectName() == "fieldCaption" for child in media)
    _ = app


def test_entry_widget_section_has_to_map_button() -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from datetime import UTC, datetime

    from PySide6.QtWidgets import QApplication, QCheckBox, QPushButton

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
    menu = widget.findChild(QPushButton, "entryMenuButton")
    assert button is not None
    assert button.isEnabled()
    assert menu is not None
    assert menu.text() == "Menü"
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
    assert leftover.findChild(QCheckBox, "entryHide") is None
    day_keys: list[str] = []
    leftover.open_on_map.connect(day_keys.append)
    day_btn.click()
    assert day_keys == ["day:1"]
    _ = app


def test_entry_widget_hide_toggle_disables_to_map() -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from datetime import UTC, datetime

    from PySide6.QtWidgets import QApplication, QCheckBox, QPushButton

    from travelcore.timeline.types import TimelineEntry, TimelineSection
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
    toggle = widget.findChild(QCheckBox, "entryHide")
    button = widget.findChild(QPushButton, "entryToMap")
    assert toggle is not None
    assert button is not None
    assert toggle.sizeHint().height() >= 22
    assert 40 <= toggle.sizeHint().width() <= 56
    assert toggle.text() == ""
    assert toggle.isChecked()
    assert button.isEnabled()
    assert widget.property("tripHidden") == "false"
    flags: list[bool] = []
    widget.hidden_changed.connect(flags.append)
    toggle.click()
    assert flags == [True]
    assert widget.is_hidden()
    assert not toggle.isChecked()
    assert not button.isEnabled()
    assert widget.property("tripHidden") == "true"
    hidden_section = TimelineSection(
        id=8,
        kind="stay",
        mode=None,
        title="Meran",
        notes=None,
        started_at=stamp,
        ended_at=stamp,
        location_name=None,
        location_from=None,
        location_to=None,
        origin="manual",
        hidden=True,
    )
    hidden_widget = EntryWidget(TimelineEntry(started_at=stamp, section=hidden_section))
    hidden_toggle = hidden_widget.findChild(QCheckBox, "entryHide")
    assert hidden_toggle is not None
    assert not hidden_toggle.isChecked()
    assert hidden_widget.is_hidden()
    _ = app


def test_entry_widget_thumbnail_opens_section_detail_on_map() -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from datetime import UTC, datetime

    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    from travelcore.timeline.types import TimelineEntry, TimelinePhoto, TimelineSection
    from traveljournal.views.timeline_view import EntryWidget

    app = QApplication.instance() or QApplication([])
    stamp = datetime(2025, 5, 15, 8, 0, tzinfo=UTC)
    located = TimelinePhoto(
        source_file_id=9,
        filename="foto.jpg",
        path="foto.jpg",
        thumbnail_path=Path("."),
        captured_at=stamp,
        used_in_journal=False,
        is_cover=False,
        is_favorite=False,
        gps_latitude=46.5,
        gps_longitude=11.3,
        file_kind="photo",
    )
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
        items=(located,),
    )
    widget = EntryWidget(TimelineEntry(started_at=stamp, section=section))
    assert widget.gallery.contextMenuPolicy() == Qt.ContextMenuPolicy.CustomContextMenu
    items = widget.gallery.items()
    assert len(items) == 1
    assert widget._item_can_open_on_map(items[0])
    opened: list[tuple[str, int]] = []
    widget.open_media_on_map.connect(lambda key, sid: opened.append((key, sid)))
    widget.gallery.map_requested.emit(items[0])
    assert opened == [("section:7", 9)]

    blank = TimelinePhoto(
        source_file_id=10,
        filename="ohne.jpg",
        path="ohne.jpg",
        thumbnail_path=Path("."),
        captured_at=stamp,
        used_in_journal=False,
        is_cover=False,
        is_favorite=False,
        gps_latitude=None,
        gps_longitude=None,
        file_kind="photo",
    )
    unsaved = TimelineSection(
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
        items=(located, blank),
    )
    pending = EntryWidget(TimelineEntry(started_at=stamp, section=unsaved))
    pending_items = pending.gallery.items()
    assert pending_items
    assert not pending._item_can_open_on_map(pending_items[0])
    _ = app


def test_map_view_focus_group_media_keeps_pending_until_shown() -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from traveljournal.services.workspace import Workspace
    from traveljournal.views.map_view import MapView

    app = QApplication.instance() or QApplication([])
    view = MapView(Workspace())
    view.focus_group_media("section:7", 9)
    assert view._requested_focus == "section:7"
    assert view._pending_detail_key == "section:7"
    assert view._pending_detail_media == 9
    _ = app


def test_cascade_inspector_offsets_second_window(tmp_path: Path) -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from jpeg_fixtures import write_plain_jpeg
    from PySide6.QtWidgets import QApplication, QWidget

    from travelcore.media.gallery import GalleryItem
    from traveljournal.widgets.media_inspector import MediaInspectorWindow, cascade_inspector

    app = QApplication.instance() or QApplication([])
    host = QWidget()
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
        thumbnail_path=tmp_path,
        sort_status=None,
    )
    first = MediaInspectorWindow(item, parent=host)
    first.move(40, 60)
    second = MediaInspectorWindow(item, parent=host)
    cascade_inspector(second, host)
    assert second.pos().x() == first.x() + 28
    assert second.pos().y() == first.y() + 28
    _ = app


def test_focus_group_media_last_press_wins_strip() -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from travelcore.maps.groups import MapTimelineCard
    from travelcore.timeline.sections import KIND_STAY
    from traveljournal.services.workspace import Workspace
    from traveljournal.views.map_view import MapView

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
            ),
            MapTimelineCard(
                group_key="section:7",
                title="Sieben",
                time_label="am 02.05.2025",
                latitude=47.0,
                longitude=12.0,
                card_kind=KIND_STAY,
            ),
        )
    )
    view.resize(800, 500)
    view.show()
    app.processEvents()
    view.focus_group_media("section:1", 3)
    first_gen = view._media_focus_gen
    view.focus_group_media("section:7", 9)
    app.processEvents()
    assert view._media_focus_gen > first_gen
    assert view._timeline.focused_key() == "section:7"
    assert view._requested_focus == "section:7"
    view._focus_detail_media(3, first_gen)
    scripts: list[str] = []
    view._run_js = scripts.append  # type: ignore[method-assign]
    view._focus_detail_media(3, first_gen)
    assert scripts == []
    view._focus_detail_media(9, view._media_focus_gen)
    assert any("traveljournalFocusMedia(9)" in script for script in scripts)
    _ = app


def test_focus_group_media_centers_image_section_and_keeps_detail() -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from travelcore.maps.groups import MapTimelineCard
    from travelcore.timeline.sections import KIND_STAY
    from traveljournal.services.workspace import Workspace
    from traveljournal.views.map_view import MapView

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
            ),
            MapTimelineCard(
                group_key="section:7",
                title="Sieben",
                time_label="am 02.05.2025",
                latitude=47.0,
                longitude=12.0,
                card_kind=KIND_STAY,
            ),
        )
    )
    view.resize(800, 500)
    view.show()
    app.processEvents()
    view.focus_group_media("section:7", 9)
    app.processEvents()
    assert view._timeline.focused_key() == "section:7"
    view._map_focus_armed = True
    view._last_expand_key = "section:7"
    view._detail_group_key = "section:7"
    view._wanted_detail_key = "section:7"
    view._wanted_detail_media = 9
    view._media_focus_lock = False
    scripts: list[str] = []
    view._run_js = scripts.append  # type: ignore[method-assign]
    view._on_timeline_focus("section:7")
    assert view._last_expand_key == "section:7"
    assert view._detail_group_key == "section:7"
    assert not any("traveljournalZoomToCover" in script for script in scripts)
    view._media_focus_lock = True
    view._on_timeline_focus("section:1")
    assert view._last_expand_key == "section:7"
    assert view._detail_group_key == "section:7"
    assert not any("traveljournalZoomToCover" in script for script in scripts)
    _ = app


def test_focus_group_media_opens_section_detail_and_photo() -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from travelcore.maps.groups import MapTimelineCard
    from travelcore.timeline.sections import KIND_STAY
    from traveljournal.services.workspace import Workspace
    from traveljournal.views.map_view import MapView

    app = QApplication.instance() or QApplication([])
    view = MapView(Workspace())
    view._stack.setCurrentWidget(view._web_host)
    view._timeline.set_cards(
        (
            MapTimelineCard(
                group_key="section:7",
                title="Sieben",
                time_label="am 02.05.2025",
                latitude=47.0,
                longitude=12.0,
                card_kind=KIND_STAY,
            ),
        )
    )
    view.resize(800, 500)
    view.show()
    app.processEvents()
    view.focus_group_media("section:7", 9)
    scripts: list[str] = []
    view.workspace.map_group_detail = lambda key: {  # type: ignore[method-assign]
        "group_key": key,
        "markers": [],
        "polylines": [],
    }
    view._page_ready = lambda: True  # type: ignore[method-assign]
    view._run_js = lambda script: scripts.append(script) or True  # type: ignore[method-assign]
    view._web = object()  # type: ignore[assignment]
    view._finish_requested_focus()
    assert view._wanted_detail_key == "section:7"
    assert view._wanted_detail_media == 9
    assert any("traveljournalShowDetail" in script for script in scripts)
    assert any("focus_source_id" in script for script in scripts)
    view._media_focus_lock = False
    view._map_focus_armed = True
    later: list[str] = []
    view._run_js = later.append  # type: ignore[method-assign]
    view._on_timeline_focus("section:7")
    assert view._last_expand_key == "section:7"
    assert not any("traveljournalZoomToCover" in script for script in later)
    _ = app


def test_refresh_reuses_live_map_without_rebuild() -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from pathlib import Path

    from PySide6.QtWidgets import QApplication

    from travelcore.maps.cache import MapRenderResult
    from travelcore.maps.groups import MapTimelineCard
    from travelcore.timeline.sections import KIND_STAY
    from traveljournal.services.workspace import Workspace
    from traveljournal.views.map_view import MapView

    app = QApplication.instance() or QApplication([])
    view = MapView(Workspace())
    view._stack.setCurrentWidget(view._web_host)
    view._timeline.set_cards(
        (
            MapTimelineCard(
                group_key="section:7",
                title="Sieben",
                time_label="am 02.05.2025",
                latitude=47.0,
                longitude=12.0,
                card_kind=KIND_STAY,
            ),
        )
    )
    view.resize(800, 500)
    view.show()
    app.processEvents()
    view._loaded_seq = 4
    view._desired_seq = 4
    view._page_ready = lambda: True  # type: ignore[method-assign]
    view.workspace.load_cached_map = lambda: MapRenderResult(  # type: ignore[method-assign]
        html_path=Path("cache/map.html"),
        empty=False,
        from_cache=True,
        render_seq=4,
    )
    rebuilt: list[object] = []
    view._apply_result = rebuilt.append  # type: ignore[method-assign]
    prepared: list[object] = []
    view._show_cached_or_prepare = lambda **kwargs: prepared.append(kwargs)  # type: ignore[method-assign]
    view.focus_group_media("section:7", 9)
    view.refresh()
    assert rebuilt == []
    assert prepared == []
    _ = app


def test_section_detail_payload_is_cached() -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from traveljournal.services.workspace import Workspace
    from traveljournal.views.map_view import MapView

    app = QApplication.instance() or QApplication([])
    view = MapView(Workspace())
    calls: list[str] = []

    def detail(key: str) -> dict[str, object]:
        calls.append(key)
        return {"group_key": key, "markers": []}

    view.workspace.map_group_detail = detail  # type: ignore[method-assign]
    first = view._section_detail_payload("section:7", 9)
    second = view._section_detail_payload("section:7", 9)
    assert calls == ["section:7"]
    assert first["focus_source_id"] == 9
    assert second["focus_source_id"] == 9
    _ = app


def test_strip_set_cards_can_keep_requested_section() -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from travelcore.maps.groups import MapTimelineCard
    from travelcore.timeline.sections import KIND_STAY
    from traveljournal.widgets.map_timeline import MapTimelineStrip

    app = QApplication.instance() or QApplication([])
    strip = MapTimelineStrip()
    strip.resize(640, 180)
    strip.show()
    seen: list[str] = []
    strip.focus_changed.connect(seen.append)
    cards = (
        MapTimelineCard(
            group_key="section:1",
            title="Eins",
            time_label="am 01.05.2025",
            latitude=46.0,
            longitude=11.0,
            card_kind=KIND_STAY,
        ),
        MapTimelineCard(
            group_key="section:7",
            title="Sieben",
            time_label="am 02.05.2025",
            latitude=47.0,
            longitude=12.0,
            card_kind=KIND_STAY,
        ),
    )
    strip.set_cards(cards, focus_key="section:7")
    app.processEvents()
    assert strip.focused_key() == "section:7"
    seen.clear()
    strip.center_on("section:7", emit=False)
    app.processEvents()
    strip._emit_center()
    assert seen == []
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


def test_strip_click_closes_detail_and_zooms_cover() -> None:
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
            ),
            MapTimelineCard(
                group_key="section:7",
                title="Sieben",
                time_label="am 02.05.2025",
                latitude=47.0,
                longitude=12.0,
                card_kind=KIND_STAY,
            ),
        )
    )
    view._map_focus_armed = True
    view._last_expand_key = "section:1"
    view._detail_group_key = "section:1"
    scripts: list[str] = []
    view._run_js = scripts.append  # type: ignore[method-assign]
    view._on_timeline_focus("section:7")
    assert view._last_expand_key == ""
    assert view._detail_group_key == ""
    assert view._timeline.focused_key() == "section:7"
    assert any("traveljournalZoomToCover" in script for script in scripts)
    view._last_expand_key = "section:7"
    view._detail_group_key = "section:7"
    scripts.clear()
    view._on_timeline_focus("section:7")
    assert view._last_expand_key == "section:7"
    assert view._detail_group_key == "section:7"
    assert not any("traveljournalZoomToCover" in script for script in scripts)
    _ = app


def test_strip_click_zooms_to_section_cover() -> None:
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
                group_key="section:7",
                title="Sieben",
                time_label="am 02.05.2025",
                latitude=47.0,
                longitude=12.0,
                card_kind=KIND_STAY,
            ),
        )
    )
    view._map_focus_armed = True
    scripts: list[str] = []
    view._run_js = scripts.append  # type: ignore[method-assign]
    view._on_timeline_focus("section:7")
    assert view._timeline.focused_key() == "section:7"
    assert any("traveljournalZoomToCover" in script for script in scripts)
    assert not any("traveljournalFocusCover" in script for script in scripts)
    _ = app


def test_map_pipeline_view_skips_overview_fit() -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from traveljournal.services.workspace import Workspace
    from traveljournal.views.map_view import MapView

    app = QApplication.instance() or QApplication([])
    view = MapView(Workspace())
    scripts: list[str] = []
    view._run_js = scripts.append  # type: ignore[method-assign]
    view._store_pipeline_view([46.5, 11.3, 14])
    view._fit_map_overview()
    assert scripts == []
    view._restore_pipeline_view()
    assert any("traveljournalRestoreView(46.5000000000, 11.3000000000, 14.000000)" in script for script in scripts)
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


def test_matches_rating_hides_rejected_from_all() -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from datetime import UTC, datetime

    from travelcore.media.gallery import SORT_FAVORITE, SORT_REJECTED, SORT_RESERVE, GalleryItem
    from traveljournal.widgets.media_tabs import matches_rating

    stamp = datetime(2025, 5, 15, 8, 0, tzinfo=UTC)

    def item(*, sort_status: str | None, favorite: bool = False) -> GalleryItem:
        return GalleryItem(
            source_file_id=1,
            path="a.jpg",
            filename="a.jpg",
            extension=".jpg",
            captured_at=stamp,
            timezone_unknown=False,
            gps_latitude=None,
            gps_longitude=None,
            camera=None,
            is_favorite=favorite,
            used_in_journal=False,
            thumbnail_path=Path("."),
            sort_status=sort_status,
        )

    rejected = item(sort_status=SORT_REJECTED)
    assert matches_rating(item(sort_status=None), None)
    assert matches_rating(item(sort_status=SORT_FAVORITE, favorite=True), None)
    assert matches_rating(item(sort_status=SORT_RESERVE), None)
    assert not matches_rating(rejected, None)
    assert not matches_rating(rejected, SORT_FAVORITE)
    assert not matches_rating(rejected, SORT_RESERVE)
    assert matches_rating(rejected, SORT_REJECTED)
    assert matches_rating(rejected, None, include_rejected=True)


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
    rejected = TimelinePhoto(
        source_file_id=3,
        filename="weg.jpg",
        path="weg.jpg",
        thumbnail_path=Path("."),
        captured_at=stamp,
        used_in_journal=False,
        is_cover=False,
        is_favorite=False,
        gps_latitude=None,
        gps_longitude=None,
        file_kind="photo",
        sort_status="rejected",
    )
    day = TimelineDay(
        id=1,
        day_index=0,
        date=stamp.date(),
        title=None,
        notes=None,
        origin="auto",
        photos=(normal, favorite, rejected),
    )
    widget = EntryWidget(TimelineEntry(started_at=stamp, leftover_day=day))
    assert widget._media_tabs.count() == 4
    assert widget._media_tabs.tabText(3) == "Aussortiert"
    assert [item.filename for item in widget.gallery.items()] == ["normal.jpg", "fav.jpg"]
    widget.set_media_tab(media_tab_index("favorite"))
    assert [item.filename for item in widget.gallery.items()] == ["fav.jpg"]
    assert [item.filename for item in widget.inspectable_media()] == ["normal.jpg", "fav.jpg", "weg.jpg"]
    widget.set_media_tab(media_tab_index("reserve"))
    assert [item.filename for item in widget.gallery.items()] == []
    widget.set_media_tab(media_tab_index("rejected"))
    assert [item.filename for item in widget.gallery.items()] == ["weg.jpg"]
    _ = app


def test_entry_widget_track_tab_filters_and_reactivates() -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from dataclasses import replace
    from datetime import UTC, datetime

    from PySide6.QtWidgets import QApplication

    from travelcore.media.gallery import SORT_REJECTED
    from travelcore.timeline.types import TimelineDay, TimelineEntry, TimelinePhoto
    from traveljournal.views.timeline_view import EntryWidget, media_tab_index

    app = QApplication.instance() or QApplication([])
    stamp = datetime(2025, 5, 15, 9, 0, tzinfo=UTC)

    def track(
        file_id: int,
        name: str,
        *,
        sort_status: str | None = None,
        favorite: bool = False,
    ) -> TimelinePhoto:
        return TimelinePhoto(
            source_file_id=file_id,
            filename=name,
            path=name,
            thumbnail_path=Path("."),
            captured_at=stamp,
            used_in_journal=False,
            is_cover=False,
            is_favorite=favorite,
            gps_latitude=None,
            gps_longitude=None,
            file_kind="gps",
            sort_status=sort_status,
        )

    day = TimelineDay(
        id=1,
        day_index=0,
        date=stamp.date(),
        title=None,
        notes=None,
        origin="auto",
        photos=(
            track(1, "normal.gpx"),
            track(2, "fav.gpx", sort_status="favorite", favorite=True),
            track(3, "weg.gpx", sort_status=SORT_REJECTED),
        ),
    )
    widget = EntryWidget(TimelineEntry(started_at=stamp, leftover_day=day))
    assert widget._media_tabs.isHidden()
    assert widget._track_tabs.count() == 4
    assert widget._track_tabs.tabText(3) == "Aussortiert"
    assert [item.filename for item in widget.track_gallery.items()] == ["normal.gpx", "fav.gpx"]
    widget.set_media_tab(media_tab_index("favorite"))
    assert widget._track_tabs.currentIndex() == media_tab_index("favorite")
    assert [item.filename for item in widget.track_gallery.items()] == ["fav.gpx"]
    widget.set_media_tab(media_tab_index("rejected"))
    shown = widget.track_gallery.items()
    assert [item.filename for item in shown] == ["weg.gpx"]
    widget.sync_rating(replace(shown[0], sort_status=None, is_favorite=False))
    assert [item.filename for item in widget.track_gallery.items()] == []
    widget.set_media_tab(media_tab_index("all"))
    assert [item.filename for item in widget.track_gallery.items()] == ["normal.gpx", "fav.gpx", "weg.gpx"]
    _ = app


def test_timeline_pool_pane_lists_parked_media(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from datetime import UTC, datetime
    from types import SimpleNamespace

    from PySide6.QtWidgets import QApplication

    from travelcore.media.gallery import GalleryItem
    from travelcore.timeline.types import TimelineDay, TimelineEntry, TimelinePhoto, TimelineSnapshot
    from traveljournal.services import workspace as workspace_mod
    from traveljournal.services.workspace import Workspace
    from traveljournal.views.timeline_view import TimelineView
    from traveljournal.widgets.media_tabs import media_tab_index

    monkeypatch.setattr(workspace_mod, "_UI_CONFIG_PATH", tmp_path / "config.json")
    app = QApplication.instance() or QApplication([])
    stamp = datetime(2025, 5, 15, 8, 0, tzinfo=UTC)
    parked = GalleryItem(
        source_file_id=9,
        path="pool.jpg",
        filename="pool.jpg",
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
        parked=True,
    )
    photo = TimelinePhoto(
        source_file_id=1,
        filename="tag.jpg",
        path="tag.jpg",
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
    monkeypatch.setattr(workspace, "current", SimpleNamespace(directory=tmp_path))
    view = TimelineView(workspace)
    monkeypatch.setattr(view, "_parked_items", lambda: [parked])
    view._snapshot = TimelineSnapshot(
        trip_id=1,
        title="Reise",
        origin="auto",
        days=(day,),
        entries=(TimelineEntry(started_at=stamp, leftover_day=day),),
    )
    view._fill_entries()
    assert view._pool_pane._tabs.count() == 4
    assert view._pool_pane._tabs.tabText(1) == "Favoriten"
    assert [item.filename for item in view._pool_pane.gallery.items()] == ["pool.jpg"]
    view._pool_pane._tabs.setCurrentIndex(media_tab_index("favorite"))
    assert [item.filename for item in view._pool_pane.gallery.items()] == ["pool.jpg"]
    view._pool_pane._tabs.setCurrentIndex(media_tab_index("rejected"))
    assert [item.filename for item in view._pool_pane.gallery.items()] == []
    assert view._pool_pane.parent() is view._split
    assert view._host_layout.indexOf(view._pool_pane) == -1
    assert view._pool_pane.isHidden()
    view._pool_toggle.setChecked(True)
    assert not view._pool_pane.isHidden()
    assert workspace.timeline_pool_visible() is True
    assert view._pool_toggle.toolTip() == "Medienpool einklappen"
    assert view._blocks[0]._media_tabs.count() == 4
    assert view._blocks[0]._media_tabs.tabText(3) == "Aussortiert"
    assert view._media_tabs.count() == 4
    assert view._pool_pane.maximumWidth() > 800
    _ = app


def test_pool_scroll_date_follows_handle() -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from datetime import UTC, datetime

    from PySide6.QtWidgets import QApplication

    from travelcore.media.gallery import GalleryItem
    from traveljournal.widgets.pool_pane import PoolPane
    from traveljournal.widgets.scroll_date import scrollbar_slider_rect

    app = QApplication.instance() or QApplication([])
    items = [
        GalleryItem(
            source_file_id=index,
            path=f"{index}.jpg",
            filename=f"{index:02d}.jpg",
            extension=".jpg",
            captured_at=datetime(2025, 5 if index < 8 else 8, min(index, 28), 8, 0, tzinfo=UTC),
            timezone_unknown=False,
            gps_latitude=None,
            gps_longitude=None,
            camera=None,
            is_favorite=False,
            used_in_journal=False,
            thumbnail_path=Path("."),
            parked=True,
        )
        for index in range(1, 16)
    ]
    pane = PoolPane()
    pane.set_items(items)
    pane.resize(260, 360)
    pane.show()
    app.processEvents()
    gallery = pane.gallery
    chip = gallery._scroll_date
    assert chip is not None
    bar = gallery.verticalScrollBar()
    assert bar.maximum() > 0
    bar.setValue(0)
    app.processEvents()
    chip.sync(show=True)
    assert not chip.label.isHidden()
    assert chip.label.text().endswith("05.2025")
    bar.setValue(bar.maximum())
    app.processEvents()
    chip.sync(show=True)
    assert "08.2025" in chip.label.text()
    handle = scrollbar_slider_rect(bar)
    center = bar.mapTo(gallery, handle.center())
    assert chip.label.x() >= 0
    assert chip.label.geometry().right() <= gallery.width()
    assert abs(chip.label.geometry().center().y() - center.y()) < 24
    _ = app


def test_timeline_pool_restores_width_after_collapse(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from traveljournal.services import workspace as workspace_mod
    from traveljournal.services.workspace import Workspace
    from traveljournal.views.timeline_view import TimelineView

    monkeypatch.setattr(workspace_mod, "_UI_CONFIG_PATH", tmp_path / "config.json")
    app = QApplication.instance() or QApplication([])
    workspace = Workspace()
    view = TimelineView(workspace)
    view.resize(1100, 700)
    view.show()
    app.processEvents()
    view._pool_toggle.setChecked(True)
    app.processEvents()
    view._split.setSizes([700, 380])
    app.processEvents()
    view._pool_toggle.setChecked(False)
    app.processEvents()
    saved = workspace.pool_width()
    assert saved >= 360
    view._pool_toggle.setChecked(True)
    app.processEvents()
    assert abs(view._split.sizes()[1] - saved) <= 8
    _ = app


def test_photos_view_pool_collapse_matches_timeline(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from traveljournal.services import workspace as workspace_mod
    from traveljournal.services.workspace import Workspace
    from traveljournal.views.photos_view import PhotosView

    monkeypatch.setattr(workspace_mod, "_UI_CONFIG_PATH", tmp_path / "config.json")
    app = QApplication.instance() or QApplication([])
    workspace = Workspace()
    view = PhotosView(workspace)
    assert view._pool_toggle.objectName() == "poolCollapse"
    assert view._pool_pane.isHidden()
    view.resize(1100, 700)
    view.show()
    app.processEvents()
    view._pool_toggle.setChecked(True)
    app.processEvents()
    assert not view._pool_pane.isHidden()
    assert workspace.timeline_pool_visible() is True
    view._split.setSizes([700, 340])
    app.processEvents()
    view._pool_toggle.setChecked(False)
    app.processEvents()
    assert view._pool_pane.isHidden()
    saved = workspace.pool_width()
    assert saved >= 320
    view._pool_toggle.setChecked(True)
    app.processEvents()
    assert abs(view._split.sizes()[1] - saved) <= 8
    _ = app


def test_timeline_drop_pool_on_section_moves_members(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from datetime import UTC, datetime

    from PySide6.QtWidgets import QApplication

    from travelcore.timeline.types import TimelineEntry, TimelineSection
    from traveljournal.services import workspace as workspace_mod
    from traveljournal.services.workspace import Workspace
    from traveljournal.views.timeline_view import EntryWidget, TimelineView

    monkeypatch.setattr(workspace_mod, "_UI_CONFIG_PATH", tmp_path / "config.json")
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
    workspace = Workspace()
    moved: list[tuple[int, list[int]]] = []

    def fake_move(section_id: int, ids: list[int], **_kwargs: object) -> None:
        moved.append((section_id, list(ids)))

    monkeypatch.setattr(workspace, "move_members", fake_move)
    view = TimelineView(workspace)
    block = EntryWidget(TimelineEntry(started_at=stamp, section=section), parent=view)
    assert block.accepts_pool_drop()
    assert block.gallery.dragEnabled()
    assert block.track_gallery.dragEnabled()
    assert view._pool_pane.acceptDrops()
    view._drop_pool_on_entry(block, [9, 9, 7])
    assert moved == [(7, [9, 7])]
    _ = app


def test_timeline_drop_on_same_section_is_noop(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from datetime import UTC, datetime
    from pathlib import Path

    from PySide6.QtWidgets import QApplication

    from travelcore.timeline.types import TimelineEntry, TimelinePhoto, TimelineSection
    from traveljournal.services import workspace as workspace_mod
    from traveljournal.services.workspace import Workspace
    from traveljournal.views.timeline_view import EntryWidget, TimelineView

    monkeypatch.setattr(workspace_mod, "_UI_CONFIG_PATH", tmp_path / "config.json")
    app = QApplication.instance() or QApplication([])
    stamp = datetime(2025, 5, 15, 8, 0, tzinfo=UTC)
    photo = TimelinePhoto(
        source_file_id=9,
        filename="ort.jpg",
        path="ort.jpg",
        thumbnail_path=Path("."),
        captured_at=stamp,
        used_in_journal=False,
        is_cover=False,
        is_favorite=False,
        gps_latitude=None,
        gps_longitude=None,
        file_kind="photo",
    )
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
        items=(photo,),
    )
    workspace = Workspace()
    moved: list[tuple[int, list[int]]] = []

    def fake_move(section_id: int, ids: list[int], **_kwargs: object) -> None:
        moved.append((section_id, list(ids)))

    monkeypatch.setattr(workspace, "move_members", fake_move)
    view = TimelineView(workspace)
    block = EntryWidget(TimelineEntry(started_at=stamp, section=section), parent=view)
    view._drop_pool_on_entry(block, [9, 9])
    assert moved == []
    _ = app


def test_timeline_drop_section_on_pool_parks_media(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from traveljournal.services import workspace as workspace_mod
    from traveljournal.services.workspace import Workspace
    from traveljournal.views.timeline_view import TimelineView

    monkeypatch.setattr(workspace_mod, "_UI_CONFIG_PATH", tmp_path / "config.json")
    app = QApplication.instance() or QApplication([])
    workspace = Workspace()
    parked: list[list[int]] = []

    def fake_park(ids: list[int]) -> None:
        parked.append(list(ids))

    monkeypatch.setattr(workspace, "park_media", fake_park)
    view = TimelineView(workspace)
    monkeypatch.setattr(view, "refresh", lambda: None)
    monkeypatch.setattr(view, "_set_pool_visible", lambda _visible: None)
    view._drop_on_timeline_pool([3, 3, 1])
    assert parked == [[3, 1]]
    monkeypatch.setattr(view._pool_pane, "contains", lambda source_id: source_id == 3)
    view._drop_on_timeline_pool([3])
    assert parked == [[3, 1]]
    _ = app


def test_timeline_autoscroll_step_near_edges() -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from traveljournal.views.timeline_view import autoscroll_step

    assert autoscroll_step(200, 400) == 0
    assert autoscroll_step(0, 400) < 0
    assert autoscroll_step(400, 400) > 0
    assert autoscroll_step(-10, 400) < 0
    assert autoscroll_step(500, 400) > 0
    assert abs(autoscroll_step(0, 400)) >= abs(autoscroll_step(40, 400))
    assert abs(autoscroll_step(400, 400)) >= abs(autoscroll_step(360, 400))
    assert autoscroll_step(0, 0) == 0


def test_timeline_drag_autoscroll_timer(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from traveljournal.services import workspace as workspace_mod
    from traveljournal.services.workspace import Workspace
    from traveljournal.views.timeline_view import TimelineView

    monkeypatch.setattr(workspace_mod, "_UI_CONFIG_PATH", tmp_path / "config.json")
    app = QApplication.instance() or QApplication([])
    view = TimelineView(Workspace())
    view.resize(800, 600)
    view.show()
    app.processEvents()
    assert not view._drag_scroll.isActive()
    view._pool_pane.gallery.drag_started.emit()
    assert view._drag_scroll.isActive()
    view._pool_pane.gallery.drag_finished.emit()
    assert not view._drag_scroll.isActive()
    height = view._scroll.viewport().height()
    assert height > 0
    assert view._drag_scroll_delta(y=0) < 0
    assert view._drag_scroll_delta(y=height) > 0
    assert view._drag_scroll_delta(y=height // 2) == 0
    bar = view._scroll.verticalScrollBar()
    bar.setRange(0, 1000)
    bar.setValue(100)
    monkeypatch.setattr(view, "_drag_scroll_delta", lambda: 20)
    view._on_drag_scroll_tick()
    assert bar.value() == 120
    _ = app


def test_timeline_map_anchor_uses_ordered_items_not_entry_attr(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from datetime import UTC, datetime
    from pathlib import Path

    from PySide6.QtWidgets import QApplication

    from travelcore.timeline.types import TimelineEntry, TimelinePhoto, TimelineSection
    from traveljournal.services import workspace as workspace_mod
    from traveljournal.services.workspace import Workspace
    from traveljournal.views.timeline_view import EntryWidget, TimelineView

    monkeypatch.setattr(workspace_mod, "_UI_CONFIG_PATH", tmp_path / "config.json")
    app = QApplication.instance() or QApplication([])
    stamp = datetime(2025, 5, 15, 8, 0, tzinfo=UTC)
    stay_photo = TimelinePhoto(
        source_file_id=1,
        filename="ort.jpg",
        path="ort.jpg",
        thumbnail_path=Path("."),
        captured_at=stamp,
        used_in_journal=False,
        is_cover=False,
        is_favorite=False,
        gps_latitude=None,
        gps_longitude=None,
        display_latitude=46.0,
        display_longitude=11.0,
        file_kind="photo",
    )
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
        items=(stay_photo,),
    )
    view = TimelineView(Workspace())
    block = EntryWidget(TimelineEntry(started_at=stamp, section=section), parent=view)
    assert not hasattr(block, "entry")
    assert view._section_has_map_anchor(block, set()) is True
    assert view._section_has_map_anchor(block, {1}) is False
    _ = app


def test_photos_view_multi_select_and_pool_drag(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from datetime import UTC, datetime

    from PySide6.QtWidgets import QAbstractItemView, QApplication

    from travelcore.media.gallery import GalleryItem
    from traveljournal.services import workspace as workspace_mod
    from traveljournal.services.workspace import Workspace
    from traveljournal.views.photos_view import PhotosView

    monkeypatch.setattr(workspace_mod, "_UI_CONFIG_PATH", tmp_path / "config.json")
    app = QApplication.instance() or QApplication([])
    view = PhotosView(Workspace())
    stamp = datetime(2025, 5, 15, 8, 0, tzinfo=UTC)

    def item(name: str, source_file_id: int, *, parked: bool = False) -> GalleryItem:
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
            is_favorite=False,
            used_in_journal=False,
            thumbnail_path=Path("."),
            parked=parked,
        )

    view._items = [
        item("a.jpg", 1),
        item("b.jpg", 2),
        item("c.jpg", 3),
        item("d.jpg", 4),
        item("pool.jpg", 5, parked=True),
    ]
    view._apply_filters()
    assert view.stats.objectName() == "pageSubtitle"
    assert view.stats.text() == "Kein Projekt geöffnet"
    assert view.gallery.selectionMode() == QAbstractItemView.SelectionMode.MultiSelection
    assert view.gallery.dragEnabled()
    assert view.gallery.acceptDrops()
    assert view._pool_pane.acceptDrops()
    assert not view._group_selected_btn.isEnabled()
    view.gallery.select_by_source_ids({1, 3})
    assert {row.source_file_id for row in view.gallery.selected_items()} == {1, 2, 3}
    assert view._group_selected_btn.isEnabled()
    default = view.gallery.gridSize()
    view._on_thumb_zoom(50)
    assert view.gallery.gridSize().width() < default.width()
    assert view._pool_pane.gallery.gridSize().width() == view.gallery.gridSize().width()

    parked: list[list[int]] = []
    unparked: list[list[int]] = []
    monkeypatch.setattr(view.workspace, "park_media", lambda ids: parked.append(list(ids)))
    monkeypatch.setattr(view.workspace, "unpark_media", lambda ids: unparked.append(list(ids)))
    monkeypatch.setattr(view, "refresh", lambda: None)
    view._drop_on_pool([1, 5])
    assert parked == [[1]]
    view._drop_on_gallery([1, 5])
    assert unparked == [[5]]
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

    def item(
        name: str,
        source_file_id: int,
        *,
        favorite: bool = False,
        parked: bool = False,
        sort_status: str | None = None,
    ) -> GalleryItem:
        status = sort_status if sort_status is not None else ("favorite" if favorite else None)
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
            is_favorite=favorite or status == "favorite",
            used_in_journal=False,
            thumbnail_path=Path("."),
            sort_status=status,
            parked=parked,
        )

    view._items = [
        item("normal.jpg", 1),
        item("fav.jpg", 2, favorite=True),
        item("weg.jpg", 3, sort_status="rejected"),
        item("pool-fav.jpg", 4, favorite=True, parked=True),
        item("pool.jpg", 5, parked=True),
        item("pool-weg.jpg", 6, parked=True, sort_status="rejected"),
    ]
    view._apply_filters()
    assert [row.filename for row in view.gallery.items()] == ["normal.jpg", "fav.jpg"]
    assert [row.filename for row in view._pool_pane.gallery.items()] == ["pool-fav.jpg", "pool.jpg"]
    assert not view._show_rejected.isHidden()
    assert not view._show_rejected.isChecked()
    view._show_rejected.setChecked(True)
    assert [row.filename for row in view.gallery.items()] == ["normal.jpg", "fav.jpg", "weg.jpg"]
    assert [row.filename for row in view._pool_pane.gallery.items()] == [
        "pool-fav.jpg",
        "pool.jpg",
        "pool-weg.jpg",
    ]
    view._show_rejected.setChecked(False)
    assert [row.filename for row in view.gallery.items()] == ["normal.jpg", "fav.jpg"]
    view._media_tabs.setCurrentIndex(media_tab_index("favorite"))
    assert view._show_rejected.isHidden()
    assert [row.filename for row in view.gallery.items()] == ["fav.jpg"]
    view._media_tabs.setCurrentIndex(media_tab_index("reserve"))
    assert [row.filename for row in view.gallery.items()] == []
    view._media_tabs.setCurrentIndex(media_tab_index("rejected"))
    assert [row.filename for row in view.gallery.items()] == ["weg.jpg"]
    view._pool_pane._tabs.setCurrentIndex(media_tab_index("favorite"))
    assert [row.filename for row in view._pool_pane.gallery.items()] == ["pool-fav.jpg"]
    view._pool_pane._tabs.setCurrentIndex(media_tab_index("rejected"))
    assert [row.filename for row in view._pool_pane.gallery.items()] == ["pool-weg.jpg"]
    _ = app


def test_photos_view_filter_panel_quality_and_rating(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from datetime import UTC, date, datetime

    from PySide6.QtWidgets import QApplication

    from travelcore.media.gallery import GalleryItem
    from traveljournal.services import workspace as workspace_mod
    from traveljournal.services.workspace import Workspace
    from traveljournal.views.photos_view import PhotosView

    monkeypatch.setattr(workspace_mod, "_UI_CONFIG_PATH", tmp_path / "config.json")
    app = QApplication.instance() or QApplication([])
    view = PhotosView(Workspace())
    stamp = datetime(2025, 6, 15, 8, 0, tzinfo=UTC)

    def item(
        name: str,
        source_file_id: int,
        *,
        quality: str | None = None,
        sort_status: str | None = None,
        parked: bool = False,
    ) -> GalleryItem:
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
            is_favorite=sort_status == "favorite",
            used_in_journal=False,
            thumbnail_path=Path("."),
            sort_status=sort_status,
            parked=parked,
            quality_light=quality,
        )

    view._items = [
        item("green.jpg", 1, quality="green", sort_status="favorite"),
        item("red.jpg", 2, quality="red", sort_status="rejected"),
        item("plain.jpg", 3),
        item("pool-green.jpg", 4, quality="green", parked=True),
    ]
    view._filter_btn.setChecked(True)
    assert not view._filter_panel.isHidden()
    view._filter_panel._quality["green"].setChecked(True)
    view._filter_panel._quality["yellow"].setChecked(True)
    assert [row.filename for row in view.gallery.items()] == ["green.jpg"]
    assert [row.filename for row in view._pool_pane.gallery.items()] == ["pool-green.jpg"]
    view._filter_panel.reset()
    view._filter_panel._ratings["favorite"].setChecked(True)
    view._filter_panel._ratings["none"].setChecked(True)
    assert [row.filename for row in view.gallery.items()] == ["green.jpg", "plain.jpg"]
    assert [row.filename for row in view._pool_pane.gallery.items()] == ["pool-green.jpg"]
    assert view._filter_btn.text() == "Filtern · Bewertung"
    view._filter_panel.reset()
    view._filter_panel._range.setChecked(True)
    view._filter_panel.set_span(date(2025, 7, 1), date(2025, 7, 31))
    view._filter_panel.changed.emit()
    assert [row.filename for row in view.gallery.items()] == []
    assert view._filter_btn.text() == "Filtern · Datum"
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


def test_timeline_card_combos_ignore_hover_wheel() -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtGui import QWheelEvent
    from PySide6.QtWidgets import QApplication

    from travelcore.timeline.transfer_links import LINK_DASH_SOLID, LINK_GEOMETRY_LINE
    from travelcore.timeline.types import TimelineLink
    from traveljournal.views.timeline_view import SectionKindCombo
    from traveljournal.widgets.transfer_links import TransferLinkRow

    app = QApplication.instance() or QApplication([])
    wheel = QWheelEvent(
        QPointF(20, 10),
        QPointF(20, 10),
        QPoint(0, 0),
        QPoint(0, 120),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase,
        False,
    )
    kind = SectionKindCombo()
    kind.addItem("Tag", "day")
    kind.addItem("Aufenthalt", "stay")
    kind.addItem("Transfer", "movement")
    kind.setCurrentIndex(0)
    kind.wheelEvent(wheel)
    assert kind.currentIndex() == 0
    assert kind.focusPolicy() == Qt.FocusPolicy.ClickFocus
    row = TransferLinkRow(
        TimelineLink(id=0, sort_index=0, geometry=LINK_GEOMETRY_LINE, dash=LINK_DASH_SOLID),
        [],
    )
    before = row.geometry.currentIndex()
    row.geometry.wheelEvent(wheel)
    assert row.geometry.currentIndex() == before
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
    assert view._save_button.toolTip() == "Nichts zu speichern"
    _ = app


def test_timeline_undo_pending_toggles_save_button(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from travelcore.timeline.types import PendingSectionSpec
    from traveljournal.services import workspace as workspace_mod
    from traveljournal.services.workspace import Workspace
    from traveljournal.views.timeline_view import TimelineView, _copy_pending_spec

    monkeypatch.setattr(workspace_mod, "_UI_CONFIG_PATH", tmp_path / "config.json")
    app = QApplication.instance() or QApplication([])
    view = TimelineView(Workspace())
    spec = PendingSectionSpec(local_id=-1, source_file_ids=(1,), kind="stay")
    view._pending.append(_copy_pending_spec(spec))
    view._record_pending_insert(_copy_pending_spec(spec), 0)
    view._update_save_button()
    assert view._save_button.isEnabled()
    assert view.workspace.history.undo()
    assert view._pending == []
    assert not view._save_button.isEnabled()
    assert view.workspace.history.redo()
    assert len(view._pending) == 1
    assert view._save_button.isEnabled()
    _ = app


def test_timeline_leave_prompts_when_text_dirty(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
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
    monkeypatch.setattr(view, "_ask_unsaved_work", lambda: "cancel")
    assert view.confirm_leave() is False
    assert block.is_dirty()
    assert view._save_button.isEnabled()
    monkeypatch.setattr(view, "_ask_unsaved_work", lambda: "discard")
    assert view.confirm_leave() is True
    assert not view._save_button.isEnabled()
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
    first_offset = scroll_offset_to_widget_top(host, first)
    second_offset = scroll_offset_to_widget_top(host, second)
    assert first_offset == 0
    assert second_offset == 400 + 16
    _ = app


def test_timeline_join_is_wide_downward_connector() -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from traveljournal.views.timeline_view import _TIMELINE_JOIN_H, TimelineJoin

    app = QApplication.instance() or QApplication([])
    join = TimelineJoin("#2eb8a0")
    assert join.objectName() == "timelineJoin"
    assert join.height() == _TIMELINE_JOIN_H
    clicked: list[bool] = []
    join.add_requested.connect(lambda: clicked.append(True))
    join.resize(240, _TIMELINE_JOIN_H)
    join.show()
    app.processEvents()
    join._plus.clicked.emit()
    assert clicked == [True]
    fallback = TimelineJoin("not-a-color")
    assert fallback._color.name().lower() == "#ffffff"
    _ = app


def test_entry_span_dates_feeds_join_insert() -> None:
    from datetime import UTC, date, datetime

    from travelcore.timeline.sections import KIND_STAY, insert_dates_between
    from travelcore.timeline.types import TimelineDay, TimelineEntry, TimelineSection
    from traveljournal.views.timeline_view import _entry_span_dates

    early = datetime(2025, 5, 14, tzinfo=UTC)
    tag = TimelineEntry(
        started_at=early,
        leftover_day=TimelineDay(
            id=1,
            day_index=0,
            date=date(2025, 5, 14),
            title=None,
            notes=None,
            origin="auto",
        ),
    )
    stay = TimelineEntry(
        started_at=datetime(2025, 5, 20, tzinfo=UTC),
        section=TimelineSection(
            id=2,
            kind=KIND_STAY,
            mode=None,
            title="A",
            notes=None,
            started_at=datetime(2025, 5, 20, tzinfo=UTC),
            ended_at=datetime(2025, 5, 25, tzinfo=UTC),
            location_name=None,
            location_from=None,
            location_to=None,
            origin="manual",
        ),
    )
    assert _entry_span_dates(tag) == (date(2025, 5, 14), date(2025, 5, 14))
    assert _entry_span_dates(stay) == (date(2025, 5, 20), date(2025, 5, 25))
    assert insert_dates_between(_entry_span_dates(tag)[1], _entry_span_dates(stay)[0]) == (
        date(2025, 5, 15),
        date(2025, 5, 19),
    )


def test_span_index_at_mid_contains_then_nearest() -> None:
    from traveljournal.views.timeline_view import span_index_at_mid

    spans = [(0, 100), (116, 300), (316, 500)]
    assert span_index_at_mid(spans, 50) == 0
    assert span_index_at_mid(spans, 200) == 1
    assert span_index_at_mid(spans, 105) == 0
    assert span_index_at_mid(spans, 310) == 2
    assert span_index_at_mid([], 0) is None


def test_timeline_scroll_date_follows_handle(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from datetime import UTC, datetime

    from PySide6.QtCore import QPoint
    from PySide6.QtWidgets import QApplication, QFrame, QWidget

    from travelcore.timeline.sections import KIND_DAY, KIND_STAY
    from travelcore.timeline.types import TimelineEntry, TimelineSection
    from traveljournal.services import workspace as workspace_mod
    from traveljournal.services.workspace import Workspace
    from traveljournal.views.timeline_view import (
        EntryWidget,
        TimelineView,
        _scrollbar_slider_rect,
        timeline_center_date,
    )

    monkeypatch.setattr(workspace_mod, "_UI_CONFIG_PATH", tmp_path / "config.json")
    app = QApplication.instance() or QApplication([])
    early = datetime(2025, 5, 14, tzinfo=UTC)
    late_start = datetime(2025, 8, 1, tzinfo=UTC)
    late_end = datetime(2025, 8, 10, tzinfo=UTC)
    tag = EntryWidget(
        TimelineEntry(
            started_at=early,
            section=TimelineSection(
                id=1,
                kind=KIND_DAY,
                mode=None,
                title="Mai",
                notes=None,
                started_at=early,
                ended_at=early,
                location_name=None,
                location_from=None,
                location_to=None,
                origin="manual",
            ),
        )
    )
    stay = EntryWidget(
        TimelineEntry(
            started_at=late_start,
            section=TimelineSection(
                id=2,
                kind=KIND_STAY,
                mode=None,
                title="August",
                notes=None,
                started_at=late_start,
                ended_at=late_end,
                location_name=None,
                location_from=None,
                location_to=None,
                origin="manual",
            ),
        )
    )
    assert tag.scroll_date() == "14.05.2025"
    assert stay.scroll_date() == "01.–10.08.2025"

    class _Dated(QFrame):
        def __init__(self, text: str, parent: QWidget) -> None:
            super().__init__(parent)
            self._text = text
            self.setFixedHeight(1400)

        def scroll_date(self) -> str:
            return self._text

    view = TimelineView(Workspace())
    view._empty.hide()
    view._subtitle.hide()
    first = _Dated("14.05.2025", view._host)
    second = _Dated("01.–10.08.2025", view._host)
    insert_at = max(view._host_layout.count() - 1, 0)
    view._host_layout.insertWidget(insert_at, first)
    view._host_layout.insertWidget(insert_at + 1, second)
    view._blocks = [first, second]  # type: ignore[list-item]
    view.resize(720, 520)
    view.show()
    app.processEvents()
    bar = view._scroll.verticalScrollBar()
    assert bar.maximum() > 0
    host = view._scroll.widget()
    viewport = view._scroll.viewport()
    assert host is not None
    assert first.height() >= 1400
    assert second.mapTo(host, QPoint(0, 0)).y() > first.height() // 2
    bar.setValue(0)
    view._sync_scroll_date(show=True)
    app.processEvents()
    mid_y = bar.value() + viewport.height() // 2
    assert timeline_center_date(view._blocks, host, mid_y) == "14.05.2025"
    assert view._scroll_date.text() == "14.05.2025"
    assert not view._scroll_date.isHidden()
    target = second.mapTo(host, QPoint(0, 0)).y() + 80 - viewport.height() // 2
    bar.setValue(max(0, min(target, bar.maximum())))
    view._sync_scroll_date(show=True)
    app.processEvents()
    mid_y = bar.value() + viewport.height() // 2
    assert timeline_center_date(view._blocks, host, mid_y) == "01.–10.08.2025"
    assert view._scroll_date.text() == "01.–10.08.2025"
    handle = _scrollbar_slider_rect(bar)
    center = bar.mapTo(view._scroll, handle.center())
    assert view._scroll_date.x() >= 0
    assert view._scroll_date.geometry().right() <= view._scroll.width()
    assert abs(view._scroll_date.geometry().center().y() - center.y()) < 24
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
        scroll_delta_to_widget_top,
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
    insert_at = view._host_layout.indexOf(view._tail)
    view._host_layout.insertWidget(insert_at, first)
    view._host_layout.insertWidget(insert_at + 1, second)
    view._blocks = [first, second]
    view.show()
    view._sync_reveal_tail()
    view._host.adjustSize()
    app.processEvents()
    assert view._block_for_group_key("day:2") is second
    viewport = view._scroll.viewport()
    view._pending_reveal = second
    view._apply_pending_reveal()
    app.processEvents()
    assert abs(scroll_delta_to_widget_top(second, viewport)) <= 1
    first_bottom = first.mapTo(viewport, first.rect().bottomLeft()).y()
    assert first_bottom <= 1
    first.setMinimumHeight(900)
    app.processEvents()
    view._pending_reveal = second
    view._apply_pending_reveal()
    app.processEvents()
    assert abs(scroll_delta_to_widget_top(second, viewport)) <= 1
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
    assert window._pool_button.isHidden()
    assert window._to_map_button.isHidden()
    pixmap = load_media_pixmap(item)
    assert not pixmap.isNull()
    assert pixmap.width() >= 40
    _ = app


def test_media_inspector_shows_ratings_for_tracks() -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from travelcore.media.gallery import GalleryItem
    from traveljournal.widgets.media_inspector import MediaInspectorWindow, _can_rate

    app = QApplication.instance() or QApplication([])
    item = GalleryItem(
        source_file_id=8,
        path="flug.igc",
        filename="flug.igc",
        extension=".igc",
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
    assert _can_rate(item)
    window = MediaInspectorWindow(item)
    assert set(window._rating_buttons) == {"favorite", "reserve", "rejected"}
    assert all(not button.isHidden() for button in window._rating_buttons.values())
    _ = app


def test_media_inspector_parks_and_unparks_from_pool_button(tmp_path: Path) -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from jpeg_fixtures import write_plain_jpeg
    from PySide6.QtWidgets import QApplication

    from travelcore.media.gallery import GalleryItem
    from traveljournal.widgets.media_inspector import MediaInspectorWindow

    class StubWorkspace:
        def __init__(self) -> None:
            self.parked_ids: list[int] = []
            self.unparked_ids: list[int] = []

        def park_media(self, source_file_ids: list[int]) -> None:
            self.parked_ids = list(source_file_ids)

        def unpark_media(self, source_file_ids: list[int]) -> None:
            self.unparked_ids = list(source_file_ids)

        def inspector_size(self) -> tuple[int, int]:
            return (720, 520)

        def inspector_maximized(self) -> bool:
            return False

    app = QApplication.instance() or QApplication([])
    jpeg = write_plain_jpeg(tmp_path / "foto.jpg", size=(40, 30))
    item = GalleryItem(
        source_file_id=7,
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
    workspace = StubWorkspace()
    seen: list[bool] = []
    window = MediaInspectorWindow(item, workspace=workspace)
    window.park_changed.connect(lambda updated: seen.append(updated.parked))
    assert not window._pool_button.isHidden()
    assert window._pool_button.text() == "In den Pool"
    window._toggle_pool()
    assert workspace.parked_ids == [7]
    assert window.item().parked is True
    assert window._pool_button.text() == "Zurückholen"
    assert seen == [True]
    window._toggle_pool()
    assert workspace.unparked_ids == [7]
    assert window.item().parked is False
    assert window._pool_button.text() == "In den Pool"
    assert seen == [True, False]
    _ = app


def test_media_inspector_opens_current_item_on_map(tmp_path: Path) -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from jpeg_fixtures import write_plain_jpeg
    from PySide6.QtWidgets import QApplication, QPushButton

    from travelcore.media.gallery import GalleryItem
    from traveljournal.widgets.media_inspector import MediaInspectorWindow

    class StubWorkspace:
        def inspector_size(self) -> tuple[int, int]:
            return (720, 520)

        def inspector_maximized(self) -> bool:
            return False

        def map_group_key_for_source(self, source_file_id: int) -> str | None:
            return "section:7" if source_file_id == 9 else None

    app = QApplication.instance() or QApplication([])
    jpeg = write_plain_jpeg(tmp_path / "foto.jpg", size=(40, 30))
    located = GalleryItem(
        source_file_id=9,
        path=str(jpeg),
        filename="foto.jpg",
        extension=".jpg",
        captured_at=None,
        timezone_unknown=False,
        gps_latitude=46.5,
        gps_longitude=11.3,
        camera=None,
        is_favorite=False,
        used_in_journal=True,
        thumbnail_path=Path("."),
        sort_status=None,
    )
    blank = GalleryItem(
        source_file_id=10,
        path=str(jpeg),
        filename="ohne.jpg",
        extension=".jpg",
        captured_at=None,
        timezone_unknown=False,
        gps_latitude=None,
        gps_longitude=None,
        camera=None,
        is_favorite=False,
        used_in_journal=True,
        thumbnail_path=Path("."),
        sort_status=None,
    )
    window = MediaInspectorWindow(located, items=[located, blank], workspace=StubWorkspace())
    button = window.findChild(QPushButton, "inspectorToMap")
    assert button is not None
    assert not button.isHidden()
    assert button.isEnabled()
    opened: list[tuple[str, int]] = []
    window.open_media_on_map.connect(lambda key, sid: opened.append((key, sid)))
    button.click()
    assert opened == [("section:7", 9)]
    window.step(1)
    assert not window._to_map_button.isEnabled()
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
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QKeyEvent
    from PySide6.QtTest import QTest
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
    assert window._image._browse is True
    window.step(1)
    assert window.item().filename == "eins.jpg"
    assert window.windowTitle() == "eins.jpg · 1 von 2"
    override = QKeyEvent(
        QEvent.Type.ShortcutOverride, Qt.Key.Key_Right, Qt.KeyboardModifier.NoModifier
    )
    QApplication.sendEvent(window, override)
    assert override.isAccepted()
    QApplication.sendEvent(
        window,
        QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Right, Qt.KeyboardModifier.NoModifier),
    )
    assert window.item().filename == "zwei.jpg"
    window._rating_buttons["favorite"].setFocus()
    QTest.keyClick(window._rating_buttons["favorite"], Qt.Key.Key_Left)
    assert window.item().filename == "eins.jpg"
    window._image.side_clicked.emit(1)
    assert window.item().filename == "zwei.jpg"
    window._image.zoom_at(2.0, QPointF(200, 150))
    assert window._image.zoom == 2.0
    window.step(1)
    assert window.item().filename == "eins.jpg"
    assert window._image.zoom == 1.0
    window._meta.setFocus()
    QTest.keyClick(window._meta, Qt.Key.Key_Right)
    assert window.item().filename == "zwei.jpg"
    _ = app
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from jpeg_fixtures import write_plain_jpeg
    from PySide6.QtWidgets import QApplication

    from travelcore.media.gallery import GalleryItem
    from traveljournal.widgets.media_inspector import MediaInspectorWindow

    class StubWorkspace:
        def __init__(self) -> None:
            self.statuses: dict[int, str | None] = {}

        def set_sort_status(self, source_file_id: int, status: str | None) -> None:
            self.statuses[source_file_id] = status

        def inspector_size(self) -> tuple[int, int]:
            return (720, 520)

        def inspector_maximized(self) -> bool:
            return False

    app = QApplication.instance() or QApplication([])
    first_path = write_plain_jpeg(tmp_path / "eins.jpg", size=(40, 30))
    second_path = write_plain_jpeg(tmp_path / "zwei.jpg", size=(40, 30))
    third_path = write_plain_jpeg(tmp_path / "drei.jpg", size=(40, 30))

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
    third = make_item(3, third_path, "drei.jpg")
    workspace = StubWorkspace()
    rated: list[str] = []
    window = MediaInspectorWindow(first, items=[first, second, third], workspace=workspace)
    window.rating_changed.connect(lambda item: rated.append(item.filename))
    window._choose_rating("favorite")
    assert workspace.statuses[1] == "favorite"
    assert rated == ["eins.jpg"]
    assert window.item().filename == "zwei.jpg"
    window._choose_rating("reserve")
    assert workspace.statuses[2] == "reserve"
    assert window.item().filename == "drei.jpg"
    window._choose_rating("rejected")
    assert workspace.statuses[3] == "rejected"
    assert window.item().filename == "drei.jpg"
    assert window.item().sort_status == "rejected"
    _ = app


def test_media_inspector_pool_advances_to_next_photo(tmp_path: Path) -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from jpeg_fixtures import write_plain_jpeg
    from PySide6.QtWidgets import QApplication

    from travelcore.media.gallery import GalleryItem
    from traveljournal.widgets.media_inspector import MediaInspectorWindow

    class StubWorkspace:
        def __init__(self) -> None:
            self.parked_ids: list[int] = []
            self.unparked_ids: list[int] = []

        def park_media(self, source_file_ids: list[int]) -> None:
            self.parked_ids.extend(source_file_ids)

        def unpark_media(self, source_file_ids: list[int]) -> None:
            self.unparked_ids.extend(source_file_ids)

        def inspector_size(self) -> tuple[int, int]:
            return (720, 520)

        def inspector_maximized(self) -> bool:
            return False

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
    window = MediaInspectorWindow(first, items=[first, second], workspace=StubWorkspace())
    window._toggle_pool()
    assert window.item().filename == "zwei.jpg"
    assert window._items[0].parked is True
    window._toggle_pool()
    assert window.item().filename == "zwei.jpg"
    assert window.item().parked is True
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


def test_inspector_remembers_window_size(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from jpeg_fixtures import write_plain_jpeg
    from PySide6.QtCore import QSize
    from PySide6.QtWidgets import QApplication

    from travelcore.media.gallery import GalleryItem
    from traveljournal.services import workspace as workspace_mod
    from traveljournal.services.workspace import Workspace
    from traveljournal.widgets.media_inspector import MediaInspectorWindow

    monkeypatch.setattr(workspace_mod, "_UI_CONFIG_PATH", tmp_path / "config.json")
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
    workspace = Workspace()
    first = MediaInspectorWindow(item, workspace=workspace)
    first.resize(1100, 640)
    first.close()
    second = MediaInspectorWindow(item, workspace=workspace)
    assert second.size() == QSize(1100, 640)
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


def test_inspector_zoom_loads_full_original(tmp_path: Path) -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from jpeg_fixtures import write_plain_jpeg
    from PySide6.QtCore import QPointF
    from PySide6.QtWidgets import QApplication

    from travelcore.media.gallery import GalleryItem
    from traveljournal.widgets.media_inspector import MediaInspectorWindow, wait_inspector_decodes

    app = QApplication.instance() or QApplication([])
    original = write_plain_jpeg(tmp_path / "foto.jpg", size=(2400, 1800))
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
    window = MediaInspectorWindow(item)
    window._image.resize(640, 480)
    wait_inspector_decodes()
    fitted = window._image.source()
    assert max(fitted.width(), fitted.height()) <= 1920
    assert max(fitted.width(), fitted.height()) < 2400
    window._image.zoom_at(2.0, QPointF(320, 240))
    wait_inspector_decodes()
    assert window._image.zoom == 2.0
    full = window._image.source()
    assert max(full.width(), full.height()) == 2400
    _ = app


def test_inspector_map_opens_thumbnail_then_original_on_double_click(tmp_path: Path) -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from jpeg_fixtures import write_plain_jpeg
    from PySide6.QtWidgets import QApplication

    from travelcore.media.gallery import GalleryItem
    from traveljournal.widgets.media_inspector import MediaInspectorWindow, wait_inspector_decodes

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
    wait_inspector_decodes()
    assert window._image.source().width() == 200
    _ = app


def test_inspector_display_edge_snaps_to_window_size() -> None:
    from traveljournal.widgets.media_inspector import inspector_display_edge

    assert inspector_display_edge(800, 600) == 1280
    assert inspector_display_edge(1600, 900) == 1600
    assert inspector_display_edge(1920, 1080) == 1920
    assert inspector_display_edge(1921, 1080) == 2560
    assert inspector_display_edge(3000, 2000) == 2560
    assert inspector_display_edge(960, 720, 2.0) == 1920


def test_load_media_pixmap_respects_max_edge(tmp_path: Path) -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from jpeg_fixtures import write_plain_jpeg
    from PySide6.QtWidgets import QApplication

    from travelcore.media.gallery import GalleryItem
    from traveljournal.widgets.media_inspector import load_media_pixmap

    app = QApplication.instance() or QApplication([])
    jpeg = write_plain_jpeg(tmp_path / "foto.jpg", size=(400, 300))
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
    pixmap = load_media_pixmap(item, max_edge=80)
    assert max(pixmap.width(), pixmap.height()) <= 80
    assert pixmap.width() > 0
    _ = app


def test_inspector_shows_thumb_then_loads_original(tmp_path: Path) -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from jpeg_fixtures import write_plain_jpeg
    from PySide6.QtWidgets import QApplication

    from travelcore.media.gallery import GalleryItem
    from traveljournal.widgets.media_inspector import MediaInspectorWindow, wait_inspector_decodes

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
    window = MediaInspectorWindow(item)
    assert window.showing_original()
    assert window._image.source().width() == 40
    wait_inspector_decodes()
    assert window._image.source().width() == 200
    _ = app


def test_inspector_prefetches_neighbor_original(tmp_path: Path) -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from jpeg_fixtures import write_plain_jpeg
    from PySide6.QtWidgets import QApplication

    from travelcore.media.gallery import GalleryItem
    from traveljournal.widgets.media_inspector import MediaInspectorWindow, wait_inspector_decodes

    app = QApplication.instance() or QApplication([])
    first_path = write_plain_jpeg(tmp_path / "eins.jpg", size=(200, 150))
    second_path = write_plain_jpeg(tmp_path / "zwei.jpg", size=(180, 120))
    first_thumb = write_plain_jpeg(tmp_path / "eins_t.jpg", size=(40, 30))
    second_thumb = write_plain_jpeg(tmp_path / "zwei_t.jpg", size=(36, 24))

    def make_item(source_file_id: int, path: Path, filename: str, thumb: Path) -> GalleryItem:
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
            thumbnail_path=thumb,
            sort_status=None,
        )

    first = make_item(1, first_path, "eins.jpg", first_thumb)
    second = make_item(2, second_path, "zwei.jpg", second_thumb)
    window = MediaInspectorWindow(first, items=[first, second])
    wait_inspector_decodes()
    assert window._cache.covering(2, 0, 1280) is not None
    window.step(1)
    assert window.item().filename == "zwei.jpg"
    assert window._image.source().width() == 180
    _ = app


def test_parse_map_bridge_url_reads_group_key() -> None:
    from traveljournal.views.map_view import (
        MAP_PAGE_SETUP_JS,
        mark_cover_js,
        parse_map_bridge_url,
        parse_map_expand_console,
        parse_map_media_console,
        parse_map_media_url,
        parse_map_place_cancel_console,
        parse_map_place_console,
        parse_map_view,
        restore_map_view_js,
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
    assert parse_map_place_console("traveljournal:place:46.5:11.3") == (46.5, 11.3)
    assert parse_map_place_console("traveljournal:place:-33.9:-18.4") == (-33.9, -18.4)
    assert parse_map_place_console("leaflet ready") is None
    assert parse_map_place_cancel_console("traveljournal:place-cancel") is True
    assert parse_map_place_cancel_console("traveljournal:place:46.5:11.3") is False
    assert parse_map_view([46.5, 11.3, 14]) == (46.5, 11.3, 14.0)
    assert parse_map_view({"lat": 46.5, "lng": 11.3, "zoom": 12}) == (46.5, 11.3, 12.0)
    assert parse_map_view({"lat": 46.5, "lon": 11.3, "zoom": 12}) == (46.5, 11.3, 12.0)
    assert parse_map_view(None) is None
    assert parse_map_view("nope") is None
    script = restore_map_view_js(46.5, 11.3, 14)
    assert "traveljournalRestoreView(46.5000000000, 11.3000000000, 14.000000)" in script
    assert "traveljournalKeepFocus" in script
    assert mark_cover_js("section:7") == (
        'if (window.traveljournalMarkCover) traveljournalMarkCover("section:7");'
    )
    assert "traveljournalSetPlaceMode" in MAP_PAGE_SETUP_JS
    assert "traveljournalCaptureView" in MAP_PAGE_SETUP_JS
    assert "traveljournalRestoreView" in MAP_PAGE_SETUP_JS
    assert "pointerup" in MAP_PAGE_SETUP_JS
    assert "traveljournalCoverActivate" in MAP_PAGE_SETUP_JS
    assert "traveljournalCenterCover" in MAP_PAGE_SETUP_JS
    assert "traveljournalFitCoverPack" in MAP_PAGE_SETUP_JS
    assert "getBoundingClientRect" not in MAP_PAGE_SETUP_JS
    assert "layer.getLatLng" in MAP_PAGE_SETUP_JS
    assert "zoom: {animate: false}" in MAP_PAGE_SETUP_JS
    assert "getContainer" in MAP_PAGE_SETUP_JS
    assert "window._tjPageSetup" in MAP_PAGE_SETUP_JS


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


def test_map_view_refresh_applies_pending_instead_of_live_reuse(tmp_path: Path) -> None:
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
    opened = store.create(tmp_path / "reise_karte_stale", "Karte")
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
    first = workspace.render_map()
    view = MapView(workspace)
    view._on_prepared(view._generation, opened.directory, first)
    assert view._pending_result is first
    rebuilt = workspace.render_map(force=True)
    view._live_stale = True
    view._pending_result = rebuilt
    view.refresh()
    assert view._pending_result is None
    assert view._desired_seq == rebuilt.render_seq
    assert not view._live_stale
    view._live_stale = True
    view._preparing = True
    assert not view._reuse_live_map()
    _ = app


def test_map_timeline_strip_centers_first_card() -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from datetime import UTC, date, datetime

    from PySide6.QtCore import QEvent, QPointF, QRectF, Qt
    from PySide6.QtGui import QCursor, QMouseEvent
    from PySide6.QtWidgets import QApplication

    from travelcore.maps.groups import MapTimelineCard
    from travelcore.timeline.sections import KIND_DAY, KIND_MOVEMENT, KIND_STAY
    from traveljournal.widgets.map_timeline import (
        CARD_HEIGHT,
        CARD_IDLE_SCALE,
        CARD_WIDTH,
        MapTimelineStrip,
        cover_dest_rect,
        cursor_on_card_global,
        hexagon_cut,
        nearest_card_index,
        section_card_menu_items,
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
                started_at=datetime(2025, 5, 1, tzinfo=UTC),
                ended_at=datetime(2025, 5, 1, tzinfo=UTC),
            ),
            MapTimelineCard(
                group_key="section:2",
                title="Zwei",
                time_label="am 10.05.2025",
                latitude=47.0,
                longitude=12.0,
                card_kind=KIND_MOVEMENT,
                started_at=datetime(2025, 5, 10, tzinfo=UTC),
                ended_at=datetime(2025, 5, 10, tzinfo=UTC),
            ),
            MapTimelineCard(
                group_key="day:3",
                title="Drei",
                time_label="am 03.05.2025",
                latitude=48.0,
                longitude=13.0,
                card_kind=KIND_DAY,
            ),
            MapTimelineCard(
                group_key="section:9",
                title="Ohne Ort",
                time_label="am 09.05.2025",
                latitude=None,
                longitude=None,
                card_kind=KIND_STAY,
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
    assert titles == ["Eins", "Zwei", "Drei", "Ohne Ort"]
    assert strip._widgets[3].card.needs_pin is True
    assert strip._widgets[0].card.needs_pin is False
    assert section_card_menu_items(strip._widgets[0].card) == (
        ("Platzieren", False),
        ("Verschieben", True),
        ("Zentrieren", True),
    )
    assert section_card_menu_items(strip._widgets[3].card) == (
        ("Platzieren", True),
        ("Verschieben", False),
        ("Zentrieren", False),
    )
    assert section_card_menu_items(strip._widgets[2].card) == ()
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
    lines = [child for child in strip._inner.children() if child.objectName() == "mapTimelineJoin"]
    assert len(lines) == 3
    added: list[object] = []
    strip.add_between.connect(added.append)
    lines[0]._plus.clicked.emit()
    assert len(added) == 1
    start, end = added[0]
    assert start == date(2025, 5, 2)
    assert end == date(2025, 5, 9)
    again = len(focused)
    strip.center_on("section:2")
    app.processEvents()
    assert focused[-1] == "section:2"
    assert len(focused) == again + 1
    before = len(focused)
    strip.set_cards(strip._cards)
    app.processEvents()
    assert strip.focused_key() == "section:2"
    assert len(focused) == before
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
    card = strip._widgets[2]
    local = QPointF(card.width() / 2, card.height() / 2)
    card.mouseReleaseEvent(
        QMouseEvent(
            QEvent.Type.MouseButtonRelease,
            local,
            local,
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
    )
    app.processEvents()
    expected = cursor_on_card_global(card, 0.5, 0.5)
    cursor = QCursor.pos()
    assert abs(cursor.x() - expected.x()) <= 2
    assert abs(cursor.y() - expected.y()) <= 2
    _ = app


def test_transfer_link_row_keeps_dashed() -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from travelcore.timeline.transfer_links import LINK_DASH_DASHED, LINK_GEOMETRY_LINE
    from travelcore.timeline.types import TimelineLink
    from traveljournal.widgets.transfer_links import TransferLinkRow

    app = QApplication.instance() or QApplication([])
    row = TransferLinkRow(
        TimelineLink(id=3, sort_index=0, geometry=LINK_GEOMETRY_LINE, dash=LINK_DASH_DASHED),
        [],
    )
    assert row.dash.currentData() == LINK_DASH_DASHED
    assert row.to_link(0).dash == LINK_DASH_DASHED
    car = row.symbol.findData("car")
    assert car >= 0
    assert not row.symbol.itemIcon(car).isNull()
    _ = app
