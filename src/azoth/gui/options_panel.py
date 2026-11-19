"""Quality choice (Maximum / High / Smaller) shown next to "Convert to"."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QButtonGroup, QFrame, QHBoxLayout, QPushButton, QVBoxLayout, QWidget

from .. import quality
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
