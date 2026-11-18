"""The "Supported formats" section: every format and what it converts into."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import (
    QHeaderView,
    QLabel,
    QLineEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .. import ranking
from ..format_list import CATEGORY_TITLES, conversion_table

COL_FORMAT, COL_EXTENSIONS, COL_TARGETS, COL_LIBREOFFICE = range(4)


def _names(fmts) -> str:
    return ", ".join(f.id.upper() for f in fmts) if fmts else "–"


class FormatsPanel(QWidget):
    def __init__(self, libreoffice_installed: bool) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        if libreoffice_installed:
            status = "LibreOffice is installed, so every conversion below is available."
        else:
            status = (
                "LibreOffice isn't installed. Conversions in the last column need it "
                "(free download from libreoffice.org)."
            )
        self.status_label = QLabel(status)
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Search, e.g. pdf, heic, word …")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.apply_filter)
        layout.addWidget(self.search)

        self.tree = QTreeWidget()
        headers = ["Format", "File extensions", "Converts to"]
        if not libreoffice_installed:
            headers[2] = "Converts to (works now)"
            headers.append("Needs LibreOffice")
        self.tree.setHeaderLabels(headers)
        self.tree.setAlternatingRowColors(True)
        # Long target lists wrap onto a second line instead of being cut off with "…".
        self.tree.setWordWrap(True)
        self.tree.setTextElideMode(Qt.TextElideMode.ElideNone)
        self.tree.setUniformRowHeights(False)
        self.tree.setMinimumHeight(240)
        header = self.tree.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(COL_FORMAT, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(COL_EXTENSIONS, QHeaderView.ResizeMode.ResizeToContents)
        for col in range(COL_TARGETS, len(headers)):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.Stretch)
        # Qt wraps the text but doesn't grow the rows, so row heights are set by hand
        # whenever a column changes width.
        header.sectionResized.connect(lambda *_: self._update_row_heights())
        layout.addWidget(self.tree)

        self._categories: dict[str, QTreeWidgetItem] = {}
        for category, title in CATEGORY_TITLES.items():
            item = QTreeWidgetItem([title])
            font = item.font(COL_FORMAT)
            font.setBold(True)
            item.setFont(COL_FORMAT, font)
            item.setFirstColumnSpanned(False)
            self.tree.addTopLevelItem(item)
            self._categories[category] = item

        for row in conversion_table():
            fmt = row.format
            if libreoffice_installed:
                everything = ranking.rank(row.right_away + row.needs_libreoffice, [fmt.category])
                columns = [_names(everything)]
            else:
                columns = [_names(row.right_away), _names(row.needs_libreoffice)]
            item = QTreeWidgetItem(
                [f"{fmt.id.upper()}  ({fmt.name})", ", ".join(f".{e}" for e in fmt.extensions)]
                + columns
            )
            for col in range(COL_TARGETS, COL_TARGETS + len(columns)):
                item.setToolTip(col, item.text(col))
            # Searchable text: id, name, extensions and all targets.
            haystack = " ".join(
                [fmt.id, fmt.name, *fmt.extensions]
                + [t.id for t in row.right_away + row.needs_libreoffice]
            ).lower()
            item.setData(COL_FORMAT, Qt.ItemDataRole.UserRole, haystack)
            self._categories[fmt.category].addChild(item)

        self.tree.expandAll()

    def _update_row_heights(self) -> None:
        metrics = QFontMetrics(self.tree.font())
        header = self.tree.header()
        line = metrics.height()
        for category in self._categories.values():
            for i in range(category.childCount()):
                item = category.child(i)
                height = line
                for col in range(COL_TARGETS, self.tree.columnCount()):
                    width = max(20, header.sectionSize(col) - 10)
                    rect = metrics.boundingRect(
                        0, 0, width, 10_000, Qt.TextFlag.TextWordWrap, item.text(col)
                    )
                    height = max(height, rect.height())
                # Set on a stretched column: its width hint is ignored, only the height counts.
                item.setSizeHint(COL_TARGETS, QSize(header.sectionSize(COL_TARGETS), height + 4))

    def showEvent(self, event) -> None:
        super().showEvent(event)
        QTimer.singleShot(0, self._update_row_heights)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        # Wait until the header has stretched its columns to the new width.
        QTimer.singleShot(0, self._update_row_heights)

    def apply_filter(self, text: str) -> None:
        """Show only formats whose name, extension or targets contain ``text``."""
        words = text.lower().split()
        for category in self._categories.values():
            visible_children = 0
            for i in range(category.childCount()):
                child = category.child(i)
                haystack = child.data(COL_FORMAT, Qt.ItemDataRole.UserRole)
                match = all(w.lstrip(".") in haystack for w in words)
                child.setHidden(not match)
                visible_children += match
            category.setHidden(visible_children == 0)

    def visible_formats(self) -> list[str]:
        """Format ids currently shown (used by tests)."""
        ids = []
        for category in self._categories.values():
            if category.isHidden():
                continue
            for i in range(category.childCount()):
                child = category.child(i)
                if not child.isHidden():
                    ids.append(child.text(COL_FORMAT).split()[0].lower())
        return ids
