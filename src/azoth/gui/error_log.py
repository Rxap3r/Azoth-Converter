"""Error log: when something goes wrong, write the details to a file on this computer.

The log is a plain text file in the app's own folder (removed by the uninstaller). It is
never sent anywhere; the user can open it and pass it on if they want to report a problem.
It may contain file names, so the dialog and PRIVACY.md say so.

Two kinds of problems are caught:
- Python errors nobody handled: written to the log, and the user sees a short message
  instead of the app silently closing;
- hard crashes inside a library (e.g. an image decoder): Python's ``faulthandler``
  writes where it happened just before the app closes.
"""

from __future__ import annotations

import faulthandler
import platform
import sys
import threading
import traceback
from datetime import datetime
from pathlib import Path

from .. import __version__
from .settings import storage_dir

FILE_NAME = "error-log.txt"
MAX_BYTES = 1_000_000  # older entries are dropped beyond this
KEEP_BYTES = 300_000

_crash_file = None  # kept open for faulthandler


def log_path() -> Path:
    return storage_dir() / FILE_NAME


def _trim(path: Path) -> None:
    try:
        if path.stat().st_size > MAX_BYTES:
            data = path.read_bytes()[-KEEP_BYTES:]
            path.write_bytes(b"(older entries removed)\n" + data[data.find(b"\n") + 1 :])
    except OSError:
        pass


def write(title: str, details: str) -> Path | None:
    """Add one entry to the log. Never raises: logging must not cause a second error."""
    path = log_path()
    try:
        _trim(path)
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        header = (
            f"=== {stamp} · {title} · Azoth Converter {__version__} · "
            f"{platform.system()} {platform.release()} · Python {platform.python_version()}\n"
        )
        with path.open("a", encoding="utf-8") as f:
            f.write(header + details.rstrip() + "\n\n")
        return path
    except OSError:
        return None


def _show_message(path: Path | None) -> None:
    from PySide6.QtWidgets import QApplication, QMessageBox

    if QApplication.instance() is None:
        return
    where = f"\n\nThe details were saved in:\n{path}" if path else ""
    QMessageBox.warning(
        None,
        "Something went wrong",
        "Sorry, an unexpected error happened. Your original files were not changed."
        f"{where}\n\nThe file stays on this computer. If you report the problem, you can "
        "attach it; it may contain names of files you converted.",
    )


def _excepthook(kind, value, tb) -> None:
    path = write("Unexpected error", "".join(traceback.format_exception(kind, value, tb)))
    try:
        _show_message(path)
    except Exception:  # the message box itself must never crash the app
        pass


def _thread_excepthook(args) -> None:
    if args.exc_type is SystemExit:
        return
    details = "".join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback))
    write(f"Unexpected error in thread {getattr(args.thread, 'name', '?')}", details)


def install() -> None:
    """Start logging. Call once, before the window opens."""
    global _crash_file
    sys.excepthook = _excepthook
    threading.excepthook = _thread_excepthook
    try:
        path = log_path()
        _trim(path)
        _crash_file = path.open("a", encoding="utf-8")
        faulthandler.enable(file=_crash_file, all_threads=True)
    except OSError:
        _crash_file = None
