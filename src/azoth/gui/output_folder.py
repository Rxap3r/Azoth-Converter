"""The "Save to" row: next to the original, or a folder the user picks."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QLabel, QPushButton, QWidget

from .settings import forget_file_dialog_history

SAME_FOLDER = "Same folder as the original"


class OutputFolderRow(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._folder: Path | None = None
        self.label = QLabel(SAME_FOLDER)
        self.choose_btn = QPushButton("Choose folder…")
        self.choose_btn.clicked.connect(self._choose)
        self.reset_btn = QPushButton("Reset")
        self.reset_btn.clicked.connect(lambda: setattr(self, "folder", None))
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.label, 1)
        layout.addWidget(self.choose_btn)
        layout.addWidget(self.reset_btn)

    @property
    def folder(self) -> Path | None:
        """The chosen folder, or None for "next to each original"."""
        return self._folder

    @folder.setter
    def folder(self, folder: Path | None) -> None:
        self._folder = Path(folder) if folder is not None else None
        self.label.setText(str(self._folder) if self._folder is not None else SAME_FOLDER)

    def set_busy(self, busy: bool) -> None:
        self.choose_btn.setEnabled(not busy)
        self.reset_btn.setEnabled(not busy)

    def _choose(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Save converted files to")
        forget_file_dialog_history()
        if folder:
            self.folder = Path(folder)
