"""Quality choice (Maximum / High / Smaller), picture size and text recognition (OCR)
choices, shown next to "Convert to"."""

from __future__ import annotations

from PySide6.QtCore import QLocale, Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .. import ocr, quality, resize
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


class ResizeOptions(QWidget):
    """ "Picture size" on the Convert page: keep the size (default), or choose a new one.
    Shown when pictures stay pictures. Always starts at "Keep original size", so nothing
    is resized by accident."""

    changed = Signal()

    CHOICES = [
        (None, "Keep original size"),
        (resize.LONGEST, "Longest side"),
        (resize.WIDTH, "Width"),
        (resize.HEIGHT, "Height"),
        (resize.FIT, "Fit inside width × height"),
        (resize.PERCENT, "Percentage"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.mode = QComboBox()
        self.mode.setAccessibleName("Picture size")
        for mode, text in self.CHOICES:
            self.mode.addItem(text, mode)
        self.width_box = self._spin(1920, " px", resize.MAX_SIDE, "Width in pixels")
        self.height_box = self._spin(1080, " px", resize.MAX_SIDE, "Height in pixels")
        self.percent_box = self._spin(50, " %", resize.MAX_PERCENT, "Percentage of the size")
        self.times = label("×", "muted")
        boxes = QHBoxLayout()
        boxes.setContentsMargins(0, 0, 0, 0)
        boxes.setSpacing(6)
        for widget in (self.width_box, self.times, self.height_box, self.percent_box):
            boxes.addWidget(widget)
        boxes.addStretch(1)
        self.enlarge = QCheckBox("Also enlarge smaller pictures")
        self.enlarge.setToolTip(
            "Pictures smaller than the chosen size are made bigger. Enlarging is smooth "
            "but adds no detail, so they won't get sharper."
        )
        self.hint = label("", "small", wrap=True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addWidget(label("Picture size", "caption"))
        layout.addWidget(self.mode)
        layout.addLayout(boxes)
        layout.addWidget(self.enlarge)
        layout.addWidget(self.hint)
        self.mode.currentIndexChanged.connect(self._update)
        self.enlarge.toggled.connect(self._update)
        for box in (self.width_box, self.height_box, self.percent_box):
            box.valueChanged.connect(self._update)
        self._update()

    @staticmethod
    def _spin(value: int, suffix: str, maximum: int, name: str) -> QSpinBox:
        box = QSpinBox()
        box.setRange(1, maximum)
        box.setValue(value)
        box.setSuffix(suffix)
        box.setGroupSeparatorShown(False)
        box.setAccessibleName(name)
        box.setMinimumWidth(96)
        return box

    def spec(self) -> resize.Resize | None:
        """The chosen size, or None for "Keep original size"."""
        mode = self.mode.currentData()
        if mode is None:
            return None
        if mode == resize.PERCENT:
            return resize.Resize(mode, percent=self.percent_box.value())
        return resize.Resize(
            mode,
            width=self.width_box.value(),
            height=self.height_box.value(),
            enlarge=self.enlarge.isChecked(),
        )

    def set_mode(self, mode: str | None) -> None:
        """Select a size choice by its mode (None: keep original size)."""
        index = self.mode.findData(mode)
        if index >= 0:
            self.mode.setCurrentIndex(index)

    def set_busy(self, busy: bool) -> None:
        for widget in (
            self.mode, self.width_box, self.height_box, self.percent_box, self.enlarge
        ):  # fmt: skip
            widget.setEnabled(not busy)

    def _update(self) -> None:
        mode = self.mode.currentData()
        self.width_box.setVisible(mode in (resize.LONGEST, resize.WIDTH, resize.FIT))
        self.height_box.setVisible(mode in (resize.HEIGHT, resize.FIT))
        self.times.setVisible(mode == resize.FIT)
        self.percent_box.setVisible(mode == resize.PERCENT)
        self.enlarge.setVisible(mode not in (None, resize.PERCENT))
        if mode is None:
            hint = "Pictures keep all their pixels."
        elif mode == resize.PERCENT and self.percent_box.value() > 100:
            hint = "Pictures are enlarged smoothly. This adds no detail."
        elif mode == resize.PERCENT:
            hint = "Proportions are kept."
        elif self.enlarge.isChecked():
            hint = (
                "Proportions are kept. Smaller pictures are enlarged smoothly, "
                "which adds no detail."
            )
        else:
            hint = "Proportions are kept. Pictures that are already smaller stay as they are."
        self.hint.setText(hint)
        self.changed.emit()
