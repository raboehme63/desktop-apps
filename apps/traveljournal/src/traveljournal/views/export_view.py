"""Export page: choose product, flip through a Travelbook preview, pick format at export."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

from PySide6.QtCore import QByteArray, QMimeData, QSize, Qt
from PySide6.QtGui import QDrag, QIcon, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from travelcore.export.catalog import (
    default_page_size_id,
    first_path,
    list_page_sizes,
    list_product_ids,
    load_catalog,
    load_product,
    page_size,
    product_formats,
)
from travelcore.export.document import (
    TravelbookDocument,
    add_spread,
    document_path,
    load_or_create,
    remove_spread,
    replace_chapter,
    replace_elements,
    replace_page,
    replace_spread,
    save_document,
)
from traveljournal.services.workspace import Workspace
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

    def __init__(self, product_id: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Exportieren")
        self.setModal(True)
        self._product_id = product_id
        allowed = product_formats(product_id)
        preferred = first_path()[1]
        self._format_id = preferred if preferred in allowed else (allowed[0] if allowed else "")
        self._buttons: dict[str, QPushButton] = {}

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
        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        box.button(QDialogButtonBox.StandardButton.Ok).setText("Exportieren")
        box.button(QDialogButtonBox.StandardButton.Cancel).setText("Abbrechen")
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        box.button(QDialogButtonBox.StandardButton.Ok).setEnabled(bool(allowed))
        root.addWidget(box)

    def selected_format(self) -> str:
        return self._format_id

    def _pick(self, format_id: str) -> None:
        self._format_id = format_id


class ExportView(QWidget):
    def __init__(self, workspace: Workspace, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.workspace = workspace
        self._product_id, _default_format = first_path()
        self._page_size_id = default_page_size_id()
        self._mode = "export"
        self._choices_collapsed = False
        self._product_buttons: dict[str, QPushButton] = {}
        self._page_buttons: dict[str, QPushButton] = {}
        self._mode_buttons: dict[str, QPushButton] = {}
        self._document: TravelbookDocument | None = None

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
        size_row.addStretch(1)
        body_layout.addWidget(self._size_row_host)
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
        actions.addWidget(self._add_spread_button)
        actions.addWidget(self._remove_spread_button)
        actions.addStretch(1)
        root.addWidget(self._edit_bar)

        self._tray = _MediaTray()
        root.addWidget(self._tray)

        self._apply_page_size()
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
            )
        if self._document is not None:
            self._preview.set_leaves(leaves_from_document(snapshot, self._document))
        else:
            self._preview.set_leaves(leaves_from_snapshot(snapshot))
        self._preview.set_editable(self._mode == "edit")
        self._sync_selection()
        self._sync_editor()

    def _select_product(self, product_id: str) -> None:
        self._product_id = product_id
        self._sync_selection()
        self._sync_editor()

    def _select_page_size(self, size_id: str) -> None:
        self._page_size_id = size_id
        self._apply_page_size()
        if self._document is not None and self.workspace.current is not None:
            self._document = replace(self._document, page_size=size_id)
            save_document(document_path(self.workspace.current.directory), self._document)
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

    def _sync_selection(self) -> None:
        for product_id, button in self._product_buttons.items():
            button.setChecked(product_id == self._product_id)
        for size_id, button in self._page_buttons.items():
            button.setChecked(size_id == self._page_size_id)
        for mode, button in self._mode_buttons.items():
            button.setChecked(mode == self._mode)
        product = load_product(self._product_id)
        product_label = _label(product.get("label"), self._product_id)
        self._product_hint.setText(_label(product.get("description"), ""))
        is_book = _product_is_book(self._product_id)
        show_preview = self._product_id == "travelbook"
        size_label = ""
        if is_book:
            size_label = _label(page_size(self._page_size_id).get("label"), self._page_size_id)
        if is_book and size_label:
            self._choices_summary.setText(f"{product_label} · {size_label}")
        else:
            self._choices_summary.setText(product_label)
        self._choices_body.setVisible(not self._choices_collapsed)
        self._collapse_button.setText("▼" if self._choices_collapsed else "▲")
        self._collapse_button.setToolTip(
            "Auswahl ausklappen" if self._choices_collapsed else "Auswahl einklappen"
        )
        self._size_caption.setVisible(is_book)
        self._size_row_host.setVisible(is_book)
        self._preview.setVisible(show_preview)
        editing = self._mode == "edit" and show_preview
        self._edit_bar.setVisible(editing)
        self._add_spread_button.setVisible(editing)
        self._remove_spread_button.setVisible(editing)
        self._tray.setVisible(editing)
        if show_preview:
            self._other_hint.hide()
        elif self._product_id == "travelbook-interactive":
            self._other_hint.setText(
                "Vorschau der Karten-Website folgt. Nach dem Export: schwenken und zoomen, nur lesen."
            )
            self._other_hint.show()
        else:
            self._other_hint.setText("Jahrbuch-Vorschau folgt.")
            self._other_hint.show()
        self._export_button.setEnabled(self.workspace.current is not None)

    def _sync_editor(self) -> None:
        leaf = self._preview.current_leaf()
        editing = self._mode == "edit" and self._product_id == "travelbook"
        has_section = leaf is not None and leaf.section_id is not None and self._document is not None
        extra = bool(leaf is not None and leaf.variant == "extra")
        self._add_spread_button.setEnabled(editing and has_section)
        self._remove_spread_button.setEnabled(editing and extra)
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

    def _add_spread(self) -> None:
        leaf = self._preview.current_leaf()
        if leaf is None or leaf.section_id is None or self._document is None:
            return
        chapter = self._chapter_for(leaf.section_id)
        if chapter is None:
            return
        self._document = replace_chapter(self._document, add_spread(chapter))
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

    def _export(self) -> None:
        if self.workspace.current is None:
            QMessageBox.information(self, "Export", "Bitte zuerst ein Projekt öffnen.")
            return
        dialog = ExportFormatDialog(self._product_id, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        chosen = _format_caption(dialog.selected_format())
        QMessageBox.information(
            self,
            "Export",
            f"{chosen}-Datei nach exports/ schreiben folgt. Die Vorschau bleibt das Blätterbuch.",
        )
