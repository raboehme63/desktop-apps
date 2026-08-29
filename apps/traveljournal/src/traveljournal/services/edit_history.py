"""Application undo stack for journal edits. travelcore stays command-free."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QUndoCommand, QUndoStack
from PySide6.QtWidgets import QApplication, QLineEdit, QPlainTextEdit, QTextEdit


class _FnCommand(QUndoCommand):
    """Command whose first redo is a no-op because the edit already ran."""

    def __init__(self, title: str, undo_fn: Callable[[], None], redo_fn: Callable[[], None]) -> None:
        super().__init__(title)
        self._undo_fn = undo_fn
        self._redo_fn = redo_fn
        self._first_redo = True

    def redo(self) -> None:
        if self._first_redo:
            self._first_redo = False
            return
        self._redo_fn()

    def undo(self) -> None:
        self._undo_fn()


class EditHistory(QObject):
    applied = Signal()
    index_changed = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._stack = QUndoStack(self)
        self._stack.setUndoLimit(80)
        self._stack.indexChanged.connect(self.index_changed)

    def push(self, title: str, undo_fn: Callable[[], None], redo_fn: Callable[[], None]) -> None:
        self._stack.push(_FnCommand(title, undo_fn, redo_fn))

    def begin_macro(self, title: str) -> None:
        self._stack.beginMacro(title)

    def end_macro(self) -> None:
        self._stack.endMacro()

    def undo(self) -> bool:
        if not self._stack.canUndo():
            return False
        self._stack.undo()
        self.applied.emit()
        return True

    def redo(self) -> bool:
        if not self._stack.canRedo():
            return False
        self._stack.redo()
        self.applied.emit()
        return True

    def clear(self) -> None:
        self._stack.clear()
        self.index_changed.emit()

    def can_undo(self) -> bool:
        return self._stack.canUndo()

    def can_redo(self) -> bool:
        return self._stack.canRedo()

    def undo_text(self) -> str:
        return self._stack.undoText()

    def redo_text(self) -> str:
        return self._stack.redoText()


def undo_focused_text() -> bool:
    widget = QApplication.focusWidget()
    if isinstance(widget, QLineEdit) and widget.isUndoAvailable():
        widget.undo()
        return True
    if isinstance(widget, (QPlainTextEdit, QTextEdit)) and widget.document().isUndoAvailable():
        widget.undo()
        return True
    return False


def redo_focused_text() -> bool:
    widget = QApplication.focusWidget()
    if isinstance(widget, QLineEdit) and widget.isRedoAvailable():
        widget.redo()
        return True
    if isinstance(widget, (QPlainTextEdit, QTextEdit)) and widget.document().isRedoAvailable():
        widget.redo()
        return True
    return False
