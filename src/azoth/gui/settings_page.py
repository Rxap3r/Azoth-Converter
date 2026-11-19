"""The Settings page: look (light / dark / follow Windows), conversion settings, About."""

from __future__ import annotations

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from .. import __version__
from . import theme
from .widgets import label

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
            "Keep photo metadata when converting (camera, date, GPS location)"
        )
        self.metadata_check.setToolTip(METADATA_DETAILS)  # shown on hover
        self.word_check = QCheckBox("Use Microsoft Word for Word → PDF (exact layout and fonts)")
        self.word_check.setToolTip(
            "Word converts the file on this computer; nothing is uploaded.\n"
            "Macros stay off. If Word fails, LibreOffice is used instead."
        )
        self.word_check.setChecked(use_word)
        self.word_check.setVisible(word_installed)  # only when Word is installed
        self.word_check.toggled.connect(self.use_word_changed)
        conversion = [
            label("Converting", "h2"),
            self.metadata_check,
            self.word_check,
        ]

        self.about_btn = QPushButton("About Azoth Converter…")
        self.about_btn.clicked.connect(self.about_requested)
        self.updates_btn = QPushButton("Check for updates…")
        self.updates_btn.setToolTip(RELEASES_URL)
        self.updates_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(RELEASES_URL)))
        buttons = QWidget()
        row = QHBoxLayout(buttons)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self.updates_btn)
        row.addWidget(self.about_btn)
        row.addStretch(1)
        about = [
            label("About", "h2"),
            label(
                f"Version {__version__}. Works offline: your files never leave this computer.",
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

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 20)
        layout.setSpacing(14)
        layout.addWidget(label("Settings", "h1"))
        for group in (appearance, conversion, about):
            card = _card(*group)
            card.setMaximumWidth(640)
            layout.addWidget(card, 0, Qt.AlignmentFlag.AlignLeft)
            card.setMinimumWidth(520)
        self.about_btn.setMaximumWidth(260)
        layout.addStretch(1)

    def theme_choice(self) -> str:
        return next(k for k, b in self.theme_buttons.items() if b.isChecked())

    def set_theme_choice(self, choice: str) -> None:
        if choice in self.theme_buttons:
            self.theme_buttons[choice].setChecked(True)

    def use_word(self, saved: bool) -> bool:
        """The Word setting to save (the saved one if Word isn't installed here)."""
        return self.word_check.isChecked() if self.word_installed else saved
