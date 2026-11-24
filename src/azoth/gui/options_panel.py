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

from .. import ocr, quality, resize, upscale
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
            button.setToolTip(
                f"{level.description}\nPhoto quality {level.image_quality} of 100 (JPG, WebP, "
                f"HEIC, AVIF) · PDF pages as pictures at {level.dpi} DPI."
            )
            button.setAccessibleName(f"Quality: {level.label}")
            button.toggled.connect(lambda on, lv=level.id: on and self._changed(lv))
            self.group.addButton(button)
            self.buttons[level.id] = button
            row.addWidget(button, 1)
        caption = label("Quality", "caption")
        caption.setToolTip(
            "Only for photos, and for PDF pages that Azoth Converter saves as pictures. "
            "Documents → PDF always keep full quality."
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addWidget(caption)
        layout.addWidget(frame)
        self.buttons[quality.DEFAULT.id].setChecked(True)

    def level(self) -> str:
        return next(k for k, b in self.buttons.items() if b.isChecked())

    def set_level(self, level_id: str | None) -> None:
        if level_id in self.buttons:
            self.buttons[level_id].setChecked(True)

    def set_busy(self, busy: bool) -> None:
        for button in self.buttons.values():
            button.setEnabled(not busy)

    def _changed(self, level_id: str) -> None:
        self.level_changed.emit(level_id)


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


class ExcelOptions(QWidget):
    """PDF → Excel choices on the Convert page (under "More options")."""

    CHOICES = (
        ("tables_only", "Tables only",
         "Does not keep the text that is not in the tables, for example headings and page "
         "footers."),
        ("one_sheet", "All pages on one sheet",
         "Not one sheet for each page. With “Tables only”, a table that continues on more "
         "than one page (for example a bank statement) becomes one table. You can sort "
         "and filter it."),
    )  # fmt: skip

    def __init__(self, prefs: Preferences | None = None) -> None:
        super().__init__()
        self.prefs = prefs or Preferences()
        self.boxes: dict[str, QCheckBox] = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addWidget(label("Excel", "caption"))
        for name, text, tip in self.CHOICES:
            box = QCheckBox(text)
            box.setToolTip(tip)
            box.setChecked(self.prefs.excel_option(name))
            box.toggled.connect(lambda on, n=name: self.prefs.save_excel_option(n, on))
            layout.addWidget(box)
            self.boxes[name] = box

    def options(self) -> dict[str, bool]:
        return {name: box.isChecked() for name, box in self.boxes.items()}

    def summary(self) -> str:
        return " · ".join(box.text() for box in self.boxes.values() if box.isChecked())

    def set_busy(self, busy: bool) -> None:
        for box in self.boxes.values():
            box.setEnabled(not busy)


class OcrOptions(QWidget):
    """ "Text recognition" on the Convert page: shown when a scan or photo becomes text,
    Word or (optional) a searchable PDF."""

    def __init__(self, prefs: Preferences | None = None) -> None:
        super().__init__()
        prefs = prefs or Preferences()
        self.prefs = prefs
        self.searchable = QCheckBox("Make the text searchable (OCR)")
        self.searchable.setToolTip(
            "Azoth Converter reads the text in the pictures and adds it to the PDF. You cannot "
            "see this text, but you can search and copy it. The pictures stay the same. This "
            "is slow: some seconds for each page."
        )
        self.searchable.setChecked(prefs.ocr_searchable)
        self.searchable.toggled.connect(self._toggled)
        self.language = LanguageBox(prefs)
        self.language.setToolTip("The language of the text in scans and photos")
        self.language_label = label("Text language", "caption")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
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
        (resize.FIT, "Screen size"),
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
        self.only_shrink = QCheckBox("Don't enlarge smaller pictures")
        self.only_shrink.setToolTip(
            "Pictures that are smaller than the selected size do not change. Use this to make "
            "large photos smaller (for example for e-mail) and to keep small photos as they are."
        )
        self.ai = QCheckBox("Enhance with AI")
        self.ai.setToolTip(
            "When the AI makes a picture larger, it adds new, sharp shapes. When the picture "
            "keeps its size, it becomes sharper, with less noise and fewer JPEG blocks. The AI "
            "operates only on this computer, and it is slow."
        )
        if not upscale.available():
            self.ai.hide()
        self.best = QCheckBox("Best quality (slow)")
        self.best.setToolTip(
            "Uses a larger AI. Hair, fur and grass look better when small pictures become "
            "much larger. It is approximately 15× slower: some minutes for each picture."
        )
        if not upscale.available(best=True):
            self.best.hide()
        self.denoise = QComboBox()
        self.denoise.setAccessibleName("Noise removal")
        for level, text in upscale.DENOISE_LABELS.items():
            self.denoise.addItem(f"Noise removal: {text}", level)
        self.denoise.setCurrentIndex(self.denoise.findData(upscale.MEDIUM))
        self.denoise.setToolTip(
            "How much noise and how many JPEG blocks the AI removes. Low keeps the small grain "
            "and texture. High gives the cleanest and smoothest result."
        )
        self.hint = label("", "small", wrap=True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addWidget(label("Picture size", "caption"))
        layout.addWidget(self.mode)
        layout.addWidget(self.preset)
        layout.addLayout(boxes)
        layout.addWidget(self.only_shrink)
        layout.addWidget(self.ai)
        layout.addWidget(self.best)
        layout.addWidget(self.denoise)
        layout.addWidget(self.hint)
        self.mode.currentIndexChanged.connect(self._mode_changed)
        self.preset.currentIndexChanged.connect(self._preset_changed)
        self.only_shrink.toggled.connect(self._update)
        self.ai.toggled.connect(self._update)
        self.best.toggled.connect(self._update)
        self.denoise.currentIndexChanged.connect(self._update)
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

    def uses_ai(self) -> bool:
        return self.ai.isChecked() and not self.ai.isHidden()

    def uses_best(self) -> bool:
        return self.uses_ai() and self.best.isChecked() and upscale.available(best=True)

    def spec(self) -> resize.Resize | None:
        """The chosen size, or None for "Keep original size" (without AI). With AI and
        the original size: 100 %, so pictures keep their size and get better."""
        mode = self.mode.currentData()
        ai = {}
        if self.uses_ai():
            ai = {"ai": True, "denoise": self.denoise.currentData(), "best": self.uses_best()}
        if mode is None:
            return resize.Resize(resize.PERCENT, percent=100, **ai) if ai else None
        if mode == resize.PERCENT:
            return resize.Resize(mode, percent=self.percent_box.value(), **ai)
        return resize.Resize(
            mode,
            width=self.width_box.value(),
            height=self.height_box.value(),
            enlarge=not self.only_shrink.isChecked(),
            **ai,
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
            self.only_shrink, self.ai, self.best, self.denoise,
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
        self.width_box.setVisible(custom and mode in (resize.WIDTH, resize.FIT))
        self.height_box.setVisible(custom and mode in (resize.HEIGHT, resize.FIT))
        self.times.setVisible(custom and mode == resize.FIT)
        self.percent_box.setVisible(custom and mode == resize.PERCENT)
        self.only_shrink.setVisible(mode not in (None, resize.PERCENT))
        ai = self.uses_ai()
        self.best.setVisible(ai and upscale.available(best=True))
        self.denoise.setVisible(ai and not self.uses_best())  # the big model has one setting
        if mode is None and ai:
            hint = "Pictures keep their size and get sharper, with less noise."
        elif mode is None:
            hint = "Pictures keep all their pixels."
        elif mode == resize.FIT:
            hint = (
                "The picture fits inside this size with its proportions kept, so one side "
                "may come out smaller. Portrait pictures are turned: 1920 × 1080 becomes "
                "1080 × 1920."
            )
        else:
            hint = "Proportions are kept."
        if mode is not None and (mode != resize.PERCENT or self.percent_box.value() > 100):
            if ai and (not self.only_shrink.isChecked() or mode == resize.PERCENT):
                hint += " Enlarging adds sharp detail."
            elif not self.only_shrink.isChecked() or mode == resize.PERCENT:
                hint += " Enlarging is smooth but adds no detail."
            else:
                hint += " Pictures that are already smaller stay as they are."
        if ai:
            if mode is not None:
                hint += " The AI is used for pictures that get bigger or keep their size."
            hint += (
                " The AI invents detail: it looks real but isn't fully true to the original"
                " (not for documents, evidence or ID photos). Takes a while."
            )
        self.mode.setToolTip(hint)
        self.preset.setToolTip(hint)
        # Only the AI's caveat stays visible: the result isn't fully true to the original.
        warning = "The AI invents detail: not for documents or ID photos." if ai else ""
        self.hint.setText(warning)
        self.hint.setToolTip(hint)
        self.hint.setVisible(bool(warning))
        self.changed.emit()

    def summary(self) -> str:
        """A few words for the closed "More options": "Original size", "Full HD · AI" …"""
        mode = self.mode.currentData()
        if mode is None:
            text = "Original size"
        elif self.is_custom():
            text = f"{self.mode.currentText()}: custom"
        else:
            text = self.preset.currentText().split(" (")[0]
        return f"{text} · AI" if self.uses_ai() else text
