"""The "PDF tools" page: Merge, Split, Edit pages (rotate, delete, reorder), Compress,
Password and Make searchable (text recognition).

The work itself is in ``azoth.pdf_tools`` (lossless, no Qt). This page only collects the
choices, runs the job in a background thread and shows the result.
"""

from __future__ import annotations

import threading
import traceback
from collections.abc import Callable, Iterable
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, QRect, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import (
    QDesktopServices,
    QIcon,
    QImage,
    QPixmap,
    QTransform,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QCheckBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLineEdit,
    QListView,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QRadioButton,
    QStackedWidget,
    QStyledItemDelegate,
    QVBoxLayout,
    QWidget,
)

from .. import formats, ocr, pdf_tools, quality
from ..converters import ConversionError
from . import error_log, icons
from .file_list import DONE, FAILED, INFO, WORKING
from .options_panel import LanguageBox
from .output_folder import FileNameRow, OutputFolderRow
from .settings import forget_file_dialog_history
from .theme import Colors, repolish
from .widgets import label

TOOLS = [
    ("merge", "Merge"),
    ("split", "Split"),
    ("edit", "Edit pages"),
    ("compress", "Compress"),
    ("password", "Password"),
    ("ocr", "Make searchable"),
]
THUMB_WIDTH = 110
ROLE_PATH = Qt.ItemDataRole.UserRole
ROLE_PAGE = Qt.ItemDataRole.UserRole + 1  # original page index
ROLE_TURN = Qt.ItemDataRole.UserRole + 2  # extra clockwise rotation


def is_pdf(path: Path) -> bool:
    fmt = formats.detect(path) if path.is_file() else None
    return fmt is not None and fmt.id == "pdf"


def choose_pdfs(parent: QWidget, many: bool) -> list[Path]:
    caption = "Choose PDFs" if many else "Choose a PDF"
    if many:
        paths, _ = QFileDialog.getOpenFileNames(parent, caption, "", "PDF files (*.pdf)")
    else:
        path, _ = QFileDialog.getOpenFileName(parent, caption, "", "PDF files (*.pdf)")
        paths = [path] if path else []
    forget_file_dialog_history()
    return [Path(p) for p in paths]


class Task(QObject):
    """Runs one job in a background thread; reports back through signals."""

    done = Signal(object)  # list[Path]
    failed = Signal(str)
    nothing = Signal(str)  # nothing to do (e.g. the PDF can't get smaller)
    progress = Signal(str)  # a status text while the job runs

    def start(self, job: Callable[[], list[Path]]) -> None:
        def run() -> None:
            try:
                result = job()
            except pdf_tools.NotSmaller as exc:
                self.nothing.emit(str(exc))
            except ConversionError as exc:
                self.failed.emit(str(exc))
            except Exception as exc:  # never let a bad file kill the app
                error_log.write("PDF tool failed", traceback.format_exc())
                self.failed.emit(f"Unexpected error: {exc}")
            else:
                self.done.emit(result)

        threading.Thread(target=run, daemon=True).start()


class ResultBar(QWidget):
    """What happened, with Open / Show in folder once something was saved."""

    def __init__(self) -> None:
        super().__init__()
        self.outputs: list[Path] = []
        self.status = label("", "status")
        self.status.setWordWrap(True)
        self.open_btn = QPushButton("Open")
        self.folder_btn = QPushButton("Show in folder")
        for button in (self.open_btn, self.folder_btn):
            button.setProperty("role", "link")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setVisible(False)
        self.open_btn.clicked.connect(self._open)
        self.folder_btn.clicked.connect(self._folder)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(12)
        row.addWidget(self.status, 1)
        row.addWidget(self.open_btn)
        row.addWidget(self.folder_btn)

    def show_state(self, state: str, text: str, outputs: Iterable[Path] = ()) -> None:
        self.outputs = list(outputs)
        self.status.setText(text)
        self.status.setProperty("state", state)
        repolish(self.status)
        self.open_btn.setVisible(state == DONE and len(self.outputs) == 1)
        self.folder_btn.setVisible(state == DONE and bool(self.outputs))

    def text(self) -> str:
        return self.status.text()

    def _open(self) -> None:
        if self.outputs:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.outputs[0])))

    def _folder(self) -> None:
        if self.outputs:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.outputs[0].parent)))


class PageDelegate(QStyledItemDelegate):
    """Draws the page number under its picture (Qt puts it beside it in a list)."""

    def initStyleOption(self, option, index) -> None:
        super().initStyleOption(option, index)
        option.decorationPosition = option.Position.Top
        option.displayAlignment = Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop


