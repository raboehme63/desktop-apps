"""Export page: choose product, flip through a Travelbook preview, pick format at export."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QByteArray, QMimeData, QSize, Qt, QThreadPool, Signal
from PySide6.QtGui import QDrag, QIcon, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from travelcore.config import AppSettings
from travelcore.exceptions import ExportError, ProjectError
from traveljournal.ui.errors import report_exception
from travelcore.export.book import export_rotations, export_sources
from travelcore.export.catalog import (
    default_page_size_id,
    first_path,
    list_page_sizes,
    list_photo_layouts,
    list_product_ids,
    load_catalog,
    load_product,
    page_size,
    product_formats,
)
from travelcore.export.cewe import export_mcf_filename, normalize_mcf_save_path
from travelcore.export.document import (
    TravelbookDocument,
    add_spread,
    apply_photo_layout,
    document_path,
    layout_is_photos,
    load_or_create,
    remove_spread,
    replace_chapter,
    replace_elements,
    replace_page,
    replace_spread,
    save_document,
)
from travelcore.export.html import (
    export_interactive_dirname,
    normalize_html_dir,
    unique_export_dir,
)
from travelcore.export.pdf import export_filename, normalize_pdf_save_path, unique_export_path
from travelcore.export.photo_layouts import layout_from_frames, save_user_layout
from travelcore.export.quality import DEFAULT_QUALITY_ID, list_pdf_qualities
from traveljournal.services.workers import (
    ExportInteractiveRunnable,
    ExportMcfRunnable,
    ExportPdfRunnable,
)
from traveljournal.services.workspace import Workspace
from traveljournal.views.photo_templates_dialog import (
    PhotoTemplateDialog,
    frames_from_elements,
    layout_preview_icon,
)
from traveljournal.widgets.book_preview import BookPreview, leaves_from_document, leaves_from_snapshot
from traveljournal.widgets.gallery import POOL_MIME, encode_pool_source_ids
from traveljournal.widgets.photo_canvas import BookMedia


def _label(value: object, fallback: str) -> str:
    if isinstance(value, dict):
        text = value.get("de") or value.get("en")
        if text:
            return str(text)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return fallback


def _format_caption(format_id: str) -> str:
    for item in load_catalog().get("formats") or []:
        if isinstance(item, dict) and item.get("id") == format_id:
            return _label(item.get("label"), format_id.upper())
    return format_id.upper()


def _product_is_book(product_id: str) -> bool:
    layout = load_product(product_id).get("layout")
    return isinstance(layout, dict) and layout.get("kind") == "book"


class _MediaTray(QListWidget):
    """Section media for drag-and-drop onto photo pages."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("bookMediaTray")
        self.setViewMode(QListWidget.ViewMode.IconMode)
        self.setFlow(QListWidget.Flow.LeftToRight)
        self.setWrapping(False)
        self.setMovement(QListWidget.Movement.Static)
        self.setIconSize(QSize(56, 56))
        self.setSpacing(6)
        self.setMaximumHeight(84)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)

    def set_media(self, media: tuple[BookMedia, ...]) -> None:
        self.clear()
        for item in media:
            row = QListWidgetItem()
            pixmap = QPixmap(str(item.thumbnail_path)) if item.thumbnail_path.is_file() else QPixmap()
            if not pixmap.isNull():
                row.setIcon(QIcon(pixmap))
            row.setToolTip(item.thumbnail_path.name)
            row.setData(Qt.ItemDataRole.UserRole, item.source_file_id)
            row.setSizeHint(QSize(64, 64))
            self.addItem(row)

    def startDrag(self, supported: Qt.DropAction) -> None:  # noqa: N802
        del supported
        ids = [
            int(item.data(Qt.ItemDataRole.UserRole))
            for item in self.selectedItems()
            if item.data(Qt.ItemDataRole.UserRole) is not None
        ]
        if not ids:
            return
        mime = QMimeData()
        mime.setData(POOL_MIME, QByteArray(encode_pool_source_ids(ids)))
        drag = QDrag(self)
        drag.setMimeData(mime)
        current = self.currentItem()
        if current is not None and not current.icon().isNull():
            drag.setPixmap(current.icon().pixmap(QSize(48, 48)))
        drag.exec(Qt.DropAction.CopyAction)


def _choice_button(caption: str, key: str, on_pick: Callable[[str], None]) -> QPushButton:
    button = QPushButton(caption)
    button.setObjectName("exportChoice")
    button.setCheckable(True)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    button.clicked.connect(lambda _checked=False, value=key: on_pick(value))
    return button


