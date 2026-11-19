"""The "Options" section: quality level, photo metadata, Microsoft Word."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QCheckBox, QComboBox, QFormLayout, QLabel, QWidget

from .. import quality
from .settings import Preferences


class OptionsPanel(QWidget):
    use_word_changed = Signal(bool)

    def __init__(self, *, word_installed: bool, use_word: bool) -> None:
        super().__init__()
        self.word_installed = word_installed

        self.level_combo = QComboBox()
        for level in quality.LEVELS:
            self.level_combo.addItem(level.label, level.id)
        self.level_hint = QLabel()
        self.level_hint.setWordWrap(True)
        self.level_hint.setStyleSheet("color: palette(placeholder-text);")
        self.level_combo.currentIndexChanged.connect(self._update_level_hint)
        self._update_level_hint()

        self.metadata_check = QCheckBox("Keep photo metadata (camera, date, GPS location)")

        self.word_check = QCheckBox("Use Microsoft Word for Word → PDF (exact layout and fonts)")
        self.word_check.setToolTip(
            "Word converts the file on this computer; nothing is uploaded.\n"
            "Macros stay off. If Word fails, LibreOffice is used instead."
        )
        self.word_check.setChecked(use_word)
        self.word_check.setVisible(word_installed)  # only when Word is installed
        self.word_check.toggled.connect(self.use_word_changed)

        form = QFormLayout(self)
        form.setContentsMargins(16, 0, 0, 0)
        form.addRow("Quality:", self.level_combo)
        form.addRow("", self.level_hint)
        form.addRow(self.metadata_check)
        form.addRow(self.word_check)

    def level(self) -> str:
        return self.level_combo.currentData()

    def set_level(self, level_id: str) -> None:
        index = self.level_combo.findData(level_id)
        if index >= 0:
            self.level_combo.setCurrentIndex(index)

    def options(self) -> dict:
        """The conversion options for ``Engine.convert``."""
        return {"level": self.level(), "keep_metadata": self.metadata_check.isChecked()}

    def load(self, prefs: Preferences) -> None:
        if prefs.level:
            self.set_level(prefs.level)
        self.metadata_check.setChecked(prefs.keep_metadata)

    def use_word(self, saved: bool) -> bool:
        """The Word setting to save (the saved one if Word isn't installed here)."""
        return self.word_check.isChecked() if self.word_installed else saved

    def _update_level_hint(self) -> None:
        level = quality.BY_ID[self.level()]
        self.level_hint.setText(
            f"{level.description} Photos: quality {level.image_quality} · "
            f"PDF pages as images: {level.dpi} DPI. Word/Excel/PowerPoint → PDF and "
            "image → PDF always keep full quality."
        )