class RemovableDelegate(QStyledItemDelegate):
    """Draws a trash button at the right end of each row; clicking it removes that row."""

    SIZE = 18

    def __init__(self, view: QListWidget, on_remove: Callable[[int], None]) -> None:
        super().__init__(view)
        self.icon = QIcon()
        self._on_remove = on_remove

    def button_rect(self, option_rect: QRect) -> QRect:
        s = self.SIZE
        return QRect(option_rect.right() - s - 8, option_rect.center().y() - s // 2 + 1, s, s)

    def sizeHint(self, option, index) -> QSize:
        hint = super().sizeHint(option, index)
        return QSize(hint.width() + self.SIZE + 16, max(hint.height(), self.SIZE + 10))

    def paint(self, painter, option, index) -> None:
        super().paint(painter, option, index)
        self.icon.paint(painter, self.button_rect(option.rect))

    def editorEvent(self, event, model, option, index) -> bool:
        if (
            event.type() == QEvent.Type.MouseButtonRelease
            and event.button() == Qt.MouseButton.LeftButton
            and self.button_rect(option.rect).contains(event.position().toPoint())
        ):
            self._on_remove(index.row())
            return True
        return super().editorEvent(event, model, option, index)


def _list(view: QListWidget) -> QListWidget:
    view.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
    view.setDefaultDropAction(Qt.DropAction.MoveAction)
    view.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
    return view


def _move_selected(view: QListWidget, step: int) -> None:
    """Move the selected items one place up (-1) or down (+1)."""
    rows = sorted(view.row(i) for i in view.selectedItems())
    if not rows or (step < 0 and rows[0] == 0) or (step > 0 and rows[-1] == view.count() - 1):
        return
    for row in rows if step < 0 else reversed(rows):
        item = view.takeItem(row)
        view.insertItem(row + step, item)
        item.setSelected(True)


def _single_pdf_row(owner: QWidget) -> tuple[QWidget, object, QPushButton]:
    name = label("No PDF chosen yet. Drag one here, or choose it.", "muted")
    button = QPushButton("Choose PDF…")
    row = QFrame()
    row.setProperty("role", "card")
    layout = QHBoxLayout(row)
    layout.setContentsMargins(14, 10, 10, 10)
    layout.addWidget(name, 1)
    layout.addWidget(button)
    return row, name, button


class MergeTool(QWidget):
    changed = Signal()
    problem = Signal(str)  # a file that can't be merged

    def __init__(self) -> None:
        super().__init__()
        self.list = _list(QListWidget())
        self.list.setAccessibleName("PDFs to merge, in order")
        self.list.model().rowsMoved.connect(lambda *_: self.changed.emit())
        self.remover = RemovableDelegate(self.list, self.remove_row)
        self.list.setItemDelegate(self.remover)
        self.list.setToolTip("Drag to change the order. Click the bin to remove a PDF.")
        self.list.installEventFilter(self)  # Delete key removes the selected PDFs
        self.add_btn = QPushButton("Add PDFs…")
        self.add_btn.clicked.connect(lambda: self.add_files(choose_pdfs(self, many=True)))
        self.up_btn = QPushButton("Move up")
        self.up_btn.clicked.connect(lambda: _move_selected(self.list, -1) or self.changed.emit())
        self.down_btn = QPushButton("Move down")
        self.down_btn.clicked.connect(lambda: _move_selected(self.list, 1) or self.changed.emit())
        self.remove_btn = QPushButton("Remove")
        self.remove_btn.clicked.connect(self.remove_selected)
        buttons = QHBoxLayout()
        for button in (self.add_btn, self.up_btn, self.down_btn, self.remove_btn):
            buttons.addWidget(button)
        buttons.addStretch(1)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        layout.addWidget(
            label("Joins PDFs into one, in this order. Drag them to change the order.", "muted")
        )
        layout.addWidget(self.list, 1)
        layout.addLayout(buttons)

    def files(self) -> list[Path]:
        return [Path(self.list.item(i).data(ROLE_PATH)) for i in range(self.list.count())]

    def add_files(self, paths: Iterable[Path]) -> None:
        known = {p.resolve() for p in self.files()}
        for path in paths:
            if not is_pdf(path) or path.resolve() in known:
                continue
            try:
                pages = pdf_tools.page_count(path)
            except ConversionError as exc:
                self.problem.emit(f"{path.name} was not added: {exc}")
                continue
            item = QListWidgetItem(f"{path.name}   ·   {pages} page{'s' if pages != 1 else ''}")
            item.setData(ROLE_PATH, str(path))
            item.setToolTip(str(path))
            self.list.addItem(item)
            known.add(path.resolve())
        self.changed.emit()

    def eventFilter(self, watched, event) -> bool:
        if (
            watched is self.list
            and event.type() == QEvent.Type.KeyPress
            and event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace)
        ):
            self.remove_selected()
            return True
        return super().eventFilter(watched, event)

    def remove_row(self, row: int) -> None:
        self.list.takeItem(row)
        self.changed.emit()

    def apply_colors(self, colors: Colors) -> None:
        self.remover.icon = icons.icon("trash", colors.muted)
        self.list.viewport().update()

    def remove_selected(self) -> None:
        for item in self.list.selectedItems():
            self.list.takeItem(self.list.row(item))
        self.changed.emit()

    def action(self) -> str | None:
        n = len(self.files())
        return f"Merge {n} PDFs" if n >= 2 else None

    def result_name(self) -> str | None:
        return "Merged" if len(self.files()) >= 2 else None

    def job(self, folder: Path | None, name: str):
        sources = self.files()
        target = (folder or sources[0].parent) / f"{name}.pdf"
        return lambda: [pdf_tools.merge(sources, target)]


