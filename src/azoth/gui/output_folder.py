"""Where results go ("Save to") and what they are called ("File name")."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..engine import check_file_name
from .settings import forget_file_dialog_history
from .widgets import label

SAME_FOLDER = "Same folder as the original"


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
        self.reset_btn.setAccessibleName("Save in the same folder as the original again")
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


class FileNameRow(QWidget):
    """The result's name. Starts as the original's name; can be changed for a single file."""

    MANY = "Each file keeps its own name"

    def __init__(self) -> None:
        super().__init__()
        self._default = ""
        self.edit = QLineEdit()
        self.edit.setAccessibleName("File name of the result")
        self.extension = label("", "muted")
        row = QHBoxLayout()
        row.setSpacing(6)
        row.addWidget(self.edit, 1)
        row.addWidget(self.extension)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.caption = label("File name", "caption")
        layout.addWidget(self.caption)
        layout.addLayout(row)
        self.set_sources([])

    def set_name(
        self, default: str | None, extension: str = "", caption: str = "File name"
    ) -> None:
        """One result with the suggested name ``default`` (keeping a name already typed for
        it), or no choice (None)."""
        default = default or ""
        if default != self._default:
            self._default = default
            self.edit.setText(default)
        self.caption.setText(caption)
        self.edit.setEnabled(bool(default))
        self.edit.setPlaceholderText("")
        self.set_extension(extension)
        self.extension.setVisible(bool(default and extension))

    def name(self, extension: str = "") -> str:
        """The typed name, checked (raises ConversionError), or the suggested one."""
        return check_file_name(self.edit.text() or self._default, extension)

    def set_sources(self, paths: list[Path]) -> None:
        """One file: offer its name (keeping a name already typed for it). Else: no choice."""
        default = paths[0].stem if len(paths) == 1 else ""
        if default != self._default:
            self._default = default
            self.edit.setText(default)
        self.edit.setEnabled(len(paths) == 1)
        self.edit.setPlaceholderText(self.MANY if len(paths) > 1 else "")
        self.extension.setVisible(len(paths) == 1)

    def set_extension(self, extension: str) -> None:
        self.extension.setText(f".{extension}" if extension else "")

    def set_busy(self, busy: bool) -> None:
        self.edit.setReadOnly(busy)

    def custom_name(self) -> str | None:
        """The typed name, or None when it is the original's name (or nothing was typed)."""
        if not self.edit.isEnabled():
            return None
        text = self.edit.text().strip()
        return text if text and text != self._default else None
