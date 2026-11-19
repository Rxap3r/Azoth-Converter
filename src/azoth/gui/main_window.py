"""Main window: drop files, choose a format, convert.

The window puts the parts together and runs a conversion. The parts live in their own
modules: ``file_list`` (the files and their status), ``options_panel``, ``output_folder``,
``targets`` (which formats are offered, without Qt) and ``worker`` (the background thread).
"""

from __future__ import annotations

import threading
from pathlib import Path

from PySide6.QtCore import Qt, QThread, QUrl, Slot
from PySide6.QtGui import QDesktopServices, QDragEnterEvent, QDropEvent, QIcon
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .. import __version__
from ..converters import all_converters
from ..converters.msword import word_installed
from ..engine import Engine
from . import targets
from .about import AboutDialog
from .file_list import FileList
from .formats_panel import FormatsPanel
from .options_panel import OptionsPanel
from .output_folder import OutputFolderRow
from .resources import icon_path
from .settings import Preferences
from .targets import CLEAN_LABEL, CLEAN_TARGET
from .widgets import CollapsibleSection
from .worker import ConversionWorker

TAGLINE = "– File conversion"


class MainWindow(QMainWindow):
    def __init__(self, engine: Engine | None = None, prefs: Preferences | None = None) -> None:
        super().__init__()
        self.prefs = prefs or Preferences()
        self.engine = engine or Engine(all_converters(use_word=self.prefs.use_word))
        self.last_output: Path | None = None
        self._thread: QThread | None = None
        self._worker: ConversionWorker | None = None
        self._cancel = threading.Event()
        self._done_count = 0
        self._job_count = 0

        self.setWindowTitle(f"Azoth Converter {__version__}")
        self.resize(820, 600)
        self.setAcceptDrops(True)
        self._build_ui()
        self._load_preferences()
        self._refresh()

    # --- layout -------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.addLayout(self._header())

        for conv in self.engine.unavailable():
            banner = QLabel(f"⚠ {conv.unavailable_reason()}")
            banner.setWordWrap(True)
            banner.setStyleSheet(
                "background:#fff4ce; color:#5c4400; padding:8px; border-radius:4px;"
            )
            layout.addWidget(banner)

        self.file_list = FileList()
        self.file_list.changed.connect(self._refresh)
        layout.addWidget(self.file_list, 1)

        form = QFormLayout()
        self.target_combo = QComboBox()
        self.target_combo.currentIndexChanged.connect(self._update_notes)
        form.addRow("Convert to:", self.target_combo)
        self.output_row = OutputFolderRow()
        form.addRow("Save to:", self.output_row)
        layout.addLayout(form)

        self.options = OptionsPanel(
            word_installed=word_installed(), use_word=self.engine.uses_word()
        )
        self.options.use_word_changed.connect(self._set_use_word)
        self.options_section = CollapsibleSection("Options", self.options)
        layout.addWidget(self.options_section)

        libreoffice_installed = not any(c.id == "libreoffice" for c in self.engine.unavailable())
        self.formats_panel = FormatsPanel(libreoffice_installed)
        self.formats_section = CollapsibleSection("Supported formats", self.formats_panel)
        layout.addWidget(self.formats_section)

        self.notes_label = QLabel()
        self.notes_label.setWordWrap(True)
        self.notes_label.setStyleSheet("color: palette(placeholder-text);")
        layout.addWidget(self.notes_label)

        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setTextVisible(False)
        layout.addWidget(self.progress)
        layout.addLayout(self._actions())
        self.setCentralWidget(root)

    def _header(self) -> QHBoxLayout:
        header = QHBoxLayout()
        logo = QLabel()
        logo.setPixmap(QIcon(str(icon_path())).pixmap(40, 40))
        header.addWidget(logo)
        titles = QVBoxLayout()
        titles.setSpacing(0)
        # Name plus a short description, so it's clear at a glance what the app does.
        title = QLabel(
            "<h2 style='margin:0'>Azoth Converter "
            f"<span style='font-weight:normal; color:#8a8aa0'>{TAGLINE}</span></h2>"
        )
        subtitle = QLabel("🔒 Works offline. Your files never leave this computer.")
        subtitle.setStyleSheet("color: palette(placeholder-text);")
        titles.addWidget(title)
        titles.addWidget(subtitle)
        header.addLayout(titles, 1)
        self.about_btn = QPushButton("About")
        self.about_btn.clicked.connect(self.show_about)
        header.addWidget(self.about_btn, 0, Qt.AlignmentFlag.AlignTop)
        return header

    def _actions(self) -> QHBoxLayout:
        actions = QHBoxLayout()
        self.status_label = QLabel()
        self.open_btn = QPushButton("Open output folder")
        self.open_btn.clicked.connect(self._open_output_folder)
        self.open_btn.setEnabled(False)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self._cancel_conversion)
        self.cancel_btn.setVisible(False)
        self.convert_btn = QPushButton("Convert")
        self.convert_btn.setDefault(True)
        self.convert_btn.setMinimumWidth(120)
        self.convert_btn.clicked.connect(self.start_conversion)
        actions.addWidget(self.status_label, 1)
        actions.addWidget(self.open_btn)
        actions.addWidget(self.cancel_btn)
        actions.addWidget(self.convert_btn)
        return actions

    # --- files ------------------------------------------------------------------

    def add_files(self, paths) -> None:
        self.file_list.add_files(paths)

    @property
    def output_dir(self) -> Path | None:
        return self.output_row.folder

    @output_dir.setter
    def output_dir(self, folder: Path | None) -> None:
        self.output_row.folder = folder

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls() and self._thread is None:
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        self.add_files(u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile())

    # --- target formats -------------------------------------------------------

    def _refresh(self) -> None:
        file_formats = self.file_list.formats
        choices = targets.choices(self.engine, file_formats)
        previous = self.target_combo.currentData()
        self.target_combo.blockSignals(True)
        self.target_combo.clear()
        for fmt in choices.formats:
            self.target_combo.addItem(f"{fmt.name} (.{fmt.extension})", fmt.id)
        if choices.can_clean:
            if self.target_combo.count():
                self.target_combo.insertSeparator(self.target_combo.count())
            self.target_combo.addItem(CLEAN_LABEL, CLEAN_TARGET)
        # Keep the current choice or the remembered one; otherwise the list is ordered
        # by usefulness, so its first entry (e.g. Word for a PDF) is the default.
        self.target_combo.setCurrentIndex(0)
        for wanted in (previous, self._remembered_target()):
            index = self.target_combo.findData(wanted) if wanted else -1
            if index >= 0:
                self.target_combo.setCurrentIndex(index)
                break
        self.target_combo.blockSignals(False)

        if targets.source_formats(file_formats) and not choices:
            self.notes_label.setText(targets.NO_COMMON_TARGET)
        else:
            self._update_notes()
        busy = self._thread is not None
        self.convert_btn.setEnabled(bool(choices) and not busy)
        self.file_list.set_busy(busy)
        self.output_row.set_busy(busy)
        self.target_combo.setEnabled(not busy)

    def _update_notes(self) -> None:
        target = self.target_combo.currentData()
        self.options.metadata_check.setEnabled(target != CLEAN_TARGET)
        notes = targets.notes(self.engine, self.file_list.formats, target)
        self.notes_label.setText("\n".join(f"ℹ {n}" for n in notes))

    def _set_use_word(self, use_word: bool) -> None:
        self.engine = Engine(all_converters(use_word=use_word))
        self._update_notes()

    def set_quality_level(self, level_id: str) -> None:
        self.options.set_level(level_id)

    # --- conversion -----------------------------------------------------------

    def start_conversion(self) -> None:
        target = self.target_combo.currentData()
        if not target or self._thread is not None:
            return
        jobs = []
        for row, (path, fmt) in enumerate(
            zip(self.file_list.files, self.file_list.formats, strict=True)
        ):
            if fmt is None:
                self.file_list.set_status(row, "Skipped: unknown file type")
            elif fmt.id == target:
                self.file_list.set_status(row, "Skipped: already this format")
            else:
                self.file_list.set_status(row, "Waiting")
                jobs.append((row, path))
        if not jobs:
            return
        category = targets.single_category(self.file_list.formats)
        if category is not None:
            self.prefs.save_target(category, target)
        self.save_preferences()

        self._cancel = threading.Event()
        self._done_count = 0
        self._job_count = len(jobs)
        self.progress.setValue(0)
        self.open_btn.setEnabled(False)

        self._thread = QThread(self)
        self._worker = ConversionWorker(
            self.engine, jobs, target, self.output_dir, self.options.options(), self._cancel
        )
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.file_started.connect(self._on_started)
        self._worker.file_progress.connect(self._on_progress)
        self._worker.file_done.connect(self._on_done)
        self._worker.file_failed.connect(self._on_failed)
        self._worker.finished.connect(self._on_finished)
        self.convert_btn.setVisible(False)
        self.cancel_btn.setVisible(True)
        self.cancel_btn.setEnabled(True)
        self._thread.start()
        self._refresh()

    def _cancel_conversion(self) -> None:
        self._cancel.set()
        self.cancel_btn.setEnabled(False)
        self.status_label.setText("Cancelling…")

    def _set_overall(self, row_fraction: float) -> None:
        overall = (self._done_count + row_fraction) / max(self._job_count, 1)
        self.progress.setValue(int(overall * 1000))

    @Slot(int)
    def _on_started(self, row: int) -> None:
        cleaning = self._worker is not None and self._worker.target == CLEAN_TARGET
        verb = "Removing metadata from" if cleaning else "Converting"
        self.file_list.set_status(row, "Working…")
        self.status_label.setText(f"{verb} {self.file_list.files[row].name}")

    @Slot(int, float, str)
    def _on_progress(self, row: int, fraction: float, message: str) -> None:
        self.file_list.set_status(row, f"{int(fraction * 100)}% {message}")
        self._set_overall(fraction)

    @Slot(int, list, list)
    def _on_done(self, row: int, outputs: list, notes: list) -> None:
        self._done_count += 1
        self._set_overall(0)
        text = f"✓ {Path(outputs[0]).name}" if len(outputs) == 1 else f"✓ {len(outputs)} files"
        self.file_list.set_status(
            row,
            text,
            tooltip="\n".join([*outputs, *notes]),
            output=outputs[0] if outputs else None,
        )
        if outputs:
            self.last_output = Path(outputs[0]).parent

    @Slot(int, str)
    def _on_failed(self, row: int, message: str) -> None:
        self._done_count += 1
        self._set_overall(0)
        self.file_list.set_status(row, f"✗ {message}", tooltip=message)

    @Slot(bool)
    def _on_finished(self, cancelled: bool) -> None:
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait()
            self._thread.deleteLater()
        self._thread = None
        self._worker = None
        self.convert_btn.setVisible(True)
        self.cancel_btn.setVisible(False)
        self.open_btn.setEnabled(self.last_output is not None)
        self.status_label.setText("Cancelled" if cancelled else "Finished")
        if not cancelled:
            self.progress.setValue(1000)
        self._refresh()

    def _open_output_folder(self) -> None:
        if self.last_output is not None:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.last_output)))

    # --- preferences and about ------------------------------------------------

    def _load_preferences(self) -> None:
        self.options.load(self.prefs)
        if self.prefs.output_dir is not None:
            self.output_dir = self.prefs.output_dir

    def _remembered_target(self) -> str | None:
        category = targets.single_category(self.file_list.formats)
        return self.prefs.target_for(category) if category else None

    def save_preferences(self) -> None:
        self.prefs.save(
            output_dir=self.output_dir,
            level=self.options.level(),
            use_word=self.options.use_word(self.prefs.use_word),
            keep_metadata=self.options.metadata_check.isChecked(),
        )

    def show_about(self) -> None:
        AboutDialog(self).exec()

    def closeEvent(self, event) -> None:
        if self._thread is not None:
            answer = QMessageBox.question(
                self, "Conversion running", "A conversion is still running. Stop it and quit?"
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self._cancel.set()
            self._thread.quit()
            self._thread.wait(5000)
        self.save_preferences()
        event.accept()