class SplitTool(QWidget):
    changed = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.source: Path | None = None
        self.pages = 0
        row, self.file_label, self.choose_btn = _single_pdf_row(self)
        self.choose_btn.clicked.connect(lambda: self.add_files(choose_pdfs(self, many=False)))
        self.every_page = QRadioButton("Every page as its own PDF")
        self.by_ranges = QRadioButton("One PDF per page range:")
        self.every_page.setChecked(True)
        self.mode_group = QButtonGroup(self)
        self.mode_group.addButton(self.every_page)
        self.mode_group.addButton(self.by_ranges)
        self.ranges = QLineEdit()
        self.ranges.setPlaceholderText("e.g. 1-3, 5, 8-")
        self.ranges.setAccessibleName("Page ranges")
        self.ranges.setEnabled(False)
        self.by_ranges.toggled.connect(self.ranges.setEnabled)
        for signal in (self.by_ranges.toggled, self.ranges.textChanged):
            signal.connect(lambda *_: self.changed.emit())
        self.hint = label("", "small", wrap=True)
        ranges_row = QHBoxLayout()
        ranges_row.addWidget(self.by_ranges)
        ranges_row.addWidget(self.ranges, 1)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        layout.addWidget(label("Saves parts of a PDF as separate files.", "muted"))
        layout.addWidget(row)
        layout.addWidget(self.every_page)
        layout.addLayout(ranges_row)
        layout.addWidget(self.hint)
        layout.addStretch(1)

    def add_files(self, paths: Iterable[Path]) -> None:
        pdf = next((p for p in paths if is_pdf(p)), None)
        if pdf is None:
            return
        try:
            self.pages = pdf_tools.page_count(pdf)
        except ConversionError as exc:
            self.source, self.pages = None, 0
            self.file_label.setText(str(exc))
        else:
            self.source = pdf
            self.file_label.setText(f"{pdf.name}   ·   {self.pages} pages")
            self.file_label.setProperty("role", "")
            repolish(self.file_label)
        self.changed.emit()

    def groups(self) -> list[list[int]] | None:
        """Page groups to save, None for every page. Raises ConversionError for bad input."""
        if not self.by_ranges.isChecked():
            return None
        return pdf_tools.parse_ranges(self.ranges.text(), self.pages)

    def action(self) -> str | None:
        if self.source is None:
            self.hint.setText("")
            return None
        try:
            groups = self.groups()
        except ConversionError as exc:
            self.hint.setText(str(exc) if self.ranges.text().strip() else "")
            return None
        count = self.pages if groups is None else len(groups)
        self.hint.setText("Each part keeps the pages exactly as they are.")
        return f"Split into {count} PDF{'s' if count != 1 else ''}"

    name_caption = "Folder name"
    name_extension = ""

    def result_name(self) -> str | None:
        return pdf_tools.split_folder(self.source).name if self.source else None

    def job(self, folder: Path | None, name: str):
        src, groups = self.source, self.groups()
        out_dir = (folder or src.parent) / name
        return lambda: pdf_tools.split(src, out_dir, groups)


