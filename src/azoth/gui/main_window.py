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

from PySide6.QtCore import Qt, QThread, Signal, Slot
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .. import __version__, formats, resize
from ..converters import ConversionError, all_converters
from ..converters.msword import office_installed
from ..engine import Engine
from . import icons, targets, theme
from .about import AboutDialog
from .convert_page import ConvertPage
from .done_card import Notifier, done_message
from .file_list import DONE, FAILED, WAITING
from .formats_panel import FormatsPanel
from .pdf_tools_page import PasswordPage, PdfToolsPage
from .settings import Preferences
from .settings_page import SettingsPage
from .targets import CLEAN_TARGET, RESIZE_TARGET, display_name
from .widgets import label
from .worker import ConversionWorker

PAGES = [  # (key, text in the sidebar, icon)
    ("convert", "Convert", "convert"),
    ("pdf", "PDF tools", "pdf"),
    ("password", "Password", "lock"),
    ("formats", "Supported formats", "formats"),
    ("settings", "Settings", "settings"),
]


class MainWindow(QMainWindow):
    batch_finished = Signal()  # a conversion batch ended (done, failed or cancelled)

    def __init__(self, engine: Engine | None = None, prefs: Preferences | None = None) -> None:
        super().__init__()
        self.prefs = prefs or Preferences()
        self.engine = engine or Engine(all_converters(use_word=self.prefs.use_word))
        self.last_output: Path | None = None  # set only when all results share one folder
        self._output_folders: set[Path] = set()
        self._thread: QThread | None = None
        self._worker: ConversionWorker | None = None
        self._cancel = threading.Event()
        self._done_count = 0
        self._running: dict[int, float] = {}  # row → progress of files being converted
        self._job_count = 0
        self._outputs: list[Path] = []
        self._failed = 0

        self.setWindowTitle(f"Azoth Converter {__version__}")
        self.resize(1120, 760)
        self.setMinimumSize(960, 620)
        self.setAcceptDrops(True)
        self.theme = theme.manager(QApplication.instance(), self.prefs.theme)
        self.notifier = Notifier(self)
        self._build_ui()
        self.theme.changed.connect(self._apply_colors)
        self._apply_colors(self.theme.colors)
        self._load_preferences()
        self._refresh()

    # --- layout -------------------------------------------------------------

    def _build_ui(self) -> None:
        banners = [
            (_reason(c, missing), f"Download {c.label}…", c.download_url)
            for c, missing in self.engine.needed_engines()
        ]
        self.convert_page = ConvertPage(banners)
        page = self.convert_page
        self.file_list = page.file_list
        self.target_picker = page.target_picker
        self.quality = page.quality
        self.ocr_options = page.ocr
        self.resize_options = page.resize
        self.output_row = page.output_row
        self.name_row = page.name_row
        self.notes_label = page.notes_label
        self.status_label = page.status_label
        self.progress = page.progress
        self.done_card = page.done_card
        self.convert_btn = page.convert_btn
        self.cancel_btn = page.cancel_btn
        self.file_list.changed.connect(self._files_changed)
        self.target_picker.changed.connect(lambda _target: self._update_notes())
        self.resize_options.changed.connect(self._update_action)
        self.cancel_btn.clicked.connect(self._cancel_conversion)
        self.convert_btn.clicked.connect(self.start_conversion)

        self.pdf_page = PdfToolsPage()
        self.password_page = PasswordPage()
        libreoffice_installed = not any(c.id == "libreoffice" for c in self.engine.unavailable())
        self.formats_panel = FormatsPanel(
            libreoffice_installed,
            can_convert=lambda s, d: self.engine.find_route(s, d) is not None,
        )
        self.settings_page = SettingsPage(
            word_installed=bool(office_installed()),
            use_word=self.engine.uses_word(),
            theme_choice=self.prefs.theme,
        )
        self.settings_page.theme_changed.connect(self.set_theme)
        self.settings_page.use_word_changed.connect(self._set_use_word)
        self.settings_page.notify_check.toggled.connect(self._set_notify)
        self.settings_page.turn_check.toggled.connect(self.prefs.save_ocr_turn_pages)
        for tools_page in (self.pdf_page, self.password_page):
            tools_page.task.done.connect(
                lambda outputs: (
                    self.notifier.notify(f"Done! {Path(outputs[0]).name} is ready.")
                    if len(outputs) == 1
                    else self.notifier.notify(f"Done! {len(outputs)} PDFs saved.")
                )
            )
        self.settings_page.about_requested.connect(self.show_about)
        self.about_btn = self.settings_page.about_btn

        self.pages = QStackedWidget()
        self._page_index = {}
        for key, widget in (
            ("convert", self.convert_page),
            ("pdf", self.pdf_page),
            ("password", self.password_page),
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
        self.pdf_page.apply_colors(colors)

    # --- files ------------------------------------------------------------------

    def add_files(self, paths) -> None:
        self.file_list.add_files(paths)

    def is_busy(self) -> bool:
        return self._thread is not None

    def run_explorer_request(self, target: str, paths: list[Path]) -> None:
        """Files chosen in Explorer's right-click menu: show them and, if a target was
        chosen there, convert them to it right away (see explorer.py)."""
        if self.is_busy():
            return
        from .explorer import OPEN

        found = [p for p in paths if p.is_file()]
        self.show_page("convert")
        self.done_card.clear()
        if target == OPEN and found:  # "Open in …": join the files already in the list
            self.add_files(found)
            return
        self.file_list.clear()
        self.add_files(found)
        if not self.file_list.files:
            self.status_label.setText("The chosen files can't be found any more.")
            return
        if target == OPEN:
            return
        if self.target_picker.select(target):
            self.start_conversion()
        else:
            self.status_label.setText("Choose what to convert these files to.")

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
        paths = [u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]
        if self.current_page() == "pdf":
            self.pdf_page.add_files(paths)  # goes to the PDF tool that is open
            return
        if self.current_page() == "password":
            self.password_page.add_files(paths)
            return
        self.show_page("convert")
        self.add_files(paths)

    # --- target formats -------------------------------------------------------

    def _files_changed(self) -> None:
        """Files added or removed: the result of the last run no longer matches the list."""
        if self._thread is None:
            self.status_label.setText("")
            self.progress.setVisible(False)
            self.done_card.clear()
        self._refresh()

    def _refresh(self) -> None:
        file_formats = self.file_list.formats
        self.name_row.set_sources(self.file_list.files)
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
        self.name_row.set_busy(busy)
        self.target_picker.set_busy(busy)
        self.quality.set_busy(busy)
        self.ocr_options.set_busy(busy)
        self.resize_options.set_busy(busy)
        count = self.file_list.count()
        self.convert_page.subtitle.setText(
            f"{count} file{'s' if count != 1 else ''} · drop more anywhere in this window"
            if count
            else "Add photos, PDFs or office files to get started."
        )
        self._update_action()

    def _resize_spec(self):
        """The chosen picture size, or None (no new size, or the choice isn't shown)."""
        return self.resize_options.spec() if not self.resize_options.isHidden() else None

    def _jobs_for(self, target: str | None) -> list[int]:
        resizing = self._resize_spec() is not None
        return targets.jobs(self.file_list.formats, target, resizing)

    def _update_action(self) -> None:
        target = self.target_picker.current()
        busy = self._thread is not None
        count = len(self._jobs_for(target))
        files = f"{count} file{'s' if count != 1 else ''}"
        if target == CLEAN_TARGET:
            text = f"Remove metadata from {files}"
        elif target == RESIZE_TARGET and self.resize_options.mode.currentData() is None:
            text = f"Enhance {files}" if count else "Choose a new size"
        elif target == RESIZE_TARGET:
            text = f"Resize {files}" if count else "Choose a new size"
        elif target:
            text = f"Convert {files} to {display_name(target)}"
        else:
            text = "Convert"
        self.convert_btn.setText(text)
        self.convert_btn.setEnabled(bool(target) and count > 0 and not busy)

    def _update_notes(self) -> None:
        target = self.target_picker.current()
        self.name_row.set_extension(self._result_extension(target))
        self.settings_page.metadata_check.setEnabled(target != CLEAN_TARGET)
        self.ocr_options.set_mode(targets.ocr_mode(self.file_list.formats, target))
        resizable = targets.can_resize(self.engine, self.file_list.formats, target)
        if target == RESIZE_TARGET and self.resize_options.spec() is None:
            self.resize_options.set_mode(resize.FIT)  # this tile is about a new size
        self.resize_options.setVisible(resizable)
        self.quality.setVisible(targets.uses_quality(self.file_list.formats, target))
        notes = targets.notes(self.engine, self.file_list.formats, target)
        self.notes_label.setText("\n".join(notes))
        self.notes_label.setVisible(bool(notes))
        self._update_action()

    def _result_extension(self, target: str | None) -> str:
        if target in (CLEAN_TARGET, RESIZE_TARGET):
            files = self.file_list.files
            return files[0].suffix.lstrip(".") if len(files) == 1 else ""
        return formats.FORMATS[target].extension if target in formats.FORMATS else ""

    def _set_use_word(self, use_word: bool) -> None:
        self.engine = Engine(all_converters(use_word=use_word))
        self._update_notes()

    def _office_passwords(self, jobs: list) -> dict[str, str]:
        """Ask for the password of each protected Word, Excel or PowerPoint file in
        ``jobs``. Files whose password isn't given are taken out of ``jobs``. The
        passwords are only kept for this run, never saved."""
        from .. import office_password

        passwords: dict[str, str] = {}
        for job in list(jobs):
            row, path, _target = job
            if not office_password.is_protected(path):
                continue
            password = self.ask_password(Path(path))
            if password is None:
                jobs.remove(job)
                self.file_list.set_status(row, "Skipped: no password entered")
            else:
                passwords[str(path)] = password
        return passwords

    def ask_password(self, path: Path) -> str | None:
        """The password of a protected Office file, checked; None if the user cancels."""
        from PySide6.QtWidgets import QInputDialog, QLineEdit

        from .. import office_password

        message = (
            f"{path.name} is protected with a password. Enter it to convert the file.\n"
            "The password isn't saved, and the converted file won't have one."
        )
        while True:
            password, ok = QInputDialog.getText(
                self, "Password needed", message, QLineEdit.EchoMode.Password
            )
            if not ok:
                return None
            try:
                office_password.decrypt(path, password)
            except ConversionError as exc:
                message = f"{exc}\nTry again, or press Cancel to skip this file."
                continue
            return password

    def set_quality_level(self, level_id: str) -> None:
        self.quality.set_level(level_id)

    # --- conversion -----------------------------------------------------------

    def start_conversion(self) -> None:
        target = self.target_picker.current()
        if not target or self._thread is not None:
            return
        size = self._resize_spec()
        if target == RESIZE_TARGET and size is None:
            return
        to_convert = set(self._jobs_for(target))
        jobs = []
        for row, (path, fmt) in enumerate(
            zip(self.file_list.files, self.file_list.formats, strict=True)
        ):
            if fmt is None:
                self.file_list.set_status(row, "Skipped: unknown file type")
            elif row not in to_convert:
                self.file_list.set_status(row, "Skipped: already this format")
            else:
                self.file_list.set_status(row, "Waiting", state=WAITING)
                jobs.append((row, path, targets.job_target(target, fmt)))
        passwords = self._office_passwords(jobs)
        if not jobs:
            return
        category = targets.single_category(self.file_list.formats)
        if category is not None:
            self.prefs.save_target(category, target)
        self.save_preferences()

        self._cancel = threading.Event()
        self._done_count = 0
        self._running: dict[int, float] = {}  # row → progress of files being converted
        self._job_count = len(jobs)
        self.progress.setValue(0)
        self.progress.setVisible(True)
        self.done_card.clear()
        self._outputs = []
        self._failed = 0
        self._output_folders.clear()
        self.last_output = None
        options = {
            "level": self.quality.level(),
            "keep_metadata": self.settings_page.metadata_check.isChecked(),
            "resize": size,
            "passwords": passwords,
            **self.ocr_options.options(),
            "ocr_turn_pages": self.settings_page.turn_check.isChecked(),
        }
        self._thread = QThread(self)
        self._worker = ConversionWorker(
            self.engine,
            jobs,
            target,
            self.output_dir,
            options,
            self._cancel,
            name=self.name_row.custom_name() if len(jobs) == 1 else None,
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

    def _set_overall(self) -> None:
        # several files can be converted at the same time (photos): add them all up
        overall = (self._done_count + sum(self._running.values())) / max(self._job_count, 1)
        self.progress.setValue(int(overall * 1000))

    @Slot(int)
    def _on_started(self, row: int) -> None:
        verb = {CLEAN_TARGET: "Removing metadata from", RESIZE_TARGET: "Resizing"}.get(
            self._worker.target if self._worker is not None else "", "Converting"
        )
        self.file_list.set_progress(row, 0.0, "Working…")
        self.status_label.setText(f"{verb} {self.file_list.files[row].name}")

    @Slot(int, float, str)
    def _on_progress(self, row: int, fraction: float, message: str) -> None:
        self.file_list.set_progress(row, fraction, message)
        self._running[row] = max(0.0, min(1.0, fraction))
        self._set_overall()

    @Slot(int, list, list)
    def _on_done(self, row: int, outputs: list, notes: list) -> None:
        self._done_count += 1
        self._running.pop(row, None)
        self._set_overall()
        text = f"✓ {Path(outputs[0]).name}" if len(outputs) == 1 else f"✓ {len(outputs)} files"
        new_size = next((n for n in notes if n.startswith("New size: ")), None)
        if new_size:  # "✓ photo (resized).jpg · 2500 × 1875 px"
            text += " · " + new_size.removeprefix("New size: ").split(" (")[0]
        warnings = [n for n in notes if n.startswith("⚠")]
        if warnings:  # e.g. "⚠ Word failed, LibreOffice was used": details in the tooltip
            text += "  " + warnings[0].split(" (")[0].split(". ")[0]
        self.file_list.set_status(
            row,
            text,
            tooltip="\n".join([*outputs, *notes]),
            output=outputs[0] if outputs else None,
            state=DONE,
        )
        self._output_folders.update(Path(p).parent for p in outputs)
        self._outputs.extend(Path(p) for p in outputs)

    @Slot(int, str)
    def _on_failed(self, row: int, message: str) -> None:
        self._done_count += 1
        self._running.pop(row, None)
        self._failed += 1
        self._set_overall()
        self.file_list.set_status(row, f"✗ {message}", tooltip=message, state=FAILED)

    @Slot(bool)
    def _on_finished(self, cancelled: bool) -> None:
        kind = self._worker.target if self._worker is not None else None
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait()
            self._thread.deleteLater()
        self._thread = None
        self._worker = None
        self.convert_btn.setVisible(True)
        self.cancel_btn.setVisible(False)
        # One button for the whole batch only makes sense when all results are in one folder;
        # otherwise each file has its own "Show in folder".
        self.last_output = (
            next(iter(self._output_folders)) if len(self._output_folders) == 1 else None
        )
        converted = self._done_count - self._failed
        text = done_message(
            converted,
            self._failed,
            cancelled,
            cleaning=kind == CLEAN_TARGET,
            resizing=kind == RESIZE_TARGET,
            enhancing=kind == RESIZE_TARGET and self.resize_options.mode.currentData() is None,
        )
        self.status_label.setText("")
        self.done_card.show_result(
            text,
            ok=not self._failed and not cancelled,
            file=self._outputs[0] if len(self._outputs) == 1 else None,
            folder=self.last_output,
        )
        if not cancelled:
            self.notifier.notify(text)
        if not cancelled:
            self.progress.setValue(1000)
        self._refresh()
        self.batch_finished.emit()

    # --- preferences and about ------------------------------------------------

    def _set_notify(self, on: bool) -> None:
        self.notifier.enabled = on
        self.prefs.save_notify(on)

    def _load_preferences(self) -> None:
        self.settings_page.notify_check.setChecked(self.prefs.notify)
        self.settings_page.turn_check.setChecked(self.prefs.ocr_turn_pages)
        self.notifier.enabled = self.prefs.notify
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


def _reason(converter, missing) -> str:
    """The banner text for a missing engine, naming only what really needs it."""
    try:
        return converter.unavailable_reason(missing)
    except TypeError:  # engines without the detail
        return converter.unavailable_reason()
