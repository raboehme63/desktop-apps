"""Manage photo-page templates for the current page size."""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QImage, QPainter, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from travelcore.exceptions import ExportError
from travelcore.export.catalog import list_photo_layouts
from travelcore.export.document import PhotoElement, sorted_by_z
from travelcore.export.geometry import Frame
from travelcore.export.photo_layouts import (
    delete_user_layout,
    is_user_layout,
    layout_from_frames,
    rename_user_layout,
    save_user_layout,
)


def layout_preview_icon(
    slots: object, *, width_mm: float = 210.0, height_mm: float = 297.0
) -> QIcon:
    box = 48
    ratio = max(width_mm, 1.0) / max(height_mm, 1.0)
    if ratio >= 1.0:
        width = box
        height = max(16, int(round(box / ratio)))
    else:
        height = box
        width = max(16, int(round(box * ratio)))
    image = QImage(box, box, QImage.Format.Format_ARGB32)
    image.fill(QColor("#12151c"))
    painter = QPainter(image)
    ox = (box - width) // 2
    oy = (box - height) // 2
    painter.fillRect(ox, oy, width, height, QColor("#151a24"))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#5a9e94"))
    pad = 3
    inner_w = max(2, width - 2 * pad)
    inner_h = max(2, height - 2 * pad)
    listed = slots if isinstance(slots, list) else []
    for slot in listed:
        if not isinstance(slot, dict) or slot.get("type") != "media":
            continue
        x = ox + pad + float(slot.get("x", 0)) / 100.0 * inner_w
        y = oy + pad + float(slot.get("y", 0)) / 100.0 * inner_h
        slot_w = max(2.0, float(slot.get("w", 0)) / 100.0 * inner_w)
        slot_h = max(2.0, float(slot.get("h", 0)) / 100.0 * inner_h)
        painter.drawRoundedRect(QRectF(x, y, slot_w, slot_h), 1.5, 1.5)
    painter.end()
    return QIcon(QPixmap.fromImage(image))


def _caption(value: object, fallback: str) -> str:
    if isinstance(value, dict):
        text = value.get("de") or value.get("en")
        if text:
            return str(text)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return fallback


class PhotoTemplateDialog(QDialog):
    """List, save, rename, and delete templates for one page size."""

    def __init__(
        self,
        *,
        page_size_id: str,
        page_size_label: str,
        width_mm: float,
        height_mm: float,
        current_frames: Sequence[Frame],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Fotoseiten-Vorlagen")
        self.setMinimumSize(420, 420)
        self._page_size_id = page_size_id
        self._width_mm = width_mm
        self._height_mm = height_mm
        self._current_frames = tuple(current_frames)
        self._changed = False

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(12)
        intro = QLabel(
            f"Vorlagen für {page_size_label}. "
            "Standardraster gelten für jedes Format; eigene Vorlagen nur hier."
        )
        intro.setObjectName("pageSubtitle")
        intro.setWordWrap(True)
        root.addWidget(intro)

        self._list = QListWidget()
        self._list.setObjectName("photoTemplateList")
        self._list.setIconSize(QSize(48, 48))
        self._list.currentItemChanged.connect(lambda *_args: self._sync_actions())
        root.addWidget(self._list, 1)

        actions = QHBoxLayout()
        self._save_button = QPushButton("Aktuelle Seite speichern")
        self._save_button.setObjectName("exportSaveTemplate")
        self._save_button.setEnabled(bool(self._current_frames))
        self._save_button.setToolTip(
            "Speichert die Rahmen der zuletzt bearbeiteten Fotoseite."
            if self._current_frames
            else "Zuerst eine Fotoseite gestalten."
        )
        self._save_button.clicked.connect(self._save_current)
        self._rename_button = QPushButton("Umbenennen")
        self._rename_button.clicked.connect(self._rename)
        self._delete_button = QPushButton("Löschen")
        self._delete_button.clicked.connect(self._delete)
        actions.addWidget(self._save_button)
        actions.addWidget(self._rename_button)
        actions.addWidget(self._delete_button)
        actions.addStretch(1)
        root.addLayout(actions)

        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close = box.button(QDialogButtonBox.StandardButton.Close)
        if close is not None:
            close.setText("Schließen")
        box.rejected.connect(self.reject)
        root.addWidget(box)
        self._reload()

    def library_changed(self) -> bool:
        return self._changed

    def _reload(self) -> None:
        current = self._list.currentItem()
        keep = str(current.data(Qt.ItemDataRole.UserRole)) if current is not None else ""
        self._list.clear()
        for item in list_photo_layouts(self._page_size_id):
            layout_id = str(item["id"])
            caption = _caption(item.get("label"), layout_id)
            builtin = bool(item.get("builtin"))
            title = caption if builtin else f"{caption} (eigen)"
            icon = layout_preview_icon(
                item.get("slots"), width_mm=self._width_mm, height_mm=self._height_mm
            )
            row = QListWidgetItem(icon, title)
            row.setData(Qt.ItemDataRole.UserRole, layout_id)
            row.setData(Qt.ItemDataRole.UserRole + 1, builtin)
            row.setToolTip(caption)
            self._list.addItem(row)
            if layout_id == keep:
                self._list.setCurrentItem(row)
        self._sync_actions()

    def _selected(self) -> tuple[str, bool] | None:
        row = self._list.currentItem()
        if row is None:
            return None
        layout_id = str(row.data(Qt.ItemDataRole.UserRole) or "")
        builtin = bool(row.data(Qt.ItemDataRole.UserRole + 1))
        return layout_id, builtin

    def _sync_actions(self) -> None:
        selected = self._selected()
        user = selected is not None and not selected[1] and is_user_layout(selected[0])
        self._rename_button.setEnabled(user)
        self._delete_button.setEnabled(user)

    def _save_current(self) -> None:
        if not self._current_frames:
            return
        name, ok = QInputDialog.getText(self, "Vorlage speichern", "Name:")
        if not ok:
            return
        try:
            saved = save_user_layout(
                layout_from_frames(
                    self._current_frames, name=name, page_size=self._page_size_id
                )
            )
        except ExportError as exc:
            QMessageBox.warning(self, "Vorlage", str(exc))
            return
        self._changed = True
        self._reload()
        for index in range(self._list.count()):
            row = self._list.item(index)
            if row is not None and row.data(Qt.ItemDataRole.UserRole) == saved["id"]:
                self._list.setCurrentItem(row)
                break

    def _rename(self) -> None:
        selected = self._selected()
        if selected is None or selected[1]:
            return
        name, ok = QInputDialog.getText(self, "Vorlage umbenennen", "Name:")
        if not ok:
            return
        try:
            rename_user_layout(selected[0], name)
        except ExportError as exc:
            QMessageBox.warning(self, "Vorlage", str(exc))
            return
        self._changed = True
        self._reload()

    def _delete(self) -> None:
        selected = self._selected()
        if selected is None or selected[1]:
            return
        answer = QMessageBox.question(
            self,
            "Vorlage löschen",
            "Diese eigene Vorlage löschen? Seiten im Buch bleiben unverändert.",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            delete_user_layout(selected[0])
        except ExportError as exc:
            QMessageBox.warning(self, "Vorlage", str(exc))
            return
        self._changed = True
        self._reload()


def frames_from_elements(elements: Sequence[PhotoElement]) -> tuple[Frame, ...]:
    return tuple(item.frame for item in sorted_by_z(elements))