class EditTool(QWidget):
    changed = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.source: Path | None = None
        self._loader = None
        row, self.file_label, self.choose_btn = _single_pdf_row(self)
        self.choose_btn.clicked.connect(lambda: self.add_files(choose_pdfs(self, many=False)))
        self.pages = _list(QListWidget())
        self.pages.setAccessibleName("Pages, in order")
        self.pages.setViewMode(QListView.ViewMode.ListMode)
        self.pages.setFlow(QListView.Flow.LeftToRight)
        self.pages.setWrapping(True)
        self.pages.setResizeMode(QListView.ResizeMode.Adjust)
        self.pages.setIconSize(QSize(THUMB_WIDTH, int(THUMB_WIDTH * 1.42)))
        self.pages.setGridSize(QSize(THUMB_WIDTH + 34, int(THUMB_WIDTH * 1.42) + 44))
        self.pages.setUniformItemSizes(True)
        self.pages.setItemDelegate(PageDelegate(self.pages))
        self.pages.setProperty("role", "pages")
        self.pages.model().rowsMoved.connect(lambda *_: self.changed.emit())
        self.left_btn = QPushButton("Turn left")
        self.right_btn = QPushButton("Turn right")
        # Pages are shown left to right, so the buttons point the way the page moves.
        self.earlier_btn = QPushButton("◀ Move")
        self.later_btn = QPushButton("Move ▶")
        self.earlier_btn.setToolTip("Move the selected pages one place towards the start")
        self.later_btn.setToolTip("Move the selected pages one place towards the end")
        self.earlier_btn.setAccessibleName("Move pages towards the start")
        self.later_btn.setAccessibleName("Move pages towards the end")
        self.delete_btn = QPushButton("Delete")
        self.reset_btn = QPushButton("Start over")
        self.left_btn.clicked.connect(lambda: self.turn(-90))
        self.right_btn.clicked.connect(lambda: self.turn(90))
        self.earlier_btn.clicked.connect(
            lambda: _move_selected(self.pages, -1) or self.changed.emit()
        )
        self.later_btn.clicked.connect(lambda: _move_selected(self.pages, 1) or self.changed.emit())
        self.delete_btn.clicked.connect(self.delete_selected)
        self.reset_btn.clicked.connect(lambda: self.source and self.add_files([self.source]))
        self.pages.itemSelectionChanged.connect(self._update_buttons)
        tools = QHBoxLayout()
        for button in (self.left_btn, self.right_btn, self.earlier_btn, self.later_btn,
                       self.delete_btn):  # fmt: skip
            tools.addWidget(button)
        tools.addStretch(1)
        tools.addWidget(self.reset_btn)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        layout.addWidget(
            label(
                "Select pages to turn or delete them; drag them to change the order. "
                "The original PDF isn't changed.",
                "muted",
                wrap=True,
            )
        )
        layout.addWidget(row)
        layout.addWidget(self.pages, 1)
        layout.addLayout(tools)
        self._update_buttons()

    def add_files(self, paths: Iterable[Path]) -> None:
        pdf = next((p for p in paths if is_pdf(p)), None)
        if pdf is None:
            return
        self.pages.clear()
        self._loader = None
        try:
            total = pdf_tools.page_count(pdf)
        except ConversionError as exc:
            self.source = None
            self.file_label.setText(str(exc))
            self.changed.emit()
            return
        self.source = pdf
        self.file_label.setText(f"{pdf.name}   ·   {total} pages")
        self.file_label.setProperty("role", "")
        repolish(self.file_label)
        for i in range(total):
            item = QListWidgetItem(f"Page {i + 1}")
            item.setData(ROLE_PAGE, i)
            item.setData(ROLE_TURN, 0)
            item.setTextAlignment(Qt.AlignmentFlag.AlignHCenter)
            self.pages.addItem(item)
        # Draw the small page pictures a few at a time, so the window stays responsive.
        self._loader = pdf_tools.thumbnails(pdf, THUMB_WIDTH)
        QTimer.singleShot(0, self._load_more)
        self.changed.emit()

    def _load_more(self) -> None:
        loader = self._loader
        if loader is None:
            return
        try:
            for _ in range(8):
                index, png = next(loader)
                item = self._item_for_page(index)
                if item is not None:
                    image = QImage.fromData(png, "PNG")
                    item.setData(Qt.ItemDataRole.UserRole + 3, image)
                    self._show_thumbnail(item)
        except (StopIteration, ConversionError):
            self._loader = None
            return
        if self._loader is loader:
            QTimer.singleShot(0, self._load_more)

    def loading(self) -> bool:
        return self._loader is not None

    def _item_for_page(self, index: int) -> QListWidgetItem | None:
        for row in range(self.pages.count()):
            item = self.pages.item(row)
            if item.data(ROLE_PAGE) == index:
                return item
        return None

    def _show_thumbnail(self, item: QListWidgetItem) -> None:
        image = item.data(Qt.ItemDataRole.UserRole + 3)
        if image is None:
            return
        turn = item.data(ROLE_TURN)
        if turn:
            image = image.transformed(QTransform().rotate(turn))
        item.setIcon(QIcon(QPixmap.fromImage(image)))

    def turn(self, degrees: int) -> None:
        for item in self.pages.selectedItems():
            turn = (item.data(ROLE_TURN) + degrees) % 360
            item.setData(ROLE_TURN, turn)
            label_text = f"Page {item.data(ROLE_PAGE) + 1}"
            item.setText(f"{label_text}  ↻{turn}°" if turn else label_text)
            self._show_thumbnail(item)
        self.changed.emit()

    def delete_selected(self) -> None:
        selected = self.pages.selectedItems()
        if len(selected) >= self.pages.count():
            return  # at least one page has to stay
        for item in selected:
            self.pages.takeItem(self.pages.row(item))
        self.changed.emit()

    def edits(self) -> list[pdf_tools.PageEdit]:
        return [
            pdf_tools.PageEdit(
                self.pages.item(r).data(ROLE_PAGE), self.pages.item(r).data(ROLE_TURN)
            )
            for r in range(self.pages.count())
        ]

    def _update_buttons(self) -> None:
        has = bool(self.pages.selectedItems())
        for button in (self.left_btn, self.right_btn, self.earlier_btn, self.later_btn):
            button.setEnabled(has)
        self.delete_btn.setEnabled(has and len(self.pages.selectedItems()) < self.pages.count())

    def action(self) -> str | None:
        if self.source is None or not self.pages.count():
            return None
        changed = self.edits() != [pdf_tools.PageEdit(i) for i in range(self.pages.count())]
        return "Save as new PDF" if changed else None

    def result_name(self) -> str | None:
        return pdf_tools.edited_path(self.source).stem if self.source else None

    def job(self, folder: Path | None, name: str):
        src, edits = self.source, self.edits()
        target = (folder or src.parent) / f"{name}.pdf"
        return lambda: [pdf_tools.edit_pages(src, target, edits)]


