""" "Convert to": one tile per target format, plus the "Remove metadata only" tile."""

from __future__ import annotations

from collections.abc import Iterable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from . import icons
from .targets import CLEAN_TARGET, CLEAN_TILE, RESIZE_TARGET, RESIZE_TILE, Choices, tile_text
from .theme import LIGHT_COLORS, Colors
from .widgets import discard, label

COLUMNS = 3


class Tile(QPushButton):
    """A checkable button with a bold title and a short line under it."""

    def __init__(self, target: str, title: str, subtitle: str, *, wide: bool = False) -> None:
        super().__init__()
        self.target = target
        self.setProperty("role", "tile")
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAccessibleName(f"{title}: {subtitle}")
        self.setToolTip(subtitle)
        self.setProperty("wide", "true" if wide else "false")
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)  # focus ring only when using the keyboard
        self.title = label(title)
        self.title.setStyleSheet("font-weight: 700; font-size: 13px;")
        self.subtitle = label(subtitle, "small")
        self.subtitle.setWordWrap(wide)
        self.icon_label = QLabel()
        if not wide:  # (never setVisible(True) before it has a parent: see discard)
            self.icon_label.hide()
        text = QVBoxLayout()
        text.setSpacing(0)
        text.addWidget(self.title)
        text.addWidget(self.subtitle)
        row = QHBoxLayout(self)
        row.setContentsMargins(10, 6, 8, 6)
        row.setSpacing(10)
        row.addWidget(self.icon_label)
        row.addLayout(text, 1)
        for child in (self.title, self.subtitle, self.icon_label):
            child.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)


class TargetPicker(QWidget):
    changed = Signal(object)  # the new target id, or None

    def __init__(self) -> None:
        super().__init__()
        self._colors: Colors = LIGHT_COLORS
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.group.buttonToggled.connect(self._toggled)
        self.tiles: list[Tile] = []
        self._grid = QGridLayout()
        self._grid.setSpacing(8)
        for col in range(COLUMNS):
            self._grid.setColumnStretch(col, 1)
        self.resize_tile = Tile(RESIZE_TARGET, *RESIZE_TILE, wide=True)
        self.clean_tile = Tile(CLEAN_TARGET, *CLEAN_TILE, wide=True)
        self.extra_tiles = [self.resize_tile, self.clean_tile]  # below the formats
        for tile in self.extra_tiles:
            tile.setVisible(False)
            self.group.addButton(tile)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.addLayout(self._grid)
        for tile in self.extra_tiles:
            layout.addWidget(tile)
        self._quiet = False
        self.apply_colors(self._colors)

    def set_choices(self, choices: Choices, keep: Iterable[str | None] = ()) -> None:
        """Show the tiles for ``choices`` and select the first of ``keep`` that's offered
        (else the first tile, the most useful target)."""
        self._quiet = True
        try:
            for tile in self.tiles:
                self.group.removeButton(tile)
                self._grid.removeWidget(tile)
                discard(tile)
            self.tiles = []
            for i, fmt in enumerate(choices.formats):
                tile = Tile(fmt.id, *tile_text(fmt.id))
                self.group.addButton(tile)
                self._grid.addWidget(tile, i // COLUMNS, i % COLUMNS)
                self.tiles.append(tile)
            self.resize_tile.setVisible(choices.can_resize)
            self.clean_tile.setVisible(choices.can_clean)
            for tile in self.extra_tiles:
                tile.setChecked(False)
            offered = self.ids()
            wanted = next((k for k in keep if k in offered), offered[0] if offered else None)
            for button in self._buttons():
                button.setChecked(button.target == wanted)
        finally:
            self._quiet = False
        self.changed.emit(self.current())

    def _buttons(self) -> list[Tile]:
        return [*self.tiles, *(t for t in self.extra_tiles if not t.isHidden())]

    def ids(self) -> list[str]:
        """Offered targets in order; "resize" and "clean" (same format) come last."""
        return [t.target for t in self._buttons()]

    def current(self) -> str | None:
        button = self.group.checkedButton()
        return button.target if isinstance(button, Tile) and button.target in self.ids() else None

    def select(self, target: str) -> bool:
        for button in (*self.tiles, *self.extra_tiles):
            if button.target == target and target in self.ids():
                button.setChecked(True)
                return True
        return False

    def set_busy(self, busy: bool) -> None:
        for button in (*self.tiles, *self.extra_tiles):
            button.setEnabled(not busy)

    def apply_colors(self, colors: Colors) -> None:
        self._colors = colors
        self.clean_tile.icon_label.setPixmap(icons.pixmap("shield", colors.success, 20))
        self.resize_tile.icon_label.setPixmap(icons.pixmap("resize", colors.accent, 20))

    def _toggled(self, button, checked: bool) -> None:
        if checked and not self._quiet:
            self.changed.emit(self.current())
