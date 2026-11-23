"""What the user sees when a conversion has finished.

* ``DoneCard``: a card on the Convert page ("Done! 4 files converted") with **Open file**
  (one result) and **Open folder** (all results in one folder); it fades in.
* ``Notifier``: a Windows notification when the conversion finishes while the app is in the
  background (can be turned off in Settings). Shown by Windows itself; nothing is sent
  anywhere.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QEasingCurve, QObject, QPropertyAnimation, Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from . import icons
from .theme import Colors
from .widgets import label


def _files(n: int) -> str:
    return f"{n} file{'s' if n != 1 else ''}"


def done_message(
    converted: int,
    failed: int,
    cancelled: bool,
    cleaning: bool = False,
    resizing: bool = False,
    enhancing: bool = False,
) -> str:
    """One short sentence about the finished run."""
    if cancelled:
        return f"Cancelled after {_files(converted)}." if converted else "Cancelled."
    if failed:
        if not converted:
            return f"Nothing was saved: {_files(failed)} failed. The reason is shown on each file."
        return f"{converted} done, {failed} failed. The reason is shown on each file."
    if cleaning:
        return f"Done! Metadata removed from {_files(converted)}."
    if enhancing:
        return f"Done! {_files(converted)} enhanced."
    if resizing:
        return f"Done! {_files(converted)} resized."
    return f"Done! {_files(converted)} converted."


class DoneCard(QFrame):
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("DoneCard")
        self.file: Path | None = None
        self.folder: Path | None = None
        self._ok = True
        self._colors: Colors | None = None
        self.icon = QLabel()
        self.icon.setFixedSize(22, 22)
        self.message = label("", wrap=True)
        self.message.setObjectName("DoneText")
        self.file_btn = QPushButton("Open file")
        self.folder_btn = QPushButton("Open folder")
        self.file_btn.clicked.connect(lambda: self._open(self.file))
        self.folder_btn.clicked.connect(lambda: self._open(self.folder))
        top = QHBoxLayout()
        top.setSpacing(10)
        top.addWidget(self.icon, 0, Qt.AlignmentFlag.AlignTop)
        top.addWidget(self.message, 1)
        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        buttons.addWidget(self.file_btn)
        buttons.addWidget(self.folder_btn)
        buttons.addStretch(1)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(10)
        layout.addLayout(top)
        layout.addLayout(buttons)
        self._animation: QPropertyAnimation | None = None
        self.setVisible(False)

    def show_result(
        self, text: str, *, ok: bool, file: Path | None = None, folder: Path | None = None
    ) -> None:
        self.file, self.folder, self._ok = file, folder, ok
        self.message.setText(text)
        self.file_btn.setVisible(file is not None)
        self.folder_btn.setVisible(folder is not None)
        self._paint_icon()
        self.setVisible(True)
        self._fade_in()

    def clear(self) -> None:
        self._stop_fade()
        self.setVisible(False)
        self.file = self.folder = None

    def _fade_in(self) -> None:
        """A short fade-in. The effect is removed afterwards, so the card is drawn normally."""
        self._stop_fade()
        fade = QGraphicsOpacityEffect(self)
        fade.setOpacity(0.0)
        self.setGraphicsEffect(fade)
        self._animation = QPropertyAnimation(fade, b"opacity", self)
        self._animation.setDuration(220)
        self._animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._animation.setStartValue(0.0)
        self._animation.setEndValue(1.0)
        self._animation.finished.connect(self._stop_fade)
        self._animation.start()

    def _stop_fade(self) -> None:
        if self._animation is not None:
            self._animation.stop()
            self._animation = None
        self.setGraphicsEffect(None)  # deletes the effect

    def text(self) -> str:
        return self.message.text() if self.isVisibleTo(self.parentWidget() or self) else ""

    def apply_colors(self, colors: Colors) -> None:
        self._colors = colors
        self._paint_icon()

    def _paint_icon(self) -> None:
        if self._colors is not None:
            name, color = (
                ("check", self._colors.success) if self._ok else ("info", self._colors.error)
            )
            self.icon.setPixmap(icons.pixmap(name, color, 22))

    @staticmethod
    def _open(path: Path | None) -> None:
        if path is not None:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))


class Notifier(QObject):
    """Windows notification for work that finished while the window was in the background."""

    def __init__(self, window: QWidget) -> None:
        super().__init__(window)
        self.window = window
        self.enabled = True
        self.tray: QSystemTrayIcon | None = None

    def notify(self, text: str) -> bool:
        """Show ``text`` if the window is in the background. True if it was shown."""
        if not self.enabled or self.window.isActiveWindow():
            return False
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return False
        if self.tray is None:
            self.tray = QSystemTrayIcon(self.window.windowIcon(), self)
            self.tray.setToolTip("Azoth Converter")
            self.tray.messageClicked.connect(self._bring_to_front)
        # Windows shows notifications only for an icon in the notification area, so it is
        # shown just for the time of the message.
        self.tray.show()
        self.tray.showMessage("Azoth Converter", text, self.window.windowIcon(), 8000)
        QTimer.singleShot(15000, self.tray.hide)
        return True

    def _bring_to_front(self) -> None:
        self.window.showNormal()
        self.window.raise_()
        self.window.activateWindow()