SIGNED_WARNING = (
    "⚠ This PDF is digitally signed. The new copy can't keep a valid signature; "
    "keep the original for that."
)


class _SinglePdfTool(QWidget):
    """A tool that works on one PDF: shows its name and size, warns about signatures."""

    changed = Signal()

    def __init__(self, intro: str) -> None:
        super().__init__()
        self.source: Path | None = None
        self.size = 0
        row, self.file_label, self.choose_btn = _single_pdf_row(self)
        self.choose_btn.clicked.connect(lambda: self.add_files(choose_pdfs(self, many=False)))
        self.signed = label(SIGNED_WARNING, "banner", wrap=True)
        self.signed.setVisible(False)
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(0, 0, 0, 0)
        self.body.setSpacing(10)
        self.body.addWidget(label(intro, "muted", wrap=True))
        self.body.addWidget(row)

    def check(self, pdf: Path) -> str | None:
        """Why this PDF can't be used here, or None. Raises ConversionError."""
        return None

    def add_files(self, paths: Iterable[Path]) -> None:
        pdf = next((p for p in paths if is_pdf(p)), None)
        if pdf is None:
            return
        self.source = None
        try:
            problem = self.check(pdf)
            if problem:
                raise ConversionError(problem)
            self.size = pdf.stat().st_size
        except (ConversionError, OSError) as exc:
            if isinstance(exc, OSError):
                exc = ConversionError(f"Could not read {pdf.name}: {exc.strerror or exc}")
            self.file_label.setText(str(exc))
            self.file_label.setProperty("role", "muted")
            self.signed.setVisible(False)
        else:
            self.source = pdf
            self.file_label.setText(f"{pdf.name}   ·   {pdf_tools.size_text(self.size)}")
            self.file_label.setProperty("role", "")
            self.signed.setVisible(pdf_tools.is_signed(pdf))
        repolish(self.file_label)
        self.loaded()
        self.changed.emit()

    def loaded(self) -> None:
        """Called after a new PDF was chosen (or refused)."""


