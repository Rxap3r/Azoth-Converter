"""The "Save to" choice: same folder as the originals, or a folder the user picks."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .settings import forget_file_dialog_history
from .widgets import label

SAME_FOLDER = "Same folder as the original files"


class OutputFolderRow(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._folder: Path | None = None
        self.label = label(SAME_FOLDER)
        self.label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.choose_btn = QPushButton("Change…")
        self.choose_btn.setAccessibleName("Choose the folder to save to")
        self.choose_btn.clicked.connect(self._choose)
        self.reset_btn = QPushButton("Reset")
        self.reset_btn.setAccessibleName("Save in the same folder as the original files again")
        self.reset_btn.clicked.connect(lambda: setattr(self, "folder", None))
        row = QHBoxLayout()
        row.setSpacing(6)
        row.addWidget(self.label, 1)
        row.addWidget(self.choose_btn)
        row.addWidget(self.reset_btn)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addWidget(label("Save to", "caption"))
        layout.addLayout(row)
        self._update()

    @property
    def folder(self) -> Path | None:
        """The chosen folder, or None for "next to each original"."""
        return self._folder

    @folder.setter
    def folder(self, folder: Path | None) -> None:
        self._folder = Path(folder) if folder is not None else None
        self._update()

    def set_busy(self, busy: bool) -> None:
        self.choose_btn.setEnabled(not busy)
        self.reset_btn.setEnabled(not busy)

    def _update(self) -> None:
        text = str(self._folder) if self._folder is not None else SAME_FOLDER
        self.label.setText(text)
        self.label.setToolTip(text)
        self.reset_btn.setVisible(self._folder is not None)

    def _choose(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Save converted files to")
        forget_file_dialog_history()
        if folder:
            self.folder = Path(folder)
