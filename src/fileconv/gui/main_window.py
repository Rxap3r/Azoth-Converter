"""Main window: drop files, choose a format, convert."""

from __future__ import annotations

import threading
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QThread, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices, QDragEnterEvent, QDropEvent, QIcon
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .. import __version__, formats, quality, ranking
from ..converters import ConversionCancelled, ConversionError, all_converters
from ..converters.msword import word_installed
from ..engine import Engine
from .about import AboutDialog
from .formats_panel import FormatsPanel
from .resources import icon_path
from .settings import Preferences
from .widgets import CollapsibleSection

COL_FILE, COL_TYPE, COL_STATUS = range(3)
SAME_FOLDER = "Same folder as the original"


class ConversionWorker(QObject):
    """Converts the files one after another in a background thread."""

    file_started = Signal(int)
    file_progress = Signal(int, float, str)
    file_done = Signal(int, list, list)
    file_failed = Signal(int, str)
    finished = Signal(bool)

    def __init__(self, engine, jobs, target, output_dir, options, cancel_event):
        super().__init__()
        self.engine = engine
        self.jobs = jobs  # list of (row, path)
        self.target = target
        self.output_dir = output_dir
        self.options = options
        self.cancel_event = cancel_event

    @Slot()
    def run(self) -> None:
        for row, path in self.jobs:
            if self.cancel_event.is_set():
                break
            self.file_started.emit(row)
            try:
                result = self.engine.convert(
                    path,
                    self.target,
                    self.output_dir,
                    options=self.options,
                    progress=lambda f, m, r=row: self.file_progress.emit(r, f, m),
                    cancel_event=self.cancel_event,
                )
            except ConversionCancelled:
                self.file_failed.emit(row, "Cancelled")
                break
            except ConversionError as exc:
                self.file_failed.emit(row, str(exc))
            except Exception as exc:  # never let one bad file kill the app
                self.file_failed.emit(row, f"Unexpected error: {exc}")
            else:
                self.file_done.emit(row, [str(p) for p in result.outputs], result.notes)
        self.finished.emit(self.cancel_event.is_set())


