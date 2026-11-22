"""Portable mode: the app runs from any folder (e.g. a USB stick) and leaves nothing on the PC.

It is on when the file ``portable.txt`` lies next to the program (the portable ZIP has
it). Then settings and the error log go into a ``data`` folder beside the program
instead of ``%APPDATA%``, and the private temporary folders of the jobs go into
``data\\temp`` instead of the PC's temp folder, so not even copies left by a crash stay
behind on someone else's computer.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

MARKER = "portable.txt"
DATA_FOLDER = "data"

_ENV = "AZOTH_PROGRAM_DIR"  # tests only: pretend the program lives in this folder


def program_dir() -> Path | None:
    """The folder of the packaged program (None when run from source)."""
    if os.environ.get(_ENV):
        return Path(os.environ[_ENV])
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return None


def data_dir() -> Path | None:
    """Where the portable app keeps its data, or None when it isn't portable."""
    folder = program_dir()
    if folder is None or not (folder / MARKER).is_file():
        return None
    return folder / DATA_FOLDER


def is_portable() -> bool:
    return data_dir() is not None


def activate() -> Path | None:
    """Switch to portable mode if the marker is there. Call once, at start-up.

    Temporary files then go into ``data/temp`` (also for helper programs such as
    LibreOffice and Word, which read the TEMP variables). If that folder can't be
    created (e.g. a read-only stick), the PC's temp folder is used so conversions
    still work; the job folders are deleted after every job anyway.
    """
    data = data_dir()
    if data is None:
        return None
    temp = data / "temp"
    try:
        temp.mkdir(parents=True, exist_ok=True)
    except OSError:
        return data
    tempfile.tempdir = str(temp)
    for name in ("TMP", "TEMP", "TMPDIR"):
        os.environ[name] = str(temp)
    return data
