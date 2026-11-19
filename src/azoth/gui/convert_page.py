"""The "Convert" page: drop area and file cards on the left, the choices on the right."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from . import icons
from .file_list import FileList
from .options_panel import QualitySelector
from .output_folder import OutputFolderRow
from .target_picker import TargetPicker
from .theme import Colors, repolish
from .widgets import label


class ConvertPage(QWidget):
    def __init__(self, banners: list[str]) -> None:
        super().__init__()
        self.file_list = FileList()
        self.target_picker = TargetPicker()
        self.quality = QualitySelector()
        self.output_row = OutputFolderRow()

        # --- left: header, drop area, files
        self.title = label("Convert files", "h1")
        self.subtitle = label("", "muted")
        titles = QVBoxLayout()
        titles.setSpacing(2)
        titles.addWidget(self.title)
        titles.addWidget(self.subtitle)
        header = QHBoxLayout()
        header.addLayout(titles, 1)
        header.addWidget(self.file_list.clear_btn, 0, Qt.AlignmentFlag.AlignBottom)

        self.drop_zone = QFrame()
        self.drop_zone.setObjectName("DropZone")
        self.drop_icon = QLabel()
        self.drop_icon.setFixedSize(44, 44)
        self.drop_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        drop_text = QVBoxLayout()
        drop_text.setSpacing(2)
        drop_title = label("Drag files or folders here")
        drop_title.setStyleSheet("font-weight: 600;")
        drop_text.addWidget(drop_title)
        drop_text.addWidget(label("Photos, PDFs, Word, Excel and PowerPoint files", "small"))
        drop_row = QHBoxLayout(self.drop_zone)
        drop_row.setContentsMargins(18, 14, 18, 14)
        drop_row.setSpacing(16)
        drop_row.addWidget(self.drop_icon)
        drop_row.addLayout(drop_text, 1)
        drop_row.addWidget(self.file_list.add_btn)

        left = QVBoxLayout()
        left.setContentsMargins(28, 24, 24, 20)
        left.setSpacing(16)
        for text in banners:
            left.addWidget(label(f"⚠ {text}", "banner", wrap=True))
        left.addLayout(header)
        left.addWidget(self.drop_zone)
        left.addWidget(self.file_list, 1)

        # --- right: what to convert to, quality, folder, the button
        self.notes_label = label("", "note", wrap=True)
        self.status_label = label("", "small")
        self.status_label.setWordWrap(True)
        self.progress = QProgressBar()
        self.progress.setProperty("role", "overall")
        self.progress.setRange(0, 1000)
        self.progress.setTextVisible(False)
        self.progress.setAccessibleName("Overall progress")
        self.open_btn = QPushButton("Open output folder")
        self.open_btn.setProperty("role", "link")
        self.open_btn.setVisible(False)  # shown once something was saved
        self.progress.setVisible(False)  # shown while converting
        self.convert_btn = QPushButton("Convert")
        self.convert_btn.setProperty("role", "primary")
        self.convert_btn.setDefault(True)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setMinimumHeight(44)
        self.cancel_btn.setVisible(False)

        self.right = QFrame()
        self.right.setObjectName("RightPanel")
        self.right.setFixedWidth(350)
        right = QVBoxLayout(self.right)
        right.setContentsMargins(22, 24, 22, 20)
        right.setSpacing(14)
        right.addWidget(label("Convert to", "h2"))
        right.addWidget(self.target_picker)
        right.addWidget(self.notes_label)
        right.addWidget(self.quality)
        right.addWidget(self.output_row)
        right.addStretch(1)
        right.addWidget(self.status_label)
        right.addWidget(self.progress)
        right.addWidget(self.open_btn, 0, Qt.AlignmentFlag.AlignLeft)
        right.addWidget(self.convert_btn)
        right.addWidget(self.cancel_btn)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addLayout(left, 1)
        layout.addWidget(self.right)

    def set_drop_active(self, active: bool) -> None:
        self.drop_zone.setProperty("active", "true" if active else "false")
        repolish(self.drop_zone)

    def apply_colors(self, colors: Colors) -> None:
        self.drop_icon.setPixmap(icons.pixmap("upload", colors.accent, 24))
        self.file_list.apply_colors(colors)
        self.target_picker.apply_colors(colors)
