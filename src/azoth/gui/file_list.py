"""The list of files to convert, with its buttons and the right-click menu."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMenu,
    QMessageBox,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .. import formats, metadata
from ..converters import ConversionError
from .settings import forget_file_dialog_history

COL_FILE, COL_TYPE, COL_STATUS = range(3)


class FileList(QWidget):
    """Files and their status. Shows a drop hint while empty."""

    changed = Signal()  # files were added or removed

    def __init__(self) -> None:
        super().__init__()
        self.files: list[Path] = []
        self.formats: list[formats.Format | None] = []  # None: unknown file type
        self._busy = False

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["File", "Type", "Status"])
        self.tree.setRootIsDecorated(False)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        header = self.tree.header()
        header.setSectionResizeMode(COL_FILE, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(COL_TYPE, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(COL_STATUS, QHeaderView.ResizeMode.Stretch)
        self.tree.itemDoubleClicked.connect(self._open_output)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._menu)

        self.drop_hint = QLabel("Drag files here, or click “Add files…”")
        self.drop_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.drop_hint.setStyleSheet(
            "border: 2px dashed palette(mid); border-radius: 8px; padding: 40px; font-size: 14px;"
        )

        self.add_btn = QPushButton("Add files…")
        self.add_btn.clicked.connect(self._choose_files)
        self.remove_btn = QPushButton("Remove selected")
        self.remove_btn.clicked.connect(self.remove_selected)
        self.clear_btn = QPushButton("Clear list")
        self.clear_btn.clicked.connect(self.clear)
        buttons = QHBoxLayout()
        for button in (self.add_btn, self.remove_btn, self.clear_btn):
            buttons.addWidget(button)
        buttons.addStretch()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.drop_hint, 1)  # takes the free space while the list is empty
        layout.addWidget(self.tree, 1)
        layout.addLayout(buttons)
        self._update()

    # --- contents -------------------------------------------------------------

    def count(self) -> int:
        return len(self.files)

    def add_files(self, paths: Iterable[Path | str]) -> None:
        """Add files (folders: the files directly inside). Duplicates are ignored."""
        known = {p.resolve() for p in self.files}
        added = False
        for path in self._expand(paths):
            if path.resolve() in known:
                continue
            fmt = formats.detect(path)
            item = QTreeWidgetItem([path.name, fmt.id.upper() if fmt else "?", ""])
            item.setToolTip(COL_FILE, str(path))
            if fmt is None:
                item.setText(COL_STATUS, "Unknown file type, will be skipped")
            self.tree.addTopLevelItem(item)
            self.files.append(path)
            self.formats.append(fmt)
            known.add(path.resolve())
            added = True
        if added:
            self._changed()

    @staticmethod
    def _expand(paths: Iterable[Path | str]) -> Iterable[Path]:
        for raw in paths:
            path = Path(raw)
            if path.is_dir():
                yield from sorted(p for p in path.iterdir() if p.is_file())
            elif path.is_file():
                yield path

    def remove_rows(self, rows: Iterable[int]) -> None:
        if self._busy:
            return
        for row in sorted(set(rows), reverse=True):
            self.tree.takeTopLevelItem(row)
            del self.files[row]
            del self.formats[row]
        self._changed()

    def remove_selected(self) -> None:
        self.remove_rows(self.tree.indexOfTopLevelItem(i) for i in self.tree.selectedItems())

    def clear(self) -> None:
        if self._busy:
            return
        self.tree.clear()
        self.files.clear()
        self.formats.clear()
        self._changed()

    def _choose_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "Choose files to convert")
        forget_file_dialog_history()
        self.add_files(paths)

    # --- status -----------------------------------------------------------------

    def set_status(
        self, row: int, text: str, *, tooltip: str = "", output: str | None = None
    ) -> None:
        """Show ``text`` for a file; ``output`` is opened when the row is double-clicked."""
        item = self.tree.topLevelItem(row)
        item.setText(COL_STATUS, text)
        item.setToolTip(COL_STATUS, tooltip)
        if output is not None:
            item.setData(COL_STATUS, Qt.ItemDataRole.UserRole, output)

    def status(self, row: int) -> str:
        return self.tree.topLevelItem(row).text(COL_STATUS)

    def status_tooltip(self, row: int) -> str:
        return self.tree.topLevelItem(row).toolTip(COL_STATUS)

    def set_busy(self, busy: bool) -> None:
        """While converting, the list can't be changed."""
        self._busy = busy
        for button in (self.add_btn, self.remove_btn, self.clear_btn):
            button.setEnabled(not busy)

    def _open_output(self, item: QTreeWidgetItem) -> None:
        output = item.data(COL_STATUS, Qt.ItemDataRole.UserRole)
        if output:
            QDesktopServices.openUrl(QUrl.fromLocalFile(output))

    # --- right-click menu and metadata --------------------------------------------

    def _menu(self, pos) -> None:
        item = self.tree.itemAt(pos)
        if item is None:
            return
        row = self.tree.indexOfTopLevelItem(item)
        menu = QMenu(self)
        show = menu.addAction("Show metadata…")
        fmt = self.formats[row]
        show.setEnabled(fmt is not None and fmt.id in metadata.CLEANABLE)
        show.triggered.connect(lambda: self.show_metadata(row))
        remove = menu.addAction("Remove from list")
        remove.setEnabled(not self._busy)
        remove.triggered.connect(lambda: self.remove_rows([row]))
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    def metadata_text(self, row: int) -> str:
        path = self.files[row]
        try:
            found = metadata.inspect(path)
        except ConversionError as exc:
            return str(exc)
        if not found:
            return f"{path.name} contains no metadata."
        lines = "\n".join(f"• {f}" for f in found)
        return f"{path.name} contains:\n\n{lines}"

    def show_metadata(self, row: int) -> None:
        QMessageBox.information(self, "Photo metadata", self.metadata_text(row))

    def _changed(self) -> None:
        self._update()
        self.changed.emit()

    def _update(self) -> None:
        has_files = bool(self.files)
        self.drop_hint.setVisible(not has_files)
        self.tree.setVisible(has_files)
