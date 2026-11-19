"""Main window: a sidebar with Convert, Supported formats and Settings, and the pages.

The window puts the parts together and runs a conversion. The parts live in their own
modules: ``convert_page`` (layout of the Convert page), ``file_list``, ``target_picker``,
``options_panel`` (quality), ``output_folder``, ``formats_panel``, ``settings_page``,
``targets`` (which targets are offered, without Qt), ``worker`` (the background thread)
and ``theme`` (light / dark / follow Windows).
"""

from __future__ import annotations

import threading
from pathlib import Path

from PySide6.QtCore import Qt, QThread, QUrl, Slot
from PySide6.QtGui import QDesktopServices, QDragEnterEvent, QDropEvent, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .. import __version__
from ..converters import all_converters
from ..converters.msword import word_installed
from ..engine import Engine
from . import icons, targets, theme
from .about import AboutDialog
from .convert_page import ConvertPage
from .file_list import DONE, FAILED, WAITING
from .formats_panel import FormatsPanel
from .resources import icon_path
from .settings import Preferences
from .settings_page import SettingsPage
from .targets import CLEAN_TARGET, display_name
from .widgets import label
from .worker import ConversionWorker

PAGES = [("convert", "Convert", "convert"), ("formats", "Supported formats", "formats"),
         ("settings", "Settings", "settings")]  # fmt: skip


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
        self.resize(1120, 760)
        self.setMinimumSize(960, 620)
        self.setAcceptDrops(True)
        self.theme = theme.manager(QApplication.instance(), self.prefs.theme)
        self._build_ui()
        self.theme.changed.connect(self._apply_colors)
        self._apply_colors(self.theme.colors)
        self._load_preferences()
        self._refresh()

    # --- layout -------------------------------------------------------------

    def _build_ui(self) -> None:
        banners = [c.unavailable_reason() for c in self.engine.unavailable()]
        self.convert_page = ConvertPage(banners)
        page = self.convert_page
        self.file_list = page.file_list
        self.target_picker = page.target_picker
        self.quality = page.quality
        self.output_row = page.output_row
        self.notes_label = page.notes_label
        self.status_label = page.status_label
        self.progress = page.progress
        self.open_btn = page.open_btn
        self.convert_btn = page.convert_btn
        self.cancel_btn = page.cancel_btn
        self.file_list.changed.connect(self._refresh)
        self.target_picker.changed.connect(lambda _target: self._update_notes())
        self.open_btn.clicked.connect(self._open_output_folder)
        self.cancel_btn.clicked.connect(self._cancel_conversion)
        self.convert_btn.clicked.connect(self.start_conversion)

        libreoffice_installed = not any(c.id == "libreoffice" for c in self.engine.unavailable())
        self.formats_panel = FormatsPanel(libreoffice_installed)
        self.settings_page = SettingsPage(
            word_installed=word_installed(),
            use_word=self.engine.uses_word(),
            theme_choice=self.prefs.theme,
        )
        self.settings_page.theme_changed.connect(self.set_theme)
        self.settings_page.use_word_changed.connect(self._set_use_word)
        self.settings_page.about_requested.connect(self.show_about)
        self.about_btn = self.settings_page.about_btn

        self.pages = QStackedWidget()
        self._page_index = {}
        for key, widget in (
            ("convert", self.convert_page),
            ("formats", self.formats_panel),
            ("settings", self.settings_page),
        ):
            self._page_index[key] = self.pages.addWidget(widget)
        content = QFrame()
        content.setObjectName("Content")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.addWidget(self.pages)

        root = QWidget()
        root.setFocusPolicy(Qt.FocusPolicy.ClickFocus)  # holds the focus at start, no ring shown
        self._root = root
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._sidebar())
        layout.addWidget(content, 1)
        self.setCentralWidget(root)

    def _sidebar(self) -> QWidget:
        sidebar = QWidget()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(224)
        column = QVBoxLayout(sidebar)
        column.setContentsMargins(10, 4, 10, 14)
        column.setSpacing(4)

        brand = QHBoxLayout()
        brand.setContentsMargins(8, 4, 0, 14)
        brand.setSpacing(10)
        logo = QLabel()
        logo.setPixmap(QPixmap(str(icon_path())).scaled(
            28, 28, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
        ))  # fmt: skip
        brand.addWidget(logo)
        brand.addWidget(label("Azoth Converter", "brand"), 1)
        column.addLayout(brand)

        self.nav_group = QButtonGroup(self)
        self.nav_buttons: dict[str, QPushButton] = {}
        for key, text, _icon in PAGES:
            button = QPushButton(text)
            button.setProperty("role", "nav")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setFocusPolicy(Qt.FocusPolicy.TabFocus)  # focus ring only from the keyboard
            button.clicked.connect(lambda _=False, k=key: self.show_page(k))
            self.nav_group.addButton(button)
            self.nav_buttons[key] = button
            column.addWidget(button)
        self.nav_buttons["convert"].setChecked(True)
        column.addStretch(1)

        self.offline_label = label(
            "Works offline. Your files never leave this computer.", "offline", wrap=True
        )
        column.addWidget(self.offline_label)
        return sidebar

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not getattr(self, "_shown", False):
            self._shown = True
            self._root.setFocus()

    def show_page(self, key: str) -> None:
        self.pages.setCurrentIndex(self._page_index[key])
        self.nav_buttons[key].setChecked(True)
        self._apply_colors(self.theme.colors)

    def current_page(self) -> str:
        index = self.pages.currentIndex()
        return next(k for k, i in self._page_index.items() if i == index)

    # --- look -------------------------------------------------------------------

    def set_theme(self, choice: str) -> None:
        """ "system" (follow Windows), "light" or "dark"; saved right away."""
        self.theme.set_choice(choice)
        self.settings_page.set_theme_choice(choice)
        self.prefs.save_theme(choice)

    def _apply_colors(self, colors: theme.Colors) -> None:
        for key, _text, icon_name in PAGES:
            button = self.nav_buttons[key]
            button.setIcon(
                icons.icon(icon_name, colors.accent if button.isChecked() else colors.muted)
            )
        self.convert_page.apply_colors(colors)

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
            self.convert_page.set_drop_active(True)

    def dragLeaveEvent(self, event) -> None:
        self.convert_page.set_drop_active(False)

    def dropEvent(self, event: QDropEvent) -> None:
        self.convert_page.set_drop_active(False)
        self.show_page("convert")
        self.add_files(u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile())

    # --- target formats -------------------------------------------------------

    def _refresh(self) -> None:
        file_formats = self.file_list.formats
        choices = targets.choices(self.engine, file_formats)
        self.target_picker.set_choices(
            choices, keep=[self.target_picker.current(), self._remembered_target()]
        )
        if targets.source_formats(file_formats) and not choices:
            self.notes_label.setText(targets.NO_COMMON_TARGET)
            self.notes_label.setVisible(True)
        else:
            self._update_notes()
        busy = self._thread is not None
        self.file_list.set_busy(busy)
        self.output_row.set_busy(busy)
        self.target_picker.set_busy(busy)
        self.quality.set_busy(busy)
        count = self.file_list.count()
        self.convert_page.subtitle.setText(
            f"{count} file{'s' if count != 1 else ''} · drop more anywhere in this window"
            if count
            else "Add photos, PDFs or office files to get started."
        )
        self._update_action()

    def _jobs_for(self, target: str | None) -> int:
        return sum(1 for f in self.file_list.formats if f is not None and f.id != target)

    def _update_action(self) -> None:
        target = self.target_picker.current()
        busy = self._thread is not None
        count = self._jobs_for(target) if target else 0
        files = f"{count} file{'s' if count != 1 else ''}"
        if target == CLEAN_TARGET:
            text = f"Remove metadata from {files}"
        elif target:
            text = f"Convert {files} to {display_name(target)}"
        else:
            text = "Convert"
        self.convert_btn.setText(text)
        self.convert_btn.setEnabled(bool(target) and count > 0 and not busy)

    def _update_notes(self) -> None:
        target = self.target_picker.current()
        self.settings_page.metadata_check.setEnabled(target != CLEAN_TARGET)
        notes = targets.notes(self.engine, self.file_list.formats, target)
        self.notes_label.setText("\n".join(notes))
        self.notes_label.setVisible(bool(notes))
        self._update_action()

    def _set_use_word(self, use_word: bool) -> None:
        self.engine = Engine(all_converters(use_word=use_word))
        self._update_notes()

    def set_quality_level(self, level_id: str) -> None:
        self.quality.set_level(level_id)

    # --- conversion -----------------------------------------------------------

    def start_conversion(self) -> None:
        target = self.target_picker.current()
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
                self.file_list.set_status(row, "Waiting", state=WAITING)
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
        self.progress.setVisible(True)
        self.open_btn.setVisible(False)
        options = {
            "level": self.quality.level(),
            "keep_metadata": self.settings_page.metadata_check.isChecked(),
        }
        self._thread = QThread(self)
        self._worker = ConversionWorker(
            self.engine, jobs, target, self.output_dir, options, self._cancel
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
        self.file_list.set_progress(row, 0.0, "Working…")
        self.status_label.setText(f"{verb} {self.file_list.files[row].name}")

    @Slot(int, float, str)
    def _on_progress(self, row: int, fraction: float, message: str) -> None:
        self.file_list.set_progress(row, fraction, message)
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
            state=DONE,
        )
        if outputs:
            self.last_output = Path(outputs[0]).parent

    @Slot(int, str)
    def _on_failed(self, row: int, message: str) -> None:
        self._done_count += 1
        self._set_overall(0)
        self.file_list.set_status(row, f"✗ {message}", tooltip=message, state=FAILED)

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
        self.open_btn.setVisible(self.last_output is not None)
        self.status_label.setText("Cancelled" if cancelled else "Finished")
        if not cancelled:
            self.progress.setValue(1000)
        self._refresh()

    def _open_output_folder(self) -> None:
        if self.last_output is not None:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.last_output)))

    # --- preferences and about ------------------------------------------------

    def _load_preferences(self) -> None:
        self.quality.set_level(self.prefs.level)
        self.settings_page.metadata_check.setChecked(self.prefs.keep_metadata)
        if self.prefs.output_dir is not None:
            self.output_dir = self.prefs.output_dir

    def _remembered_target(self) -> str | None:
        category = targets.single_category(self.file_list.formats)
        return self.prefs.target_for(category) if category else None

    def save_preferences(self) -> None:
        self.prefs.save(
            output_dir=self.output_dir,
            level=self.quality.level(),
            use_word=self.settings_page.use_word(self.prefs.use_word),
            keep_metadata=self.settings_page.metadata_check.isChecked(),
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
