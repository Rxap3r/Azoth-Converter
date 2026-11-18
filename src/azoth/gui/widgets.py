"""Small reusable widgets."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QSizePolicy, QToolButton, QVBoxLayout, QWidget


class CollapsibleSection(QWidget):
    """A heading with an arrow that shows or hides the content below it."""

    def __init__(self, title: str, content: QWidget, *, expanded: bool = False) -> None:
        super().__init__()
        self.content = content
        self.toggle = QToolButton()
        self.toggle.setText(title)
        self.toggle.setCheckable(True)
        self.toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.toggle.setAutoRaise(True)
        self.toggle.setStyleSheet("QToolButton { font-weight: bold; border: none; }")
        self.toggle.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.toggle.toggled.connect(self.set_expanded)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addWidget(self.toggle)
        layout.addWidget(content)
        self.set_expanded(expanded)

    def is_expanded(self) -> bool:
        return self.toggle.isChecked()

    def set_expanded(self, expanded: bool) -> None:
        if self.toggle.isChecked() != expanded:
            self.toggle.setChecked(expanded)  # emits toggled → calls us again
            return
        self.toggle.setArrowType(Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow)
        self.content.setVisible(expanded)
        # Closed sections take only the height of their heading.
        vertical = QSizePolicy.Policy.Preferred if expanded else QSizePolicy.Policy.Maximum
        self.setSizePolicy(QSizePolicy.Policy.Preferred, vertical)
