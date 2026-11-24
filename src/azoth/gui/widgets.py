"""Small reusable widgets and helpers."""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QSize, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QPainter
from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QLayout,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
    QWidgetItem,
)


def label(text: str = "", role: str | None = None, *, wrap: bool = False) -> QLabel:
    """A label styled by the theme: role "h1", "h2", "muted", "small", "caption", "note" …"""
    widget = QLabel(text)
    if role:
        widget.setProperty("role", role)
    widget.setWordWrap(wrap)
    return widget


class ElidedLabel(QLabel):
    """A one-line label that shortens its text with "…" when there isn't room (long
    folder names), instead of cutting letters off. The full text is in ``text()``."""

    def __init__(self, text: str = "") -> None:
        super().__init__(text)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setMinimumWidth(60)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setPen(self.palette().color(self.foregroundRole()))
        shown = self.fontMetrics().elidedText(
            self.text(), Qt.TextElideMode.ElideMiddle, self.width()
        )
        align = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        painter.drawText(self.rect(), align, shown)


def download_button(text: str, url: str) -> QPushButton:
    """A button that opens an official download page in the browser. The app itself never
    goes online: only the browser does, and only when the button is clicked."""
    button = QPushButton(text)
    button.setToolTip(f"{url}\nOpens in your browser. After installing, restart Azoth Converter.")
    button.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(url)))
    return button


def discard(widget: QWidget) -> None:
    """Remove ``widget`` from the window and delete it. Hidden first and never given
    ``setParent(None)``: a visible widget without a parent is a window of its own, so it
    would flash up on Windows (a small empty window) before it's deleted."""
    widget.hide()
    widget.deleteLater()


def scrollable(content: QWidget) -> QScrollArea:
    """Wrap a page (or panel) so it scrolls when the window is too small, instead of Qt
    squeezing its parts on top of each other. Use it for every page whose content can grow."""
    layout = content.layout()
    if layout is not None:
        # The content never gets smaller than it needs; the scroll area scrolls instead.
        layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    scroll.setWidget(content)
    return scroll


class Collapsible(QWidget):
    """A section that opens and closes with a click on its title ("▸ More options"),
    so choices most people never change don't crowd the page. When closed, a short
    summary line under the title says what's chosen."""

    toggled = Signal(bool)

    def __init__(self, title: str, content: QWidget) -> None:
        super().__init__()
        self.title = title
        self.content = content
        self.header = QPushButton()
        self.header.setProperty("role", "section")
        self.header.setCursor(Qt.CursorShape.PointingHandCursor)
        self.header.clicked.connect(lambda: self.set_open(not self.is_open(), user=True))
        self.summary = label("", "small")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addWidget(self.header)
        layout.addWidget(self.summary)
        layout.addWidget(content)
        self._open = True
        self.set_open(False)

    def is_open(self) -> bool:
        return self._open

    def set_open(self, open_: bool, *, user: bool = False) -> None:
        self._open = open_
        self.header.setText(f"{'▾' if open_ else '▸'}  {self.title}")
        self.header.setAccessibleName(f"{self.title} ({'open' if open_ else 'closed'})")
        self.content.setVisible(open_)
        self.summary.setVisible(not open_ and bool(self.summary.text()))
        if user:
            self.toggled.emit(open_)

    def set_summary(self, text: str) -> None:
        self.summary.setText(text)
        self.summary.setToolTip(text)
        self.summary.setVisible(not self._open and bool(text))


def divider() -> QFrame:
    line = QFrame()
    line.setObjectName("Divider")
    line.setFrameShape(QFrame.Shape.NoFrame)
    return line


class FlowLayout(QLayout):
    """Lays out widgets left to right and wraps onto the next line, like words in text."""

    def __init__(self, parent: QWidget | None = None, spacing: int = 6) -> None:
        super().__init__(parent)
        self._items: list[QWidgetItem] = []
        self._spacing = spacing
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item) -> None:
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int):
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index: int):
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._arrange(QRect(0, 0, width, 0), move=False)

    def setGeometry(self, rect: QRect) -> None:
        super().setGeometry(rect)
        self._arrange(rect, move=True)

    def sizeHint(self) -> QSize:
        return self.minimumSize()

    def minimumSize(self) -> QSize:
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        return size

    def _arrange(self, rect: QRect, *, move: bool) -> int:
        x, y, line_height = rect.x(), rect.y(), 0
        for item in self._items:
            if item.widget() is not None and item.widget().isHidden():
                continue
            hint = item.sizeHint()
            if x + hint.width() > rect.right() + 1 and line_height > 0:
                x = rect.x()
                y += line_height + self._spacing
                line_height = 0
            if move:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x += hint.width() + self._spacing
            line_height = max(line_height, hint.height())
        return y + line_height - rect.y()


def flow_container() -> tuple[QWidget, FlowLayout]:
    widget = QWidget()
    layout = FlowLayout(widget)
    policy = QSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
    policy.setHeightForWidth(True)
    widget.setSizePolicy(policy)
    return widget, layout