class ExportFormatDialog(QDialog):
    """Ask for an output format supported by the chosen product."""

    def __init__(
        self,
        product_id: str,
        parent: QWidget | None = None,
        *,
        quality_id: str = DEFAULT_QUALITY_ID,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Exportieren")
        self.setModal(True)
        self._product_id = product_id
        allowed = product_formats(product_id)
        preferred = first_path()[1]
        self._format_id = preferred if preferred in allowed else (allowed[0] if allowed else "")
        known = {item.id for item in list_pdf_qualities()}
        self._quality_id = quality_id if quality_id in known else DEFAULT_QUALITY_ID
        self._buttons: dict[str, QPushButton] = {}
        self._quality_buttons: dict[str, QPushButton] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(12)
        product = load_product(product_id)
        intro = QLabel(
            f"Format für {_label(product.get('label'), product_id)}. "
            "Nur unterstützte Formate stehen zur Wahl."
        )
        intro.setObjectName("pageSubtitle")
        intro.setWordWrap(True)
        root.addWidget(intro)
        grid = QGridLayout()
        grid.setSpacing(8)
        group = QButtonGroup(self)
        group.setExclusive(True)
        for index, format_id in enumerate(allowed):
            button = _choice_button(_format_caption(format_id), format_id, self._pick)
            button.setChecked(format_id == self._format_id)
            group.addButton(button)
            self._buttons[format_id] = button
            grid.addWidget(button, index // 3, index % 3)
        root.addLayout(grid)

        self._quality_host = QWidget()
        quality_layout = QVBoxLayout(self._quality_host)
        quality_layout.setContentsMargins(0, 4, 0, 0)
        quality_layout.setSpacing(8)
        quality_caption = QLabel("Qualität")
        quality_caption.setObjectName("fieldCaption")
        quality_layout.addWidget(quality_caption)
        quality_grid = QGridLayout()
        quality_grid.setSpacing(8)
        quality_group = QButtonGroup(self)
        quality_group.setExclusive(True)
        for index, item in enumerate(list_pdf_qualities()):
            button = _choice_button(item.label_de, item.id, self._pick_quality)
            button.setObjectName("exportQualityChoice")
            button.setChecked(item.id == self._quality_id)
            button.setToolTip(item.note_de)
            quality_group.addButton(button)
            self._quality_buttons[item.id] = button
            quality_grid.addWidget(button, index // 3, index % 3)
        quality_layout.addLayout(quality_grid)
        self._quality_note = QLabel("")
        self._quality_note.setObjectName("pageSubtitle")
        self._quality_note.setWordWrap(True)
        quality_layout.addWidget(self._quality_note)
        root.addWidget(self._quality_host)

        self._cewe_note = QLabel(
            "Schreibt ein CEWE-Projekt (.mcf) zum Öffnen im Creator. "
            "Fotos und Texte bleiben editierbar; Karte, Länderumrisse und die "
            "Intro-Zeitleiste sind austauschbare Bilder."
        )
        self._cewe_note.setObjectName("pageSubtitle")
        self._cewe_note.setWordWrap(True)
        root.addWidget(self._cewe_note)

        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        box.button(QDialogButtonBox.StandardButton.Ok).setText("Exportieren")
        box.button(QDialogButtonBox.StandardButton.Cancel).setText("Abbrechen")
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        box.button(QDialogButtonBox.StandardButton.Ok).setEnabled(bool(allowed))
        root.addWidget(box)
        self._sync_quality()

    def selected_format(self) -> str:
        return self._format_id

    def selected_quality(self) -> str:
        return self._quality_id

    def _pick(self, format_id: str) -> None:
        self._format_id = format_id
        self._sync_quality()

    def _pick_quality(self, quality_id: str) -> None:
        self._quality_id = quality_id
        self._sync_quality()

    def _sync_quality(self) -> None:
        pdf = self._format_id == "pdf"
        self._quality_host.setVisible(pdf)
        self._cewe_note.setVisible(self._format_id == "cewe")
        for quality_id, button in self._quality_buttons.items():
            button.setChecked(quality_id == self._quality_id)
        if not pdf:
            self._quality_note.setText("")
            return
        chosen = next((item for item in list_pdf_qualities() if item.id == self._quality_id), None)
        self._quality_note.setText(chosen.note_de if chosen is not None else "")


class ExportView(QWidget):
    export_progress = Signal(int, int, str)
    export_finished = Signal()

    def __init__(self, workspace: Workspace, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.workspace = workspace
        self._pool = QThreadPool.globalInstance()
        self._exporting = False
        self._product_id, _default_format = first_path()
        self._page_size_id = default_page_size_id()
        self._photo_layout_id = ""
        self._photo_layouts: dict[str, str] = {}
        self._last_edit_side = "recto"
        self._spread_overlap = False
        self._mode = "export"
        self._choices_collapsed = False
        self._product_buttons: dict[str, QPushButton] = {}
        self._page_buttons: dict[str, QPushButton] = {}
        self._layout_buttons: dict[str, QPushButton] = {}
        self._mode_buttons: dict[str, QPushButton] = {}
        self._document: TravelbookDocument | None = None
        self._pdf_quality_id = DEFAULT_QUALITY_ID

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 12, 24, 12)
        root.setSpacing(10)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
        self._mode_group = QButtonGroup(self)
        self._mode_group.setExclusive(True)
        for key, caption in (("export", "Vorschau"), ("edit", "Editiermodus")):
            button = _choice_button(caption, key, self._select_mode)
            self._mode_group.addButton(button)
            self._mode_buttons[key] = button
            toolbar.addWidget(button)
        toolbar.addStretch(1)
        self._export_button = QPushButton("Exportieren")
        self._export_button.setObjectName("primary")
        self._export_button.clicked.connect(self._export)
        toolbar.addWidget(self._export_button)
        root.addLayout(toolbar)

        choices = QFrame()
        choices.setObjectName("card")
        choices.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        choice_layout = QVBoxLayout(choices)
        choice_layout.setContentsMargins(16, 10, 16, 10)
        choice_layout.setSpacing(8)

        header = QHBoxLayout()
        header.setSpacing(8)
        self._choices_summary = QLabel("Auswahl")
        self._choices_summary.setObjectName("fieldCaption")
        self._collapse_button = QPushButton("▲")
        self._collapse_button.setObjectName("exportCollapse")
        self._collapse_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._collapse_button.setToolTip("Auswahl einklappen")
        self._collapse_button.clicked.connect(self._toggle_choices)
        header.addWidget(self._choices_summary, 1)
        header.addWidget(self._collapse_button)
        choice_layout.addLayout(header)

        self._choices_body = QWidget()
        body_layout = QVBoxLayout(self._choices_body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(8)

        type_caption = QLabel("Ausgabetyp")
        type_caption.setObjectName("fieldCaption")
        body_layout.addWidget(type_caption)
        type_row = QHBoxLayout()
        type_row.setSpacing(8)
        self._product_group = QButtonGroup(self)
        self._product_group.setExclusive(True)
        for product_id in list_product_ids():
            product = load_product(product_id)
            button = _choice_button(
                _label(product.get("label"), product_id),
                product_id,
                self._select_product,
            )
            button.setToolTip(_label(product.get("description"), ""))
            self._product_group.addButton(button)
            self._product_buttons[product_id] = button
            type_row.addWidget(button)
        type_row.addStretch(1)
        body_layout.addLayout(type_row)
        self._product_hint = QLabel("")
        self._product_hint.setObjectName("pageSubtitle")
        self._product_hint.setWordWrap(True)
        body_layout.addWidget(self._product_hint)

        self._size_caption = QLabel("Seitenverhältnis")
        self._size_caption.setObjectName("fieldCaption")
        body_layout.addWidget(self._size_caption)
        self._size_row_host = QWidget()
        size_row = QHBoxLayout(self._size_row_host)
        size_row.setContentsMargins(0, 0, 0, 0)
        size_row.setSpacing(8)
        self._page_group = QButtonGroup(self)
        self._page_group.setExclusive(True)
        for item in list_page_sizes():
            size_id = str(item["id"])
            button = _choice_button(
                _label(item.get("label"), size_id),
                size_id,
                self._select_page_size,
            )
            width = item.get("width_mm")
            height = item.get("height_mm")
            button.setToolTip(f"{width} × {height} mm")
            self._page_group.addButton(button)
            self._page_buttons[size_id] = button
            size_row.addWidget(button)
        self._overlap_button = _choice_button("Über die Mitte", "overlap", self._toggle_spread_overlap)
        self._overlap_button.setObjectName("exportSpreadOverlap")
        self._overlap_button.setToolTip(
            "Fotos dürfen über die Bindung ragen. Die Lücke entfällt, eine Linie markiert die Mitte."
        )
        size_row.addWidget(self._overlap_button)
        size_row.addStretch(1)
        body_layout.addWidget(self._size_row_host)

        layout_header = QHBoxLayout()
        layout_header.setSpacing(8)
        self._layout_caption = QLabel("Fotoseiten")
        self._layout_caption.setObjectName("fieldCaption")
        self._manage_layouts_button = QPushButton("Vorlagen…")
        self._manage_layouts_button.setObjectName("exportManageTemplates")
        self._manage_layouts_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._manage_layouts_button.setToolTip("Vorlagen für das gewählte Seitenverhältnis verwalten.")
        self._manage_layouts_button.clicked.connect(self._manage_templates)
        layout_header.addWidget(self._layout_caption, 1)
        layout_header.addWidget(self._manage_layouts_button)
        body_layout.addLayout(layout_header)
        self._layout_row_host = QWidget()
        self._layout_grid = QGridLayout(self._layout_row_host)
        self._layout_grid.setContentsMargins(0, 0, 0, 0)
        self._layout_grid.setHorizontalSpacing(6)
        self._layout_grid.setVerticalSpacing(6)
        self._layout_group = QButtonGroup(self)
        self._layout_group.setExclusive(True)
        body_layout.addWidget(self._layout_row_host)
        choice_layout.addWidget(self._choices_body)
        root.addWidget(choices)

        self._preview = BookPreview()
        self._preview.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._preview.pageEdited.connect(self._on_page_edited)
        self._preview.currentChanged.connect(self._sync_editor)
        root.addWidget(self._preview, 1)

        self._other_hint = QLabel("")
        self._other_hint.setObjectName("pageSubtitle")
        self._other_hint.setWordWrap(True)
        root.addWidget(self._other_hint, 1)

        self._edit_bar = QWidget()
        actions = QHBoxLayout(self._edit_bar)
        actions.setContentsMargins(0, 0, 0, 0)
        self._add_spread_button = QPushButton("Doppelseite hinzufügen")
        self._add_spread_button.setToolTip("Leere Fotoseiten nach dem aktuellen Abschnitt.")
        self._add_spread_button.clicked.connect(self._add_spread)
        self._remove_spread_button = QPushButton("Doppelseite entfernen")
        self._remove_spread_button.setToolTip("Nur zusätzliche Spreads, nicht die erste Abschnittsseite.")
        self._remove_spread_button.clicked.connect(self._remove_spread)
        self._save_template_button = QPushButton("Seite als Vorlage")
        self._save_template_button.setObjectName("exportSaveTemplate")
        self._save_template_button.setToolTip(
            "Rahmen der zuletzt bearbeiteten Fotoseite für dieses Seitenverhältnis speichern."
        )
        self._save_template_button.clicked.connect(self._save_current_template)
        actions.addWidget(self._add_spread_button)
        actions.addWidget(self._remove_spread_button)
        actions.addWidget(self._save_template_button)
        actions.addStretch(1)
        root.addWidget(self._edit_bar)

        self._tray = _MediaTray()
        root.addWidget(self._tray)

        self._apply_page_size()
        self._rebuild_layout_buttons()
        self._sync_selection()
        self.refresh()

    def refresh(self) -> None:
        snapshot = self.workspace.load_timeline() if self.workspace.current is not None else None
        self._document = None
        if self.workspace.current is not None and snapshot is not None:
            self._document = load_or_create(
                self.workspace.current.directory,
                snapshot,
                page_size=self._page_size_id,
                photo_layout=self._photo_layouts.get(self._page_size_id, self._photo_layout_id),
            )
        if self._document is not None:
            self._photo_layouts = dict(self._document.photo_layouts)
            self._photo_layout_id = self._document.photo_layout
            self._spread_overlap = self._document.spread_overlap
            self._preview.set_spread_overlap(self._spread_overlap)
            self._preview.set_leaves(leaves_from_document(snapshot, self._document))
        else:
            self._preview.set_spread_overlap(self._spread_overlap)
            self._preview.set_leaves(leaves_from_snapshot(snapshot))
        self._preview.set_editable(self._mode == "edit")
        self._rebuild_layout_buttons()
        self._sync_selection()
        self._sync_editor()

    def _rebuild_layout_buttons(self) -> None:
        for button in list(self._layout_buttons.values()):
            self._layout_group.removeButton(button)
            button.setParent(None)
            button.deleteLater()
        self._layout_buttons = {}
        size = page_size(self._page_size_id)
        width = float(size["width_mm"])
        height = float(size["height_mm"])
        for index, item in enumerate(list_photo_layouts(self._page_size_id)):
            layout_id = str(item["id"])
            caption = _label(item.get("label"), layout_id)
            count = item.get("photo_count")
            if item.get("builtin") and isinstance(count, int):
                text = str(count)
            else:
                text = caption if len(caption) <= 12 else f"{caption[:11]}…"
            button = QPushButton(text)
            button.setObjectName("exportLayoutChoice")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setIcon(layout_preview_icon(item.get("slots"), width_mm=width, height_mm=height))
            button.setIconSize(QSize(40, 40))
            button.setToolTip(caption)
            button.clicked.connect(lambda _checked=False, value=layout_id: self._select_photo_layout(value))
            self._layout_group.addButton(button)
            self._layout_buttons[layout_id] = button
            self._layout_grid.addWidget(button, index // 4, index % 4)

    def _select_product(self, product_id: str) -> None:
        self._product_id = product_id
        self._sync_selection()
        self._sync_editor()

    def _toggle_spread_overlap(self, _key: str = "") -> None:
        self._spread_overlap = self._overlap_button.isChecked()
        self._preview.set_spread_overlap(self._spread_overlap)
        if self._document is not None:
            self._document = replace(self._document, spread_overlap=self._spread_overlap)
            self._save_document()
        self._sync_selection()

    def _select_page_size(self, size_id: str) -> None:
        self._page_size_id = size_id
        self._photo_layout_id = self._photo_layouts.get(size_id, "")
        self._apply_page_size()
        if self._document is not None and self.workspace.current is not None:
            self._document = replace(self._document, page_size=size_id)
            self._photo_layout_id = self._document.photo_layout
            save_document(document_path(self.workspace.current.directory), self._document)
        self._rebuild_layout_buttons()
        self._sync_selection()

    def _select_photo_layout(self, layout_id: str) -> None:
        if not layout_is_photos(layout_id):
            return
        already = layout_id == self._photo_layout_id
        self._photo_layout_id = layout_id
        self._photo_layouts[self._page_size_id] = layout_id
        document = self._document
        if document is not None and not already:
            snapshot = self.workspace.load_timeline() if self.workspace.current is not None else None
            self._document = apply_photo_layout(document, layout_id, snapshot)
            self._photo_layouts = dict(self._document.photo_layouts)
            self._save_document()
            self._reload_leaves()
        self._sync_selection()

    def _select_mode(self, mode: str) -> None:
        self._mode = mode
        self._preview.set_editable(mode == "edit")
        self._sync_selection()
        self._sync_editor()

    def _toggle_choices(self) -> None:
        self._choices_collapsed = not self._choices_collapsed
        self._sync_selection()

    def _apply_page_size(self) -> None:
        size = page_size(self._page_size_id)
        self._preview.set_page_size(float(size["width_mm"]), float(size["height_mm"]))

    def _current_photo_frames(self):
        leaf = self._preview.current_leaf()
        if leaf is None or leaf.variant not in {"section", "extra"}:
            return ()
        first = leaf.right_elements if self._last_edit_side == "recto" else leaf.left_elements
        second = leaf.left_elements if self._last_edit_side == "recto" else leaf.right_elements
        if first:
            return frames_from_elements(first)
        if second:
            return frames_from_elements(second)
        return ()

    def _manage_templates(self) -> None:
        size = page_size(self._page_size_id)
        dialog = PhotoTemplateDialog(
            page_size_id=self._page_size_id,
            page_size_label=_label(size.get("label"), self._page_size_id),
            width_mm=float(size["width_mm"]),
            height_mm=float(size["height_mm"]),
            current_frames=self._current_photo_frames(),
            parent=self,
        )
        dialog.exec()
        if dialog.library_changed():
            self._rebuild_layout_buttons()
            self._sync_selection()

    def _save_current_template(self) -> None:
        frames = self._current_photo_frames()
        if not frames:
            QMessageBox.information(
                self, "Vorlage", "Bitte zuerst eine Fotoseite gestalten (mindestens ein Rahmen)."
            )
            return
        name, ok = QInputDialog.getText(self, "Vorlage speichern", "Name:")
        if not ok:
            return
        try:
            saved = save_user_layout(layout_from_frames(frames, name=name, page_size=self._page_size_id))
        except ExportError as exc:
            QMessageBox.warning(self, "Vorlage", str(exc))
            return
        layout_id = str(saved["id"])
        self._photo_layout_id = layout_id
        self._photo_layouts[self._page_size_id] = layout_id
        self._tag_current_page_layout(layout_id)
        if self._document is not None:
            layouts = dict(self._document.photo_layouts)
            layouts[self._page_size_id] = layout_id
            self._document = replace(self._document, photo_layouts=layouts)
            self._save_document()
        self._rebuild_layout_buttons()
        self._sync_selection()

    def _tag_current_page_layout(self, layout_id: str) -> None:
        leaf = self._preview.current_leaf()
        if leaf is None or leaf.section_id is None or leaf.spread_id is None or self._document is None:
            return
        chapter = self._chapter_for(leaf.section_id)
        if chapter is None:
            return
        spread = next((item for item in chapter.spreads if item.id == leaf.spread_id), None)
        if spread is None:
            return
        side = "recto"
        use_verso = bool(leaf.left_elements or layout_is_photos(leaf.left_layout))
        use_recto = bool(leaf.right_elements or layout_is_photos(leaf.right_layout))
        if use_verso and (self._last_edit_side == "verso" or not use_recto):
            side = "verso"
        page = spread.verso if side == "verso" else spread.recto
        spread = replace_page(spread, side, replace(page, layout=layout_id))
        self._document = replace_chapter(self._document, replace_spread(chapter, spread))

    def _sync_selection(self) -> None:
        for product_id, button in self._product_buttons.items():
            button.setChecked(product_id == self._product_id)
        for size_id, button in self._page_buttons.items():
            button.setChecked(size_id == self._page_size_id)
        for layout_id, button in self._layout_buttons.items():
            button.setChecked(layout_id == self._photo_layout_id)
        for mode, button in self._mode_buttons.items():
            button.setChecked(mode == self._mode)
        self._overlap_button.setChecked(self._spread_overlap)
        product = load_product(self._product_id)
        product_label = _label(product.get("label"), self._product_id)
        self._product_hint.setText(_label(product.get("description"), ""))
        is_book = _product_is_book(self._product_id)
        show_preview = self._product_id == "travelbook"
        size_label = ""
        if is_book:
            size_label = _label(page_size(self._page_size_id).get("label"), self._page_size_id)
        layout_label = ""
        if is_book and layout_is_photos(self._photo_layout_id):
            chosen = self._layout_buttons.get(self._photo_layout_id)
            layout_label = chosen.toolTip() if chosen is not None else self._photo_layout_id
        summary_parts = [product_label]
        if is_book and size_label:
            summary_parts.append(size_label)
        if layout_label:
            summary_parts.append(layout_label)
        if is_book and self._spread_overlap:
            summary_parts.append("Über die Mitte")
        self._choices_summary.setText(" · ".join(summary_parts))
        self._choices_body.setVisible(not self._choices_collapsed)
        self._collapse_button.setText("▼" if self._choices_collapsed else "▲")
        self._collapse_button.setToolTip(
            "Auswahl ausklappen" if self._choices_collapsed else "Auswahl einklappen"
        )
        self._size_caption.setVisible(is_book)
        self._size_row_host.setVisible(is_book)
        self._layout_caption.setVisible(is_book)
        self._layout_row_host.setVisible(is_book)
        self._manage_layouts_button.setVisible(is_book)
        self._preview.setVisible(show_preview)
        editing = self._mode == "edit" and show_preview
        self._edit_bar.setVisible(editing)
        self._add_spread_button.setVisible(editing)
        self._remove_spread_button.setVisible(editing)
        self._save_template_button.setVisible(editing)
        self._tray.setVisible(editing)
        if show_preview:
            self._other_hint.hide()
        elif self._product_id == "travelbook-interactive":
            self._other_hint.setText(
                "Exportiert die Karte als HTML-Ordner. index.html im Browser öffnen: "
                "Karte, Leiste, Tagebuch und YouTube — nur lesen."
            )
            self._other_hint.show()
        else:
            self._other_hint.setText("Jahrbuch-Vorschau folgt.")
            self._other_hint.show()
        self._export_button.setEnabled(self.workspace.current is not None and not self._exporting)

    def _sync_editor(self) -> None:
        leaf = self._preview.current_leaf()
        editing = self._mode == "edit" and self._product_id == "travelbook"
        has_section = leaf is not None and leaf.section_id is not None and self._document is not None
        extra = bool(leaf is not None and leaf.variant == "extra")
        has_frames = bool(self._current_photo_frames())
        self._add_spread_button.setEnabled(editing and has_section)
        self._remove_spread_button.setEnabled(editing and extra)
        self._save_template_button.setEnabled(editing and has_frames)
        media = leaf.media if leaf is not None else ()
        self._tray.set_media(media)
        self._tray.setEnabled(editing and has_section)
        if self.workspace.current is None:
            self._add_spread_button.setToolTip("Zuerst ein Projekt öffnen.")
        elif not has_section:
            self._add_spread_button.setToolTip("Blättern Sie zu einem Reiseabschnitt.")
        else:
            self._add_spread_button.setToolTip(
                "Ziehen verschiebt den Rahmen, Strg+Ziehen das Motiv darin. "
                "Mausrad zoomt, Umschalt+Mausrad dreht gradweise, der Knopf oben dreht frei."
            )

    def _chapter_for(self, section_id: int):
        if self._document is None:
            return None
        return next((item for item in self._document.chapters if item.section_id == section_id), None)

    def _save_document(self) -> None:
        if self._document is None or self.workspace.current is None:
            return
        save_document(document_path(self.workspace.current.directory), self._document)

    def _reload_leaves(self, *, keep_last: bool = False) -> None:
        snapshot = self.workspace.load_timeline() if self.workspace.current is not None else None
        previous = len(self._preview._leaves)
        self._preview.set_leaves(leaves_from_document(snapshot, self._document), keep_index=True)
        if keep_last and len(self._preview._leaves) > previous:
            self._preview._go(len(self._preview._leaves) - 1)
        self._sync_editor()

    def _on_page_edited(self, _index: int, side: str) -> None:
        self._last_edit_side = side
        leaf = self._preview.current_leaf()
        if leaf is None or leaf.section_id is None or leaf.spread_id is None or self._document is None:
            return
        chapter = self._chapter_for(leaf.section_id)
        if chapter is None:
            return
        spread = next((item for item in chapter.spreads if item.id == leaf.spread_id), None)
        if spread is None:
            return
        page = spread.verso if side == "verso" else spread.recto
        elements = leaf.left_elements if side == "verso" else leaf.right_elements
        spread = replace_page(spread, side, replace_elements(page, elements))
        chapter = replace_spread(chapter, spread)
        self._document = replace_chapter(self._document, chapter)
        self._save_document()
        self._sync_editor()

    def _add_spread(self) -> None:
        leaf = self._preview.current_leaf()
        if leaf is None or leaf.section_id is None or self._document is None:
            return
        chapter = self._chapter_for(leaf.section_id)
        if chapter is None:
            return
        self._document = replace_chapter(
            self._document, add_spread(chapter, photo_layout=self._document.photo_layout)
        )
        self._save_document()
        self._reload_leaves(keep_last=True)

    def _remove_spread(self) -> None:
        leaf = self._preview.current_leaf()
        if leaf is None or leaf.section_id is None or leaf.spread_id is None or self._document is None:
            return
        chapter = self._chapter_for(leaf.section_id)
        if chapter is None:
            return
        self._document = replace_chapter(self._document, remove_spread(chapter, leaf.spread_id))
        self._save_document()
        self._reload_leaves()

    def _choose_pdf_destination(self, suggested: Path) -> Path | None:
        suggested.parent.mkdir(parents=True, exist_ok=True)
        chosen, _filter = QFileDialog.getSaveFileName(
            self,
            "PDF speichern unter",
            str(suggested),
            "PDF (*.pdf)",
        )
        if not chosen.strip():
            return None
        return normalize_pdf_save_path(chosen)

    def _choose_mcf_destination(self, suggested: Path) -> Path | None:
        suggested.parent.mkdir(parents=True, exist_ok=True)
        chosen, _filter = QFileDialog.getSaveFileName(
            self,
            "CEWE-Projekt speichern unter",
            str(suggested),
            "CEWE-Projekt (*.mcf)",
        )
        if not chosen.strip():
            return None
        return normalize_mcf_save_path(chosen)

    def _choose_html_destination(self, suggested: Path) -> Path | None:
        suggested.parent.mkdir(parents=True, exist_ok=True)
        chosen, _filter = QFileDialog.getSaveFileName(
            self,
            "HTML-Paket speichern unter",
            str(suggested),
            "HTML-Paket (*)",
        )
        if not chosen.strip():
            return None
        return normalize_html_dir(chosen)

    def _export(self) -> None:
        if self.workspace.current is None:
            QMessageBox.information(self, "Export", "Bitte zuerst ein Projekt öffnen.")
            return
        try:
            self.workspace.require_writable()
        except ProjectError as exc:
            report_exception(self, "Export", exc)
            return
        if self._exporting:
            return
        dialog = ExportFormatDialog(self._product_id, self, quality_id=self._pdf_quality_id)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self._pdf_quality_id = dialog.selected_quality()
        format_id = dialog.selected_format()
        if format_id == "html" and self._product_id == "travelbook-interactive":
            self._export_interactive()
            return
        if format_id not in {"pdf", "cewe"}:
            chosen = _format_caption(format_id)
            QMessageBox.information(
                self,
                "Export",
                f"{chosen}-Datei nach exports/ schreiben folgt. Die Vorschau bleibt das Blätterbuch.",
            )
            return
        if self._product_id != "travelbook":
            label = "PDF" if format_id == "pdf" else "CEWE"
            QMessageBox.information(
                self, "Export", f"{label} gibt es in dieser Version nur für das Travelbook."
            )
            return
        snapshot = self.workspace.load_timeline()
        if snapshot is None or self._document is None:
            QMessageBox.information(self, "Export", "Kein Travelbook zum Exportieren.")
            return
        self._save_document()
        exports = self.workspace.current.directory / "exports"
        if format_id == "cewe":
            suggested = unique_export_path(exports, export_mcf_filename(snapshot.title))
            destination = self._choose_mcf_destination(suggested)
            if destination is None:
                return
            worker = ExportMcfRunnable(
                self._document,
                snapshot,
                destination,
                export_sources(snapshot),
                export_rotations(snapshot),
                host=self,
            )
            worker.signals.progress.connect(self._on_cewe_progress)
            worker.signals.finished.connect(self._on_cewe_finished)
            worker.signals.failed.connect(self._on_cewe_failed)
            self._exporting = True
            self._export_button.setEnabled(False)
            self.export_progress.emit(0, 0, "CEWE-Projekt wird geschrieben…")
            self._pool.start(worker)
            return
        suggested = unique_export_path(exports, export_filename(snapshot.title))
        destination = self._choose_pdf_destination(suggested)
        if destination is None:
            return
        worker = ExportPdfRunnable(
            self._document,
            snapshot,
            destination,
            export_sources(snapshot),
            export_rotations(snapshot),
            quality=dialog.selected_quality(),
            host=self,
        )
        worker.signals.progress.connect(self._on_export_progress)
        worker.signals.finished.connect(self._on_export_finished)
        worker.signals.failed.connect(self._on_export_failed)
        self._exporting = True
        self._export_button.setEnabled(False)
        self.export_progress.emit(0, 0, "PDF wird geschrieben…")
        self._pool.start(worker)

    def _export_interactive(self) -> None:
        if self.workspace.current is None:
            QMessageBox.information(self, "Export", "Bitte zuerst ein Projekt öffnen.")
            return
        snapshot = self.workspace.load_timeline()
        title = snapshot.title if snapshot is not None else ""
        exports = self.workspace.current.directory / "exports"
        suggested = unique_export_dir(exports, export_interactive_dirname(title))
        destination = self._choose_html_destination(suggested)
        if destination is None:
            return
        worker = ExportInteractiveRunnable(
            self.workspace.current,
            destination,
            title=title or "Reise",
            size=AppSettings().default_thumbnail_size,
            map_provider=self.workspace.map_provider(),
            map_link_color=self.workspace.map_link_color(),
            map_track_color=self.workspace.map_track_color(),
            host=self,
        )
        worker.signals.progress.connect(self._on_html_progress)
        worker.signals.finished.connect(self._on_html_finished)
        worker.signals.failed.connect(self._on_html_failed)
        self._exporting = True
        self._export_button.setEnabled(False)
        self.export_progress.emit(0, 0, "Karten-Website wird geschrieben…")
        self._pool.start(worker)

    def _on_html_progress(self, current: int, total: int) -> None:
        self.export_progress.emit(current, total, f"HTML {current}/{total}")

    def _on_html_finished(self, result: object) -> None:
        self._exporting = False
        self._export_button.setEnabled(self.workspace.current is not None)
        self.export_finished.emit()
        path = getattr(result, "output_path", None)
        QMessageBox.information(
            self,
            "Export",
            (
                f"Karten-Website geschrieben:\n{path}\n\n"
                "Ordner so lassen und index.html im Browser öffnen. "
                "Kartenkacheln brauchen eine Internetverbindung."
            )
            if path is not None
            else "Karten-Website geschrieben.",
        )

    def _on_html_failed(self, message: str) -> None:
        self._exporting = False
        self._export_button.setEnabled(self.workspace.current is not None)
        self.export_finished.emit()
        QMessageBox.warning(self, "Export", message or "HTML-Export fehlgeschlagen.")

    def _on_export_progress(self, current: int, total: int) -> None:
        self.export_progress.emit(current, total, f"PDF {current}/{total}")

    def _on_export_finished(self, result: object) -> None:
        self._exporting = False
        self._export_button.setEnabled(self.workspace.current is not None)
        self.export_finished.emit()
        path = getattr(result, "output_path", None)
        QMessageBox.information(
            self,
            "Export",
            f"PDF geschrieben:\n{path}" if path is not None else "PDF geschrieben.",
        )

    def _on_export_failed(self, message: str) -> None:
        self._exporting = False
        self._export_button.setEnabled(self.workspace.current is not None)
        self.export_finished.emit()
        QMessageBox.warning(self, "Export", message or "PDF-Export fehlgeschlagen.")

    def _on_cewe_progress(self, current: int, total: int) -> None:
        self.export_progress.emit(current, total, f"CEWE {current}/{total}")

    def _on_cewe_finished(self, result: object) -> None:
        self._exporting = False
        self._export_button.setEnabled(self.workspace.current is not None)
        self.export_finished.emit()
        path = getattr(result, "output_path", None)
        QMessageBox.information(
            self,
            "Export",
            (f"CEWE-Projekt geschrieben:\n{path}\n\nIm CEWE Creator öffnen und den Feinschliff dort machen.")
            if path is not None
            else "CEWE-Projekt geschrieben.",
        )

    def _on_cewe_failed(self, message: str) -> None:
        self._exporting = False
        self._export_button.setEnabled(self.workspace.current is not None)
        self.export_finished.emit()
        QMessageBox.warning(self, "Export", message or "CEWE-Export fehlgeschlagen.")
