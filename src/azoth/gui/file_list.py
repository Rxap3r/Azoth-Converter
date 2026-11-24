"""The list of files to convert: one card per file, with its status and a remove button."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .. import formats, metadata, resize
from ..converters import ConversionError
from . import icons
from .settings import forget_file_dialog_history
from .theme import LIGHT_COLORS, Colors, repolish
from .widgets import discard, label

# Card states, used by the stylesheet to colour the status line.
WAITING, WORKING, DONE, FAILED, INFO = "waiting", "working", "done", "failed", "info"


def human_size(size: int) -> str:
    for unit in ("bytes", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "bytes" else f"{size:.1f} {unit}"
        size /= 1024
    return ""


class FileCard(QFrame):
    """One file: type badge, name, size, status line, progress bar, links, remove button."""

    def __init__(self, path: Path, fmt: formats.Format | None, owner: FileList) -> None:
        super().__init__()
        self.path = path
        self.output: str | None = None
        self._owner = owner
        self.setProperty("role", "card")
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(lambda pos: owner.show_menu(self, pos))

        self.badge = QLabel(fmt.id.upper()[:4] if fmt else "?")
        self.badge.setProperty("role", "badge")
        self.badge.setProperty("category", fmt.category if fmt else "unknown")
        self.badge.setFixedSize(40, 40)
        self.badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.badge.setToolTip(fmt.name if fmt else "Unknown file type")

        self.name = label(path.name)
        self.name.setStyleSheet("font-weight: 600;")
        self.name.setToolTip(str(path))
        self.name.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        try:
            size = human_size(path.stat().st_size)
        except OSError:
            size = ""
        pixels = resize.picture_size(path) if fmt and fmt.category == formats.IMAGE else None
        if pixels:  # photos: "4032 × 3024 px · 3.2 MB", handy for choosing a new size
            size = " · ".join(part for part in (f"{pixels[0]} × {pixels[1]} px", size) if part)
        self.size = label(size, "small")

        self.status = label("", "status")
        self.status.setProperty("state", INFO)
        self.status.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setTextVisible(False)
        self.progress.setVisible(False)
        self.progress.setAccessibleName(f"Progress of {path.name}")
        self.open_btn = QPushButton("Open")
        self.folder_btn = QPushButton("Show in folder")
        for button in (self.open_btn, self.folder_btn):
            button.setProperty("role", "link")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setVisible(False)
        self.open_btn.clicked.connect(self.open_output)
        self.folder_btn.clicked.connect(self.open_folder)

        self.metadata_btn = QPushButton()  # photos only: what's hidden in the file
        self.metadata_btn.setProperty("role", "icon")
        self.metadata_btn.setToolTip("Show metadata (location, camera, date …)")
        self.metadata_btn.setAccessibleName(f"Show the metadata of {path.name}")
        if fmt is None or fmt.id not in metadata.CLEANABLE:
            self.metadata_btn.hide()
        self.metadata_btn.clicked.connect(lambda: owner.show_metadata(owner.cards.index(self)))

        self.remove_btn = QPushButton()
        self.remove_btn.setProperty("role", "icon")
        self.remove_btn.setToolTip("Remove from list")
        self.remove_btn.setAccessibleName(f"Remove {path.name} from the list")
        self.remove_btn.clicked.connect(lambda: owner.remove_card(self))

        top = QHBoxLayout()
        top.setSpacing(8)
        top.addWidget(self.name, 1)
        top.addWidget(self.size)
        status_row = QHBoxLayout()
        status_row.setSpacing(10)
        status_row.addWidget(self.status, 1)
        status_row.addWidget(self.progress, 2)
        status_row.addWidget(self.open_btn)
        status_row.addWidget(self.folder_btn)
        text = QVBoxLayout()
        text.setSpacing(3)
        text.addLayout(top)
        text.addLayout(status_row)

        row = QHBoxLayout(self)
        row.setContentsMargins(14, 10, 8, 10)
        row.setSpacing(14)
        row.addWidget(self.badge)
        row.addLayout(text, 1)
        row.addWidget(self.metadata_btn)
        row.addWidget(self.remove_btn)

    def set_state(self, state: str, text: str, tooltip: str = "") -> None:
        self.status.setText(text)
        self.status.setToolTip(tooltip)
        self.status.setProperty("state", state)
        repolish(self.status)
        self.progress.setVisible(state == WORKING)
        has_output = state == DONE and bool(self.output)
        self.open_btn.setVisible(has_output)
        self.folder_btn.setVisible(has_output)

    def mouseDoubleClickEvent(self, event) -> None:
        self.open_output()
        super().mouseDoubleClickEvent(event)

    def open_output(self) -> None:
        if self.output:
            QDesktopServices.openUrl(QUrl.fromLocalFile(self.output))

    def open_folder(self) -> None:
        if self.output:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(self.output).parent)))


class FileList(QWidget):
    """The files and their status. ``files`` and ``formats`` are in the order shown."""

    changed = Signal()  # files were added or removed

    def __init__(self) -> None:
        super().__init__()
        self.files: list[Path] = []
        self.formats: list[formats.Format | None] = []  # None: unknown file type
        self.cards: list[FileCard] = []
        self._busy = False
        self._colors: Colors = LIGHT_COLORS

        self.add_btn = QPushButton("Add files…")
        self.add_btn.clicked.connect(self.choose_files)
        self.clear_btn = QPushButton("Clear list")
        self.clear_btn.clicked.connect(self.clear)

        self._column = QWidget()
        self._cards_layout = QVBoxLayout(self._column)
        self._cards_layout.setContentsMargins(0, 0, 4, 0)
        self._cards_layout.setSpacing(8)
        self.empty_label = label("No files yet. Drag files into this window to start.", "muted")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._cards_layout.addWidget(self.empty_label)
        self._cards_layout.addStretch(1)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setWidget(self._column)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.scroll)
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
            card = FileCard(path, fmt, self)
            if fmt is None:
                card.set_state(INFO, "Unknown file type, will be skipped")
            self._cards_layout.insertWidget(len(self.cards), card)
            self.cards.append(card)
            self.files.append(path)
            self.formats.append(fmt)
            known.add(path.resolve())
            added = True
        if added:
            self.apply_colors(self._colors)
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
            card = self.cards.pop(row)
            discard(card)
            del self.files[row]
            del self.formats[row]
        self._changed()

    def remove_card(self, card: FileCard) -> None:
        if card in self.cards:
            self.remove_rows([self.cards.index(card)])

    def clear(self) -> None:
        self.remove_rows(range(len(self.cards)))

    def choose_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "Choose files to convert")
        forget_file_dialog_history()
        self.add_files(paths)

    # --- status -----------------------------------------------------------------

    def set_status(
        self,
        row: int,
        text: str,
        *,
        tooltip: str = "",
        output: str | None = None,
        state: str = INFO,
    ) -> None:
        """Show ``text`` for a file. ``output`` is the result that Open shows."""
        card = self.cards[row]
        if output is not None:
            card.output = output
        card.set_state(state, text, tooltip)

    def set_progress(self, row: int, fraction: float, message: str) -> None:
        card = self.cards[row]
        card.progress.setValue(int(max(0.0, min(1.0, fraction)) * 1000))
        card.set_state(WORKING, f"{int(fraction * 100)}% {message}".strip())

    def status(self, row: int) -> str:
        return self.cards[row].status.text()

    def status_tooltip(self, row: int) -> str:
        return self.cards[row].status.toolTip()

    def set_busy(self, busy: bool) -> None:
        """While converting, the list can't be changed."""
        self._busy = busy
        for button in (self.add_btn, self.clear_btn, *(c.remove_btn for c in self.cards)):
            button.setEnabled(not busy)

    def apply_colors(self, colors: Colors) -> None:
        self._colors = colors
        for card in self.cards:
            card.remove_btn.setIcon(icons.icon("trash", colors.muted))
            card.metadata_btn.setIcon(icons.icon("info", colors.muted))

    # --- right-click menu and metadata --------------------------------------------

    def show_menu(self, card: FileCard, pos) -> None:
        row = self.cards.index(card)
        menu = QMenu(self)
        show = menu.addAction("Show metadata…")
        fmt = self.formats[row]
        show.setEnabled(fmt is not None and fmt.id in metadata.CLEANABLE)
        show.triggered.connect(lambda: self.show_metadata(row))
        remove = menu.addAction("Remove from list")
        remove.setEnabled(not self._busy)
        remove.triggered.connect(lambda: self.remove_rows([row]))
        menu.exec(card.mapToGlobal(pos))

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
        QMessageBox.information(self, "Metadata", self.metadata_text(row))

    def _changed(self) -> None:
        self._update()
        self.changed.emit()

    def _update(self) -> None:
        self.empty_label.setVisible(not self.cards)
        self.clear_btn.setEnabled(bool(self.cards) and not self._busy)
