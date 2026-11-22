"""Quality choice (Maximum / High / Smaller) and text recognition (OCR) choices, shown
next to "Convert to"."""

from __future__ import annotations

from PySide6.QtCore import QLocale, Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .. import ocr, quality
from .settings import Preferences
from .widgets import label

SHORT_LABELS = {"maximum": "Maximum", "high": "High", "compact": "Smaller"}


class QualitySelector(QWidget):
    level_changed = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.buttons: dict[str, QPushButton] = {}
        self.group = QButtonGroup(self)
        frame = QFrame()
        frame.setObjectName("Segmented")
        row = QHBoxLayout(frame)
        row.setContentsMargins(3, 3, 3, 3)
        row.setSpacing(2)
        for level in quality.LEVELS:
            button = QPushButton(SHORT_LABELS.get(level.id, level.label))
            button.setProperty("role", "segment")
            button.setCheckable(True)
            button.setFocusPolicy(Qt.FocusPolicy.TabFocus)
            button.setToolTip(level.label)
            button.setAccessibleName(f"Quality: {level.label}")
            button.toggled.connect(lambda on, lv=level.id: on and self._changed(lv))
            self.group.addButton(button)
            self.buttons[level.id] = button
            row.addWidget(button, 1)
        self.hint = label("", "small", wrap=True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addWidget(label("Quality", "caption"))
        layout.addWidget(frame)
        layout.addWidget(self.hint)
        self.buttons[quality.DEFAULT.id].setChecked(True)
        self._update_hint()

    def level(self) -> str:
        return next(k for k, b in self.buttons.items() if b.isChecked())

    def set_level(self, level_id: str | None) -> None:
        if level_id in self.buttons:
            self.buttons[level_id].setChecked(True)

    def set_busy(self, busy: bool) -> None:
        for button in self.buttons.values():
            button.setEnabled(not busy)

    def _changed(self, level_id: str) -> None:
        self._update_hint()
        self.level_changed.emit(level_id)

    def _update_hint(self) -> None:
        level = quality.BY_ID[self.level()]
        self.hint.setText(
            f"{level.description} Only affects photos and PDF pages saved as pictures; "
            "documents → PDF always keep full quality."
        )
        self.hint.setToolTip(
            f"Details: photo quality {level.image_quality} of 100 (JPG, WebP, HEIC, AVIF) · "
            f"PDF pages as pictures at {level.dpi} DPI (dots per inch, higher is sharper)."
        )


class LanguageBox(QComboBox):
    """Language of the text to recognise. Remembers the last choice; the first time it
    follows the computer's language."""

    def __init__(self, prefs: Preferences | None = None) -> None:
        super().__init__()
        self.prefs = prefs or Preferences()
        self.setAccessibleName("Language of the text")
        for code in ocr.available_languages():
            self.addItem(ocr.LANGUAGES[code], code)
        saved = self.prefs.ocr_language
        wanted = saved or ocr.default_language(QLocale.system().name())
        self.set_language(wanted)
        self.currentIndexChanged.connect(lambda _i: self.prefs.save_ocr(language=self.language()))

    def language(self) -> str:
        return self.currentData() or ocr.default_language()

    def set_language(self, code: str) -> None:
        index = self.findData(code)
        if index >= 0:
            self.setCurrentIndex(index)


class OcrOptions(QWidget):
    """ "Text recognition" on the Convert page: shown when a scan or photo becomes text,
    Word or (optional) a searchable PDF."""

    def __init__(self, prefs: Preferences | None = None) -> None:
        super().__init__()
        prefs = prefs or Preferences()
        self.prefs = prefs
        self.searchable = QCheckBox("Make the text searchable (OCR)")
        self.searchable.setToolTip(
            "Reads the text in the pictures and adds it invisibly, so you can search and "
            "copy it. The pictures stay exactly the same. Takes a few seconds per page."
        )
        self.searchable.setChecked(prefs.ocr_searchable)
        self.searchable.toggled.connect(self._toggled)
        self.language = LanguageBox(prefs)
        self.language_label = label("Language of the text (for scans and photos)", "small")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addWidget(label("Text recognition", "caption"))
        layout.addWidget(self.searchable)
        layout.addWidget(self.language_label)
        layout.addWidget(self.language)
        self.mode: str | None = None

    def set_mode(self, mode: str | None) -> None:
        """None: hidden; "optional": the checkbox decides; "always": the text is read."""
        self.mode = mode
        self.setVisible(mode is not None and ocr.is_available())
        self.searchable.setVisible(mode == "optional")
        self._update()

    def options(self) -> dict:
        return {
            "ocr": self.mode == "always" or self.searchable.isChecked(),
            "ocr_language": self.language.language(),
        }

    def set_busy(self, busy: bool) -> None:
        self.searchable.setEnabled(not busy)
        self.language.setEnabled(not busy)

    def _toggled(self, on: bool) -> None:
        self.prefs.save_ocr(searchable=on)
        self._update()

    def _update(self) -> None:
        used = self.mode == "always" or self.searchable.isChecked()
        self.language.setVisible(used)
        self.language_label.setVisible(used)
