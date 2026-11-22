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
    """ "Picture size" on the Convert page: keep the size (default), or choose a new one
    from ready-made sizes (Full HD, 4K …) or a custom size. Shown when pictures stay
    pictures. Always starts at "Keep original size", so nothing is resized by accident."""

    changed = Signal()

    CHOICES = [
        (None, "Keep original size"),
        (resize.FIT, "Fit inside width × height"),
        (resize.LONGEST, "Longest side"),
        (resize.WIDTH, "Width"),
        (resize.HEIGHT, "Height"),
        (resize.PERCENT, "Percentage"),
    ]
    CUSTOM = "Custom size…"

    def __init__(self) -> None:
        super().__init__()
        self.mode = QComboBox()
        self.mode.setAccessibleName("Picture size")
        for mode, text in self.CHOICES:
            self.mode.addItem(text, mode)
        self.preset = QComboBox()
        self.preset.setAccessibleName("Size")
        self.preset.setMaxVisibleItems(12)
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
        layout.addWidget(self.preset)
        layout.addLayout(boxes)
        layout.addWidget(self.enlarge)
        layout.addWidget(self.hint)
        self.mode.currentIndexChanged.connect(self._mode_changed)
        self.preset.currentIndexChanged.connect(self._preset_changed)
        self.enlarge.toggled.connect(self._update)
        for box in (self.width_box, self.height_box, self.percent_box):
            box.valueChanged.connect(self._update)
        self._mode_changed()

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

    def is_custom(self) -> bool:
        return self.preset.currentData() is None

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

    def set_custom(self, width: int = 0, height: int = 0, percent: int = 0) -> None:
        """Choose "Custom size…" with these numbers (0: leave as it is)."""
        self.preset.setCurrentIndex(self.preset.count() - 1)
        for box, value in ((self.width_box, width), (self.height_box, height),
                           (self.percent_box, percent)):  # fmt: skip
            if value:
                box.setValue(value)

    def set_busy(self, busy: bool) -> None:
        for widget in (
            self.mode, self.preset, self.width_box, self.height_box, self.percent_box,
            self.enlarge,
        ):  # fmt: skip
            widget.setEnabled(not busy)

    def _mode_changed(self) -> None:
        """New list of ready-made sizes for the choice; the usual one (Full HD) first."""
        mode = self.mode.currentData()
        self.preset.blockSignals(True)
        self.preset.clear()
        for preset in resize.PRESETS.get(mode, []):
            self.preset.addItem(preset.label, preset)
        if mode is not None:
            self.preset.addItem(self.CUSTOM, None)
            self.preset.setCurrentIndex(resize.DEFAULT_PRESET[mode])
        self.preset.blockSignals(False)
        self._preset_changed()

    def _preset_changed(self) -> None:
        preset = self.preset.currentData()
        if preset is not None:  # the boxes always hold the size that is used
            for box, value in ((self.width_box, preset.width), (self.height_box, preset.height),
                               (self.percent_box, round(preset.percent))):  # fmt: skip
                if value:
                    box.blockSignals(True)
                    box.setValue(value)
                    box.blockSignals(False)
        self._update()

    def _update(self) -> None:
        mode = self.mode.currentData()
        custom = mode is not None and self.is_custom()
        self.preset.setVisible(mode is not None)
        self.width_box.setVisible(custom and mode in (resize.LONGEST, resize.WIDTH, resize.FIT))
        self.height_box.setVisible(custom and mode in (resize.HEIGHT, resize.FIT))
        self.times.setVisible(custom and mode == resize.FIT)
        self.percent_box.setVisible(custom and mode == resize.PERCENT)
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
        if mode == resize.FIT:
            hint += " The picture fits inside the box, so one side may come out smaller."
        self.hint.setText(hint)
        self.changed.emit()
