"""The "PDF tools" page: Merge, Split and Edit pages (rotate, delete, reorder).

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

from .. import formats, pdf_tools
from ..converters import ConversionError
from . import error_log, icons
from .file_list import DONE, FAILED, INFO, WORKING
from .output_folder import OutputFolderRow
from .settings import forget_file_dialog_history
from .theme import Colors, repolish
from .widgets import label

TOOLS = [("merge", "Merge"), ("split", "Split"), ("edit", "Edit pages")]
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

    def start(self, job: Callable[[], list[Path]]) -> None:
        def run() -> None:
            try:
                result = job()
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
        self.name = QLineEdit("Merged.pdf")
        self.name.setAccessibleName("Name of the merged PDF")
        self.name.textChanged.connect(lambda _: self.changed.emit())
        buttons = QHBoxLayout()
        for button in (self.add_btn, self.up_btn, self.down_btn, self.remove_btn):
            buttons.addWidget(button)
        buttons.addStretch(1)
        name_row = QHBoxLayout()
        name_row.addWidget(label("Name of the new PDF", "caption"))
        name_row.addWidget(self.name, 1)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        layout.addWidget(
            label("Joins PDFs into one, in this order. Drag them to change the order.", "muted")
        )
        layout.addWidget(self.list, 1)
        layout.addLayout(buttons)
        layout.addLayout(name_row)

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

    def target_name(self) -> str:
        name = self.name.text().strip() or "Merged"
        name = "".join("_" if c in '<>:"/\\|?*' else c for c in name)
        return name if name.lower().endswith(".pdf") else f"{name}.pdf"

    def action(self) -> str | None:
        n = len(self.files())
        return f"Merge {n} PDFs" if n >= 2 else None

    def job(self, folder: Path | None):
        sources = self.files()
        target = (folder or sources[0].parent) / self.target_name()
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

    def job(self, folder: Path | None):
        src, groups = self.source, self.groups()
        out_dir = pdf_tools.split_folder(src, folder)
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
        self.earlier_btn = QPushButton("Move earlier")
        self.later_btn = QPushButton("Move later")
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

    def job(self, folder: Path | None):
        src, edits = self.source, self.edits()
        target = pdf_tools.edited_path(src, folder)
        return lambda: [pdf_tools.edit_pages(src, target, edits)]


class PdfToolsPage(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.task = Task()
        self.task.done.connect(self._done)
        self.task.failed.connect(self._failed)
        self.busy = False

        self.merge = MergeTool()
        self.split = SplitTool()
        self.edit = EditTool()
        self.tools = {"merge": self.merge, "split": self.split, "edit": self.edit}
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
        self.result = ResultBar()
        self.action_btn = QPushButton("Merge")
        self.action_btn.setProperty("role", "primary")
        self.action_btn.setMinimumWidth(240)
        self.action_btn.clicked.connect(self.run)
        bottom = QHBoxLayout()
        bottom.setSpacing(16)
        bottom.addWidget(self.output_row, 1)
        bottom.addWidget(self.action_btn, 0, Qt.AlignmentFlag.AlignBottom)

        titles = QVBoxLayout()
        titles.setSpacing(2)
        titles.addWidget(label("PDF tools", "h1"))
        titles.addWidget(
            label(
                "Merge, split and edit PDFs. Pages are copied as they are: no quality loss.",
                "muted",
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
        text = tool.action()
        self.action_btn.setText(text or dict(TOOLS)[self.current_tool()])
        self.action_btn.setEnabled(bool(text) and not self.busy)

    def run(self) -> None:
        tool = self.tools[self.current_tool()]
        if self.busy or not tool.action():
            return
        try:
            job = tool.job(self.output_row.folder)
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
        self._update()

    def _done(self, outputs: list[Path]) -> None:
        self._set_busy(False)
        if len(outputs) == 1:
            text = f"✓ Saved {outputs[0].name}"
        else:
            text = f"✓ Saved {len(outputs)} PDFs in {outputs[0].parent.name}"
        self.result.show_state(DONE, text, outputs)

    def _failed(self, message: str) -> None:
        self._set_busy(False)
        self.result.show_state(FAILED, f"✗ {message}")