class CompressTool(_SinglePdfTool):
    def __init__(self) -> None:
        super().__init__(
            "Saves a smaller copy. Text, links and form fields stay exactly as they are; "
            "only pictures can get smaller."
        )
        self.levels = QButtonGroup(self)
        self.level_buttons: dict[str, QRadioButton] = {}
        for level in quality.COMPRESS_LEVELS:
            button = QRadioButton(level.label)
            button.setChecked(level is quality.DEFAULT_COMPRESS)
            self.levels.addButton(button)
            self.level_buttons[level.id] = button
            about = label(level.description, "small", wrap=True)
            about.setContentsMargins(26, 0, 0, 4)
            self.body.addWidget(button)
            self.body.addWidget(about)
        self.body.addWidget(self.signed)
        self.body.addStretch(1)
        self.before = 0

    def check(self, pdf: Path) -> str | None:
        if pdf_tools.lock_state(pdf) == pdf_tools.NEEDS_PASSWORD:
            return "This PDF is password-protected. Remove the password first (Password)."
        return None

    def level(self) -> str:
        return next(k for k, b in self.level_buttons.items() if b.isChecked())

    def action(self) -> str | None:
        return "Compress" if self.source else None

    def result_name(self) -> str | None:
        return pdf_tools.compressed_path(self.source).stem if self.source else None

    def job(self, folder: Path | None, name: str):
        src, level, self.before = self.source, self.level(), self.size
        target = (folder or src.parent) / f"{name}.pdf"
        return lambda: [pdf_tools.compress(src, target, level)]

    def done_text(self, outputs: list[Path]) -> str:
        after = outputs[0].stat().st_size
        saved = round(100 * (1 - after / self.before)) if self.before else 0
        size = pdf_tools.size_text
        return f"✓ Saved {outputs[0].name}: {size(self.before)} → {size(after)} ({saved}% smaller)"


FORGET_WARNING = (
    "⚠ Keep the password safe. If you forget it, nobody can open the copy, "
    "not even with this app. Your original stays as it is, without a password."
)


class PasswordTool(_SinglePdfTool):
    submit = Signal()  # Enter pressed in a password field

    def __init__(self) -> None:
        super().__init__(
            "Lock a PDF with a password (AES-256 encryption), or remove the password "
            "from your own PDF. The password is never saved."
        )
        self.state: str | None = None
        self.mode = label("", "", wrap=True)
        self.password = QLineEdit()
        self.repeat = QLineEdit()
        for field, name in ((self.password, "Password"), (self.repeat, "Repeat password")):
            field.setEchoMode(QLineEdit.EchoMode.Password)
            field.setPlaceholderText(name)
            field.setAccessibleName(name)
            field.setMaximumWidth(360)
            field.textChanged.connect(self._update_hint)
            field.returnPressed.connect(self.submit.emit)
        self.show_check = QCheckBox("Show password")
        self.show_check.toggled.connect(self._show)
        self.hint = label("", "small", wrap=True)
        self.forget = label(FORGET_WARNING, "banner", wrap=True)
        for widget in (self.mode, self.password, self.repeat, self.show_check, self.hint):
            self.body.addWidget(widget)
        self.body.addWidget(self.forget)
        self.body.addWidget(self.signed)
        self.body.addStretch(1)
        self.loaded()

    def check(self, pdf: Path) -> str | None:
        self.state = pdf_tools.lock_state(pdf)
        return None

    def adding(self) -> bool:
        return self.state == pdf_tools.UNLOCKED

    def loaded(self) -> None:
        ready = self.source is not None
        self.clear()
        if not ready:
            self.state = None
        texts = {
            pdf_tools.UNLOCKED: "Choose a password for the copy:",
            pdf_tools.NEEDS_PASSWORD: "This PDF is locked. Enter its password to save an "
            "unlocked copy:",
            pdf_tools.RESTRICTED: "This PDF opens without a password, but an owner password "
            "limits printing, copying or changes. Enter the owner password to remove it:",
        }
        self.mode.setText(texts.get(self.state, ""))
        for widget in (self.mode, self.password, self.show_check, self.hint):
            widget.setVisible(ready)
        self.repeat.setVisible(ready and self.adding())
        self.forget.setVisible(ready and self.adding())
        self.signed.setVisible(ready and not self.signed.isHidden())

    def clear(self) -> None:
        """Forget the typed passwords."""
        self.password.clear()
        self.repeat.clear()
        self.show_check.setChecked(False)

    def _show(self, visible: bool) -> None:
        mode = QLineEdit.EchoMode.Normal if visible else QLineEdit.EchoMode.Password
        self.password.setEchoMode(mode)
        self.repeat.setEchoMode(mode)

    def _update_hint(self) -> None:
        self.hint.setText(self._hint())
        self.changed.emit()

    def _hint(self) -> str:
        password = self.password.text()
        if not self.adding() or not password:
            return ""
        problem = pdf_tools.password_problem(password)
        if problem:
            return problem
        warning = pdf_tools.password_warning(password) or ""
        if self.repeat.text() and self.repeat.text() != password:
            return ("The passwords don't match. " + warning).strip()
        return warning

    def action(self) -> str | None:
        if self.source is None:
            return None
        password = self.password.text()
        if not self.adding():
            return "Remove password" if password else None
        if pdf_tools.password_problem(password) or self.repeat.text() != password:
            return None
        return "Add password"

    def idle_text(self) -> str | None:
        if self.source is None:
            return None
        return "Add password" if self.adding() else "Remove password"

    def result_name(self) -> str | None:
        if not self.source:
            return None
        made = pdf_tools.protected_path if self.adding() else pdf_tools.unlocked_path
        return made(self.source).stem

    def job(self, folder: Path | None, name: str):
        src, password, adding = self.source, self.password.text(), self.adding()
        target = (folder or src.parent) / f"{name}.pdf"
        self.clear()
        if adding:
            return lambda: [pdf_tools.add_password(src, target, password)]
        return lambda: [pdf_tools.remove_password(src, target, password)]

    def done_text(self, outputs: list[Path]) -> str:
        name = outputs[0].name
        if pdf_tools.lock_state(outputs[0]) == pdf_tools.UNLOCKED:
            return f"✓ Saved {name} without a password"
        return f"✓ Saved {name}. It now needs the password to open."