class MainWindow(QMainWindow):
    def __init__(self, engine: Engine | None = None, prefs: Preferences | None = None) -> None:
        super().__init__()
        self.prefs = prefs or Preferences()
        self.engine = engine or Engine(all_converters(use_word=self.prefs.use_word))
        self._word_installed = word_installed()
        self.files: list[Path] = []
        self.file_formats: list[formats.Format | None] = []
        self.output_dir: Path | None = None
        self.last_output: Path | None = None
        self._thread: QThread | None = None
        self._worker: ConversionWorker | None = None
        self._cancel = threading.Event()
        self._done_count = 0

        self.setWindowTitle(f"File-Converter {__version__}")
        self.resize(820, 600)
        self.setAcceptDrops(True)
        self._build_ui()
        self._load_preferences()
        self._refresh()

    # --- layout -------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QWidget()
        layout = QVBoxLayout(root)

        header = QHBoxLayout()
        logo = QLabel()
        logo.setPixmap(QIcon(str(icon_path())).pixmap(40, 40))
        header.addWidget(logo)
        titles = QVBoxLayout()
        titles.setSpacing(0)
        title = QLabel("<h2 style='margin:0'>File-Converter</h2>")
        subtitle = QLabel("🔒 Works offline. Your files never leave this computer.")
        subtitle.setStyleSheet("color: palette(placeholder-text);")
        titles.addWidget(title)
        titles.addWidget(subtitle)
        header.addLayout(titles, 1)
        self.about_btn = QPushButton("About")
        self.about_btn.clicked.connect(self.show_about)
        header.addWidget(self.about_btn, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(header)

        for conv in self.engine.unavailable():
            banner = QLabel(f"⚠ {conv.unavailable_reason()}")
            banner.setWordWrap(True)
            banner.setStyleSheet(
                "background:#fff4ce; color:#5c4400; padding:8px; border-radius:4px;"
            )
            layout.addWidget(banner)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["File", "Type", "Status"])
        self.tree.setRootIsDecorated(False)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        header = self.tree.header()
        header.setSectionResizeMode(COL_FILE, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(COL_TYPE, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(COL_STATUS, QHeaderView.ResizeMode.Stretch)
        self.tree.itemDoubleClicked.connect(self._open_item_output)
        self.drop_hint = QLabel("Drag files here, or click “Add files…”")
        self.drop_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.drop_hint.setStyleSheet(
            "border: 2px dashed palette(mid); border-radius: 8px; padding: 40px; font-size: 14px;"
        )
        layout.addWidget(self.drop_hint, 1)  # takes the free space while the list is empty
        layout.addWidget(self.tree, 1)

        buttons = QHBoxLayout()
        self.add_btn = QPushButton("Add files…")
        self.add_btn.clicked.connect(self._choose_files)
        self.remove_btn = QPushButton("Remove selected")
        self.remove_btn.clicked.connect(self._remove_selected)
        self.clear_btn = QPushButton("Clear list")
        self.clear_btn.clicked.connect(self._clear)
        buttons.addWidget(self.add_btn)
        buttons.addWidget(self.remove_btn)
        buttons.addWidget(self.clear_btn)
        buttons.addStretch()
        layout.addLayout(buttons)

        form = QFormLayout()
        self.target_combo = QComboBox()
        self.target_combo.currentIndexChanged.connect(self._update_notes)
        form.addRow("Convert to:", self.target_combo)

        out_row = QHBoxLayout()
        self.output_label = QLabel(SAME_FOLDER)
        self.output_btn = QPushButton("Choose folder…")
        self.output_btn.clicked.connect(self._choose_output)
        self.output_reset_btn = QPushButton("Reset")
        self.output_reset_btn.clicked.connect(self._reset_output)
        out_row.addWidget(self.output_label, 1)
        out_row.addWidget(self.output_btn)
        out_row.addWidget(self.output_reset_btn)
        form.addRow("Save to:", out_row)
        layout.addLayout(form)

        options = QWidget()
        opt_form = QFormLayout(options)
        opt_form.setContentsMargins(16, 0, 0, 0)
        self.metadata_check = QCheckBox("Keep photo metadata (camera, date, GPS location)")
        self.level_combo = QComboBox()
        for level in quality.LEVELS:
            self.level_combo.addItem(level.label, level.id)
        self.level_hint = QLabel()
        self.level_hint.setWordWrap(True)
        self.level_hint.setStyleSheet("color: palette(placeholder-text);")
        self.level_combo.currentIndexChanged.connect(self._update_level_hint)
        self._update_level_hint()
        opt_form.addRow("Quality:", self.level_combo)
        opt_form.addRow("", self.level_hint)
        opt_form.addRow(self.metadata_check)
        self.word_check = QCheckBox("Use Microsoft Word for Word → PDF (exact layout and fonts)")
        self.word_check.setToolTip(
            "Word converts the file on this computer; nothing is uploaded.\n"
            "Macros stay off. If Word fails, LibreOffice is used instead."
        )
        self.word_check.setChecked(self.engine.uses_word())
        self.word_check.setVisible(self._word_installed)  # only when Word is installed
        self.word_check.toggled.connect(self._set_use_word)
        opt_form.addRow(self.word_check)
        self.options_section = CollapsibleSection("Options", options)
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
        layout.addLayout(actions)

        self.setCentralWidget(root)

    # --- file list ------------------------------------------------------------

    def add_files(self, paths) -> None:
        known = {p.resolve() for p in self.files}
        for raw in paths:
            path = Path(raw)
            if path.is_dir():
                self.add_files(sorted(p for p in path.iterdir() if p.is_file()))
                continue
            if not path.is_file() or path.resolve() in known:
                continue
            fmt = formats.detect(path)
            item = QTreeWidgetItem([path.name, fmt.id.upper() if fmt else "?", ""])
            item.setToolTip(COL_FILE, str(path))
            if fmt is None:
                item.setText(COL_STATUS, "Unknown file type, will be skipped")
            self.tree.addTopLevelItem(item)
            self.files.append(path)
            self.file_formats.append(fmt)
            known.add(path.resolve())
        self._refresh()

    def _choose_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "Choose files to convert")
        self.add_files(paths)

    def _remove_selected(self) -> None:
        rows = sorted(
            (self.tree.indexOfTopLevelItem(i) for i in self.tree.selectedItems()), reverse=True
        )
        for row in rows:
            self.tree.takeTopLevelItem(row)
            del self.files[row]
            del self.file_formats[row]
        self._refresh()

    def _clear(self) -> None:
        self.tree.clear()
        self.files.clear()
        self.file_formats.clear()
        self._refresh()

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls() and self._thread is None:
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        self.add_files(u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile())

    # --- target formats -------------------------------------------------------

    def _source_formats(self) -> list[str]:
        ids: list[str] = []
        for fmt in self.file_formats:
            if fmt is not None and fmt.id not in ids:
                ids.append(fmt.id)
        return ids

    def _refresh(self) -> None:
        has_files = bool(self.files)
        self.drop_hint.setVisible(not has_files)
        self.tree.setVisible(has_files)

        previous = self.target_combo.currentData()
        self.target_combo.blockSignals(True)
        self.target_combo.clear()
        sources = self._source_formats()
        # A file that already has the target format is simply skipped, so a target
        # is offered if every file either converts to it or already is it, and at
        # least one file actually needs converting.
        common: list[formats.Format] = []
        if sources:
            allowed = [{t.id for t in self.engine.targets_for(s)} | {s} for s in sources]
            for fmt in formats.FORMATS.values():
                if all(fmt.id in a for a in allowed) and sources != [fmt.id]:
                    common.append(fmt)
            categories = [f.category for f in self.file_formats if f is not None]
            common = ranking.rank(common, categories)  # most useful first
        for fmt in common:
            self.target_combo.addItem(f"{fmt.name} (.{fmt.extension})", fmt.id)
        # Keep the current choice or the remembered one; otherwise the list is ordered
        # by usefulness, so its first entry (e.g. Word for a PDF) is the default.
        self.target_combo.setCurrentIndex(0)
        for wanted in (previous, self._remembered_target()):
            index = self.target_combo.findData(wanted) if wanted else -1
            if index >= 0:
                self.target_combo.setCurrentIndex(index)
                break
        self.target_combo.blockSignals(False)

        if sources and not common:
            self.notes_label.setText(
                "These files have no target format in common. Convert them in separate groups."
            )
        else:
            self._update_notes()
        busy = self._thread is not None
        self.convert_btn.setEnabled(has_files and self.target_combo.count() > 0 and not busy)
        for w in (
            self.add_btn,
            self.remove_btn,
            self.clear_btn,
            self.target_combo,
            self.output_btn,
            self.output_reset_btn,
        ):
            w.setEnabled(not busy)

    def _update_level_hint(self) -> None:
        level = quality.BY_ID[self.level_combo.currentData()]
        self.level_hint.setText(
            f"{level.description} Photos: quality {level.image_quality} · "
            f"PDF pages as images: {level.dpi} DPI. Word/Excel/PowerPoint → PDF and "
            "image → PDF always keep full quality."
        )

    def set_quality_level(self, level_id: str) -> None:
        self.level_combo.setCurrentIndex(self.level_combo.findData(level_id))

    def _set_use_word(self, use_word: bool) -> None:
        self.engine = Engine(all_converters(use_word=use_word))
        self._update_notes()

    def _update_notes(self) -> None:
        target = self.target_combo.currentData()
        notes: list[str] = []
        if target:
            for src in self._source_formats():
                route = self.engine.find_route(src, target)
                if route:
                    for note in self.engine.quality_notes(route):
                        if note not in notes:
                            notes.append(note)
        self.notes_label.setText("\n".join(f"ℹ {n}" for n in notes))

    # --- output folder --------------------------------------------------------

    def _choose_output(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Save converted files to")
        if folder:
            self.output_dir = Path(folder)
            self.output_label.setText(folder)

    def _reset_output(self) -> None:
        self.output_dir = None
        self.output_label.setText(SAME_FOLDER)

    def _open_output_folder(self) -> None:
        if self.last_output is not None:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.last_output)))

    def _open_item_output(self, item: QTreeWidgetItem) -> None:
        output = item.data(COL_STATUS, Qt.ItemDataRole.UserRole)
        if output:
            QDesktopServices.openUrl(QUrl.fromLocalFile(output))

    # --- conversion -----------------------------------------------------------

    def start_conversion(self) -> None:
        target = self.target_combo.currentData()
        if not target or self._thread is not None:
            return
        jobs = []
        for row, (path, fmt) in enumerate(zip(self.files, self.file_formats, strict=True)):
            item = self.tree.topLevelItem(row)
            if fmt is None:
                item.setText(COL_STATUS, "Skipped: unknown file type")
            elif fmt.id == target:
                item.setText(COL_STATUS, "Skipped: already this format")
            else:
                item.setText(COL_STATUS, "Waiting")
                jobs.append((row, path))
        if not jobs:
            return
        category = self._single_category()
        if category is not None:
            self.prefs.save_target(category, target)
        self.save_preferences()

        options = {
            "level": self.level_combo.currentData(),
            "keep_metadata": self.metadata_check.isChecked(),
        }
        self._cancel = threading.Event()
        self._done_count = 0
        self._job_count = len(jobs)
        self.progress.setValue(0)
        self.open_btn.setEnabled(False)

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
        self.tree.topLevelItem(row).setText(COL_STATUS, "Converting…")
        self.status_label.setText(f"Converting {self.files[row].name}")

    @Slot(int, float, str)
    def _on_progress(self, row: int, fraction: float, message: str) -> None:
        self.tree.topLevelItem(row).setText(COL_STATUS, f"{int(fraction * 100)}% {message}")
        self._set_overall(fraction)

    @Slot(int, list, list)
    def _on_done(self, row: int, outputs: list, notes: list) -> None:
        self._done_count += 1
        self._set_overall(0)
        item = self.tree.topLevelItem(row)
        if len(outputs) == 1:
            text = f"✓ {Path(outputs[0]).name}"
        else:
            text = f"✓ {len(outputs)} files"
        item.setText(COL_STATUS, text)
        item.setToolTip(COL_STATUS, "\n".join(outputs))
        if outputs:
            item.setData(COL_STATUS, Qt.ItemDataRole.UserRole, outputs[0])
            self.last_output = Path(outputs[0]).parent

    @Slot(int, str)
    def _on_failed(self, row: int, message: str) -> None:
        self._done_count += 1
        self._set_overall(0)
        item = self.tree.topLevelItem(row)
        item.setText(COL_STATUS, f"✗ {message}")
        item.setToolTip(COL_STATUS, message)

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

    # --- preferences and about ------------------------------------------------

    def _load_preferences(self) -> None:
        level_index = self.level_combo.findData(self.prefs.level)
        if level_index >= 0:
            self.level_combo.setCurrentIndex(level_index)
        self.metadata_check.setChecked(self.prefs.keep_metadata)
        if self.prefs.output_dir is not None:
            self.output_dir = self.prefs.output_dir
            self.output_label.setText(str(self.output_dir))

    def _single_category(self) -> str | None:
        """The kind of files in the list, if they're all the same kind."""
        categories = {f.category for f in self.file_formats if f is not None}
        return categories.pop() if len(categories) == 1 else None

    def _remembered_target(self) -> str | None:
        category = self._single_category()
        return self.prefs.target_for(category) if category else None

    def save_preferences(self) -> None:
        self.prefs.save(
            output_dir=self.output_dir,
            level=self.level_combo.currentData(),
            use_word=self.word_check.isChecked() if self._word_installed else self.prefs.use_word,
            keep_metadata=self.metadata_check.isChecked(),
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
