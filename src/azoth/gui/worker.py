"""Runs the conversions in a background thread, so the window stays responsive."""

from __future__ import annotations

import threading
import traceback
from contextlib import closing
from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot

from .. import metadata
from ..converters import ConversionCancelled, ConversionError
from ..engine import Engine
from . import error_log
from .targets import CLEAN_TARGET


class ConversionWorker(QObject):
    """Converts the files one after another. Talks to the window only through signals."""

    file_started = Signal(int)
    file_progress = Signal(int, float, str)
    file_done = Signal(int, list, list)  # row, output paths, notes
    file_failed = Signal(int, str)
    finished = Signal(bool)  # True if cancelled

    def __init__(
        self,
        engine: Engine,
        jobs: list[tuple[int, Path, str]],
        target: str,
        output_dir: Path | None,
        options: dict,
        cancel_event: threading.Event,
        name: str | None = None,
    ) -> None:
        super().__init__()
        self.engine = engine
        self.jobs = jobs  # list of (row, path, format to convert it to)
        self.target = target  # what the user chose (a format, "clean" or "resize")
        self.output_dir = output_dir
        self.options = options
        self.cancel_event = cancel_event
        self.name = name  # result's name (only used with a single file)

    @Slot()
    def run(self) -> None:
        if self.target == CLEAN_TARGET or self.name is not None:
            self._run_one_by_one()
        else:
            self._run_batch()
        self.finished.emit(self.cancel_event.is_set())

    def _run_batch(self) -> None:
        """Conversions: the engine may do several files in one go (much faster with
        LibreOffice); results still come back file by file. "Change size only" saves each
        file in its own format: one run per format."""
        groups: dict[str, list[tuple[int, Path, str]]] = {}
        for job in self.jobs:
            groups.setdefault(job[2], []).append(job)
        for target, jobs in groups.items():
            if self.cancel_event.is_set() or not self._run_group(target, jobs):
                return

    def _run_group(self, target: str, jobs: list[tuple[int, Path, str]]) -> bool:
        """Convert ``jobs`` (all to ``target``). False if the user cancelled."""
        rows = [row for row, _, _ in jobs]
        results = self.engine.convert_many(
            [path for _, path, _ in jobs],
            target,
            self.output_dir,
            options=self.options,
            started=lambda i: self.file_started.emit(rows[i]),
            progress=lambda i, f, m: self.file_progress.emit(rows[i], f, m),
            cancel_event=self.cancel_event,
        )
        with closing(results):
            for i, outcome in results:
                if isinstance(outcome, Exception):
                    if self._report_failure(rows[i], jobs[i][1], outcome, target):
                        return False
                else:
                    notes = self._notes(jobs[i][1], outcome, target)
                    self.file_done.emit(rows[i], [str(p) for p in outcome.outputs], notes)
        return True

    def _run_one_by_one(self) -> None:
        for row, path, target in self.jobs:
            if self.cancel_event.is_set():
                break
            self.file_started.emit(row)
            try:
                if self.target == CLEAN_TARGET:
                    outputs, notes = self._clean(path)
                else:
                    outputs, notes = self._convert(row, path, target)
            except Exception as exc:  # never let one bad file kill the app
                if self._report_failure(row, path, exc, target):
                    break
            else:
                self.file_done.emit(row, outputs, notes)

    def _report_failure(self, row: int, path: Path, exc: Exception, target: str) -> bool:
        """Show why a file failed. True if the user cancelled (stop the rest)."""
        if isinstance(exc, ConversionCancelled):
            self.file_failed.emit(row, "Cancelled")
            return True
        if isinstance(exc, ConversionError):
            self.file_failed.emit(row, str(exc))
        else:
            error_log.write(
                f"Converting a {path.suffix or 'file'} to {target} failed",
                "".join(traceback.format_exception(exc)),
            )
            self.file_failed.emit(row, f"Unexpected error: {exc}")
        return False

    def _convert(self, row: int, path: Path, target: str) -> tuple[list[str], list[str]]:
        result = self.engine.convert(
            path,
            target,
            self.output_dir,
            options=self.options,
            progress=lambda f, m: self.file_progress.emit(row, f, m),
            cancel_event=self.cancel_event,
            name=self.name,
        )
        return [str(p) for p in result.outputs], self._notes(path, result, target)

    def _notes(self, path: Path, result, target: str) -> list[str]:
        """The result's notes, warnings first (marked ⚠). Warnings also go into the local
        error log, so the details can be looked up later."""
        for warning in result.warnings:
            error_log.write(f"Note while converting a {path.suffix or 'file'} to {target}", warning)
        return [*(f"⚠ {w}" for w in result.warnings), *result.notes]

    def _clean(self, path: Path) -> tuple[list[str], list[str]]:
        result = metadata.clean_file(path, self.output_dir, name=self.name)
        removed = ", ".join(f.label for f in result.removed) or "no metadata found"
        return [str(result.output)], [f"Removed: {removed}"]