class SearchableTool(_SinglePdfTool):
    """Make searchable: recognise the text of scanned pages (OCR)."""

    def __init__(self) -> None:
        super().__init__(
            "Reads the text in scanned pages and adds it invisibly, so you can search, "
            "select and copy it. The pages look exactly the same. Pages that already "
            "have text are left as they are."
        )
        self.report: Callable[[str], None] = lambda text: None
        self.language = LanguageBox()
        self.body.addWidget(label("Language of the text", "caption"))
        self.body.addWidget(self.language, 0, Qt.AlignmentFlag.AlignLeft)
        self.body.addWidget(self.signed)
        if not ocr.is_available():
            self.body.addWidget(label(f"⚠ {OCR_MISSING}", "banner", wrap=True))
        self.body.addStretch(1)

    def check(self, pdf: Path) -> str | None:
        if pdf_tools.lock_state(pdf) == pdf_tools.NEEDS_PASSWORD:
            return "This PDF is password-protected. Remove the password first (Password)."
        if not ocr.needs_ocr(pdf):
            return f"{pdf.name} already has selectable text, so there is nothing to recognise."
        return None

    def action(self) -> str | None:
        return "Make searchable" if self.source and ocr.is_available() else None

    def result_name(self) -> str | None:
        return ocr.searchable_path(self.source).stem if self.source else None

    def job(self, folder: Path | None, name: str):
        src, language, report = self.source, self.language.language(), self.report
        target = (folder or src.parent) / f"{name}.pdf"

        def progress(_fraction: float, message: str) -> None:
            report(f"{message}…")

        return lambda: [ocr.make_searchable(src, target, language, progress=progress)]


OCR_MISSING = "Text recognition is missing its language files. Reinstall Azoth Converter to use it."


