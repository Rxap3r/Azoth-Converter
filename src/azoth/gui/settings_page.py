"""The Settings page: look, conversion settings, About, and Uninstall (installed app only)."""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QProcess, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from .. import __version__, portable
from . import error_log, theme
from .widgets import label, scrollable

METADATA_DETAILS = (
    "When this is off (recommended), converted photos no longer contain:\n"
    "  •  where the photo was taken (GPS location)\n"
    "  •  date and time it was taken\n"
    "  •  camera or phone make, model, serial number and settings\n"
    "  •  hidden preview pictures (they can show parts you cropped out)\n"
    "  •  author, captions, keywords, comments and editing history (XMP, IPTC)\n"
    "Kept: the picture itself, its colours (colour profile) and the right way up.\n"
    "When it's on, the camera details, date and GPS location are copied over."
)


def uninstaller() -> Path | None:
    """The installer's uninstall program next to the app, or None (portable or run from source)."""
    if not getattr(sys, "frozen", False):
        return None
    found = sorted(Path(sys.executable).parent.glob("unins[0-9][0-9][0-9].exe"))
    return found[-1] if found else None


RELEASES_URL = "https://github.com/Rxap3r/Azoth-Converter/releases"


def _card(*widgets: QWidget) -> QFrame:
    card = QFrame()
    card.setProperty("role", "card")
    layout = QVBoxLayout(card)
    layout.setContentsMargins(18, 14, 18, 16)
    layout.setSpacing(6)
    for widget in widgets:
        layout.addWidget(widget)
    return card


class SettingsPage(QWidget):
    theme_changed = Signal(str)
    use_word_changed = Signal(bool)
    about_requested = Signal()

    def __init__(self, *, word_installed: bool, use_word: bool, theme_choice: str) -> None:
        super().__init__()
        self.word_installed = word_installed

        self.theme_group = QButtonGroup(self)
        self.theme_buttons: dict[str, QRadioButton] = {}
        appearance = [label("Appearance", "h2"), label("How the app looks.", "small")]
        for key, text in theme.CHOICES:
            button = QRadioButton(text)
            button.setChecked(key == theme_choice)
            button.toggled.connect(lambda on, k=key: on and self.theme_changed.emit(k))
            self.theme_group.addButton(button)
            self.theme_buttons[key] = button
            appearance.append(button)

        self.metadata_check = QCheckBox(
            "Keep photo and video metadata when converting (camera, date, GPS location)"
        )
        self.metadata_check.setToolTip(METADATA_DETAILS)  # shown on hover
        self.word_check = QCheckBox(
            "Use Microsoft Office (Word, Excel, PowerPoint) where installed: exact layout and fonts"
        )
        self.word_check.setToolTip(
            "Office converts the file on this computer; nothing is uploaded.\n"
            "Macros stay off. If Office fails, LibreOffice is used instead (when installed)."
        )
        self.word_check.setChecked(use_word)
        self.word_check.setVisible(word_installed)  # only when Word is installed
        self.word_check.toggled.connect(self.use_word_changed)
        self.notify_check = QCheckBox(
            "Show a Windows notification when work finishes while the app is in the background"
        )
        self.notify_check.setChecked(True)
        self.turn_check = QCheckBox(
            "Text recognition: turn sideways or upside-down pages the right way up"
        )
        self.turn_check.setToolTip(
            "Only the page's direction changes; the picture itself stays exactly the same."
        )
        self.turn_check.setChecked(True)
        conversion = [
            label("Converting", "h2"),
            self.metadata_check,
            self.word_check,
            self.turn_check,
            self.notify_check,
        ]

        self.about_btn = QPushButton("About Azoth Converter…")
        self.about_btn.clicked.connect(self.about_requested)
        self.updates_btn = QPushButton("Check for updates…")
        self.updates_btn.setToolTip(RELEASES_URL)
        self.updates_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(RELEASES_URL)))
        self.log_btn = QPushButton("Error log…")
        self.log_btn.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(error_log.log_path())))
        )
        buttons = QWidget()
        row = QHBoxLayout(buttons)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self.updates_btn)
        row.addWidget(self.about_btn)
        row.addWidget(self.log_btn)
        row.addStretch(1)
        data = portable.data_dir()
        where = (
            f" Portable version: settings and the error log are kept next to the program "
            f"in {data}, nothing is saved on this computer."
            if data is not None
            else ""
        )
        about = [
            label("About", "h2"),
            label(
                f"Version {__version__}. Works offline: your files never leave this "
                f"computer.{where}",
                "small",
                wrap=True,
            ),
            buttons,
            label(
                "“Check for updates” opens the download page in your browser, where you can "
                "compare the newest version with yours. The app itself never goes online.",
                "small",
                wrap=True,
            ),
        ]

        self.uninstall_btn = QPushButton("Uninstall Azoth Converter…")
        self.uninstall_btn.clicked.connect(self.uninstall)
        uninstall = [
            label("Uninstall", "h2"),
            label(
                "Removes the app and everything it saved on this computer (settings, error log). "
                "Your own files and converted files are not touched.",
                "small",
                wrap=True,
            ),
            self.uninstall_btn,
        ]
        groups = [appearance, conversion, about]
        if uninstaller() is not None and data is None:  # installed app only: not portable
            groups.append(uninstall)

        content = QWidget()
        layout = QVBoxLayout(content)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scrollable(content))  # scrolls instead of squeezing when too small
        layout.setContentsMargins(28, 24, 28, 20)
        layout.setSpacing(14)
        layout.addWidget(label("Settings", "h1"))
        for group in groups:
            card = _card(*group)
            card.setMaximumWidth(640)
            card.setMinimumWidth(520)
            # A row with a stretch instead of AlignLeft: with AlignLeft, Qt doesn't give
            # wrapped text the height it needs, and it gets drawn over the buttons.
            row = QHBoxLayout()
            row.addWidget(card, 1)
            row.addStretch(0)
            layout.addLayout(row)
        self.about_btn.setMaximumWidth(260)
        self.uninstall_btn.setMaximumWidth(260)
        layout.addStretch(1)

    def uninstall(self) -> None:
        program = uninstaller()
        if program is None:
            return
        answer = QMessageBox.question(
            self,
            "Uninstall Azoth Converter",
            "Remove Azoth Converter and its settings from this computer?\n\n"
            "Your own files and converted files are not touched. The app closes now.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        if QProcess.startDetached(str(program), []):
            QApplication.quit()  # the uninstaller can't remove files of a running app
        else:
            QMessageBox.warning(
                self,
                "Uninstall Azoth Converter",
                "The uninstaller could not be started. Use Windows Settings → Apps instead.",
            )

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.update_log_button()

    def update_log_button(self) -> None:
        exists = error_log.log_path().is_file()
        self.log_btn.setEnabled(exists)
        self.log_btn.setToolTip(
            "Details of errors, saved on this computer only. Attach it when reporting a problem."
            if exists
            else "No errors so far."
        )

    def theme_choice(self) -> str:
        return next(k for k, b in self.theme_buttons.items() if b.isChecked())

    def set_theme_choice(self, choice: str) -> None:
        if choice in self.theme_buttons:
            self.theme_buttons[choice].setChecked(True)

    def use_word(self, saved: bool) -> bool:
        """The Word setting to save (the saved one if Word isn't installed here)."""
        return self.word_check.isChecked() if self.word_installed else saved
