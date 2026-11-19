"""Runs the conversions in a background thread, so the window stays responsive."""

from __future__ import annotations

import threading
from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot

from .. import metadata
from ..converters import ConversionCancelled, ConversionError
from ..engine import Engine
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
        jobs: list[tuple[int, Path]],
        target: str,
        output_dir: Path | None,
        options: dict,
        cancel_event: threading.Event,
        name: str | None = None,
    ) -> None:
        super().__init__()
        self.engine = engine
        self.jobs = jobs  # list of (row, path)
        self.target = target
        self.output_dir = output_dir
        self.options = options
        self.cancel_event = cancel_event
        self.name = name  # result's name (only used with a single file)

    @Slot()
    def run(self) -> None:
        for row, path in self.jobs:
            if self.cancel_event.is_set():
                break
            self.file_started.emit(row)
            try:
                if self.target == CLEAN_TARGET:
                    outputs, notes = self._clean(path)
                else:
                    outputs, notes = self._convert(row, path)
            except ConversionCancelled:
                self.file_failed.emit(row, "Cancelled")
                break
            except ConversionError as exc:
                self.file_failed.emit(row, str(exc))
            except Exception as exc:  # never let one bad file kill the app
                self.file_failed.emit(row, f"Unexpected error: {exc}")
            else:
                self.file_done.emit(row, outputs, notes)
        self.finished.emit(self.cancel_event.is_set())

    def _convert(self, row: int, path: Path) -> tuple[list[str], list[str]]:
        result = self.engine.convert(
            path,
            self.target,
            self.output_dir,
            options=self.options,
            progress=lambda f, m: self.file_progress.emit(row, f, m),
            cancel_event=self.cancel_event,
            name=self.name,
        )
        return [str(p) for p in result.outputs], result.notes

    def _clean(self, path: Path) -> tuple[list[str], list[str]]:
        result = metadata.clean_file(path, self.output_dir, name=self.name)
        removed = ", ".join(f.label for f in result.removed) or "no metadata found"
        return [str(result.output)], [f"Removed: {removed}"]