class PdfToolsPage(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.task = Task()
        self.task.done.connect(self._done)
        self.task.failed.connect(self._failed)
        self.task.nothing.connect(self._nothing)
        self.busy = False

        self.merge = MergeTool()
        self.split = SplitTool()
        self.edit = EditTool()
        self.compress = CompressTool()
        self.password = PasswordTool()
        self.password.submit.connect(self.run)
        self.searchable = SearchableTool()
        self.searchable.report = self.task.progress.emit
        self.task.progress.connect(lambda text: self.result.show_state(WORKING, text))
        self.tools = {
            "merge": self.merge,
            "split": self.split,
            "edit": self.edit,
            "compress": self.compress,
            "password": self.password,
            "ocr": self.searchable,
        }
        self.stack = QStackedWidget()
        for tool in self.tools.values():
            self.stack.addWidget(tool)
            tool.changed.connect(self._update)
        self.merge.problem.connect(lambda message: self.result.show_state(FAILED, f"✗ {message}"))

        self.tool_buttons: dict[str, QPushButton] = {}
        self.tool_group = QButtonGroup(self)
        switcher = QHBoxLayout()
        switcher.setSpacing(8)
        for key, text in TOOLS:
            button = QPushButton(text)
            button.setProperty("role", "filter")
            button.setCheckable(True)
            button.clicked.connect(lambda _=False, k=key: self.show_tool(k))
            self.tool_group.addButton(button)
            self.tool_buttons[key] = button
            switcher.addWidget(button)
        switcher.addStretch(1)
        self.tool_buttons["merge"].setChecked(True)

        self.output_row = OutputFolderRow()
        self.name_row = FileNameRow()
        self.result = ResultBar()
        self.action_btn = QPushButton("Merge")
        self.action_btn.setProperty("role", "primary")
        self.action_btn.setMinimumWidth(240)
        self.action_btn.clicked.connect(self.run)
        bottom = QHBoxLayout()
        bottom.setSpacing(16)
        bottom.addWidget(self.output_row, 1)
        bottom.addWidget(self.name_row, 1)
        bottom.addWidget(self.action_btn, 0, Qt.AlignmentFlag.AlignBottom)

        titles = QVBoxLayout()
        titles.setSpacing(2)
        titles.addWidget(label("PDF tools", "h1"))
        titles.addWidget(
            label(
                "Merge, split, edit, compress, lock and make PDFs searchable. Only Compress "
                "changes pictures; everything else copies pages as they are.",
                "muted",
                wrap=True,
            )
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 20)
        layout.setSpacing(14)
        layout.addLayout(titles)
        layout.addLayout(switcher)
        layout.addWidget(self.stack, 1)
        layout.addWidget(self.result)
        layout.addLayout(bottom)
        self._update()

    def current_tool(self) -> str:
        return next(k for k, b in self.tool_buttons.items() if b.isChecked())

    def show_tool(self, key: str) -> None:
        self.tool_buttons[key].setChecked(True)
        self.stack.setCurrentWidget(self.tools[key])
        self.result.show_state(INFO, "")
        self._update()

    def add_files(self, paths: Iterable[Path | str]) -> None:
        """Files dropped on the window go to the tool that is open."""
        if not self.busy:
            self.tools[self.current_tool()].add_files([Path(p) for p in paths])

    def _update(self) -> None:
        tool = self.tools[self.current_tool()]
        self.name_row.set_name(
            tool.result_name(),
            getattr(tool, "name_extension", "pdf"),
            getattr(tool, "name_caption", "File name"),
        )
        text = tool.action()
        idle = getattr(tool, "idle_text", lambda: None)()
        self.action_btn.setText(text or idle or dict(TOOLS)[self.current_tool()])
        self.action_btn.setEnabled(bool(text) and not self.busy)

    def run(self) -> None:
        tool = self.tools[self.current_tool()]
        if self.busy or not tool.action():
            return
        try:
            name = self.name_row.name(getattr(tool, "name_extension", "pdf"))
            job = tool.job(self.output_row.folder, name)
        except ConversionError as exc:
            self.result.show_state(FAILED, f"✗ {exc}")
            return
        self._set_busy(True)
        self.result.show_state(WORKING, "Working…")
        self.task.start(job)

    def apply_colors(self, colors: Colors) -> None:
        self.merge.apply_colors(colors)

    def _set_busy(self, busy: bool) -> None:
        self.busy = busy
        for button in self.tool_buttons.values():
            button.setEnabled(not busy)
        for tool in self.tools.values():
            tool.setEnabled(not busy)
        self.output_row.set_busy(busy)
        self.name_row.set_busy(busy)
        self._update()

    def _done(self, outputs: list[Path]) -> None:
        self._set_busy(False)
        tool = self.tools[self.current_tool()]
        if hasattr(tool, "done_text"):
            text = tool.done_text(outputs)
        elif len(outputs) == 1:
            text = f"✓ Saved {outputs[0].name}"
        else:
            text = f"✓ Saved {len(outputs)} PDFs in {outputs[0].parent.name}"
        self.result.show_state(DONE, text, outputs)

    def _nothing(self, message: str) -> None:
        self._set_busy(False)
        self.result.show_state(INFO, message)

    def _failed(self, message: str) -> None:
        self._set_busy(False)
        self.result.show_state(FAILED, f"✗ {message}")
