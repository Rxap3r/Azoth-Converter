"""The About window: version, privacy promise, license and included components."""

from __future__ import annotations

from importlib import metadata

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from .. import __version__
from ..converters.msword import APPS, app_installed
from ..converters.office import find_soffice
from .resources import icon_path

# (name, distribution name for the version or None, license, what it does)
COMPONENTS = [
    ("Qt / PySide6", "PySide6-Essentials", "LGPL-3.0", "Window and controls"),
    ("Pillow", "pillow", "MIT-CMU", "Images"),
    ("pillow-heif / libheif", "pillow-heif", "BSD-3-Clause / LGPL-3.0", "HEIC and AVIF photos"),
    ("PyMuPDF / MuPDF", "PyMuPDF", "AGPL-3.0", "PDF reading, rendering, merging"),
    ("pdf2docx", "pdf2docx", "MIT", "PDF → Word"),
    ("python-docx", "python-docx", "MIT", "Word files for PDF → Word and OCR"),
    ("openpyxl", "openpyxl", "MIT", "Excel files for PDF → Excel"),
    ("et-xmlfile", "et-xmlfile", "MIT", "Used by the above"),
    ("Tesseract OCR", None, "Apache-2.0", "Text recognition (built into MuPDF)"),
    ("Tesseract language data", None, "Apache-2.0", "OCR in English, German, French, Italian"),
    ("OpenCV", "opencv-python-headless", "Apache-2.0", "PDF → Word layout, runs the AI model"),
    ("Real-ESRGAN model", None, "BSD-3-Clause", "Enhance with AI (by Xintao Wang et al.)"),
    ("msoffcrypto-tool", "msoffcrypto-tool", "MIT", "Passwords on Word, Excel, PowerPoint"),
    ("cryptography", "cryptography", "Apache-2.0 / BSD-3-Clause", "Encryption for the above"),
    ("olefile", "olefile", "BSD-2-Clause", "Reads older Office files for the above"),
    ("NumPy", "numpy", "BSD-3-Clause", "Used by the above"),
    ("FFmpeg", None, "GPL-3.0", "Video and audio (Windows build by Gyan Doshi)"),
    ("LibreOffice", None, "MPL-2.0", "Office formats (installed separately)"),
    ("Microsoft Word", None, "Your own Microsoft licence", "Word → PDF, optional"),
]


def _version(dist: str | None) -> str:
    if dist is None:
        return ""
    try:
        return metadata.version(dist)
    except metadata.PackageNotFoundError:
        return ""


class AboutDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("About Azoth Converter")
        self.resize(640, 560)
        layout = QVBoxLayout(self)

        header = QHBoxLayout()
        icon = QLabel()
        icon.setPixmap(
            QPixmap(str(icon_path())).scaled(
                72,
                72,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
        header.addWidget(icon)
        title = QLabel(
            f"<h2 style='margin:0'>Azoth Converter</h2>Version {__version__}<br>"
            "Converts documents, PDFs and images on your own computer."
        )
        header.addWidget(title, 1)
        layout.addLayout(header)

        privacy = QLabel(
            "<b>🔒 Your files never leave this computer.</b> No uploads, no account, no "
            "tracking, no automatic internet connection. Temporary files are deleted after "
            "each conversion, and photo location data is removed by default."
        )
        privacy.setWordWrap(True)
        layout.addWidget(privacy)

        license_text = QLabel(
            "Azoth Converter is free, open-source software under the "
            "<b>GNU General Public License v3.0 or later</b>. You may use, study, share and "
            "change it. It comes with no warranty."
        )
        license_text.setWordWrap(True)
        layout.addWidget(license_text)

        engines = []
        soffice = find_soffice()
        engines.append(f"LibreOffice: {'found' if soffice else 'not installed'}")
        for app in APPS:
            engines.append(f"{app.label}: {'found' if app_installed(app) else 'not installed'}")
        self.engines_label = QLabel(" · ".join(engines))
        layout.addWidget(self.engines_label)

        layout.addWidget(QLabel("<b>Included components</b>"))
        self.components = QTreeWidget()
        self.components.setHeaderLabels(["Component", "Version", "License", "Used for"])
        self.components.setRootIsDecorated(False)
        for name, dist, license_name, purpose in COMPONENTS:
            self.components.addTopLevelItem(
                QTreeWidgetItem([name, _version(dist), license_name, purpose])
            )
        header_view = self.components.header()
        for col in range(3):
            header_view.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        header_view.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.components, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)
