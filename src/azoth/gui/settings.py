"""Remembers a few choices between launches.

Everything the app stores lives in ONE folder, so uninstalling can remove it
completely: on Windows ``%APPDATA%\\Azoth Converter``. Nothing goes into the
registry. Only preferences are kept: no file names, no history.

Qt's file dialogs normally remember visited folders in a registry area shared by
all Qt programs. ``configure_storage`` redirects that into our folder too, and
``forget_file_dialog_history`` erases it after each dialog.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from PySide6.QtCore import QSettings

ORGANIZATION = "Azoth Converter"
APPLICATION = "Azoth Converter"
FOLDER_NAME = "Azoth Converter"

_storage_dir: Path | None = None


def default_storage_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / FOLDER_NAME


def configure_storage(folder: Path | None = None) -> Path:
    """Send all settings (ours and Qt's) to ``folder``. Call before any QSettings use."""
    global _storage_dir
    _storage_dir = Path(folder) if folder else default_storage_dir()
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(_storage_dir))
    return _storage_dir


def storage_dir() -> Path:
    return _storage_dir or configure_storage()


def open_settings() -> QSettings:
    return QSettings(str(storage_dir() / "settings.ini"), QSettings.Format.IniFormat)


def forget_file_dialog_history() -> None:
    """Erase the folders Qt's file dialog remembered (privacy: no history)."""
    storage_dir()  # make sure Qt's settings point at our folder
    qt = QSettings(QSettings.Format.IniFormat, QSettings.Scope.UserScope, "QtProject")
    qt.remove("FileDialog")
    qt.sync()


class Preferences:
    def __init__(self, store: QSettings | None = None) -> None:
        self.store = store or open_settings()

    def _get(self, key: str, default, kind=str):
        value = self.store.value(key, default)
        if kind is bool:
            return value in (True, "true", "1", 1)
        try:
            return kind(value)
        except (TypeError, ValueError):
            return default

    def target_for(self, category: str) -> str | None:
        """Last target chosen for this kind of file (PDF, image, document, …)."""
        return self._get(f"targets/{category}", "") or None

    def save_target(self, category: str, target: str) -> None:
        self.store.setValue(f"targets/{category}", target)
        self.store.sync()

    @property
    def output_dir(self) -> Path | None:
        raw = self._get("output_dir", "")
        path = Path(raw) if raw else None
        return path if path is not None and path.is_dir() else None  # folder may be gone

    @property
    def level(self) -> str | None:
        return self._get("quality_level", "") or None

    @property
    def use_word(self) -> bool:
        return self._get("use_word", True, bool)

    @property
    def keep_metadata(self) -> bool:
        return self._get("keep_metadata", False, bool)

    def save(
        self,
        *,
        output_dir: Path | None,
        level: str,
        use_word: bool,
        keep_metadata: bool,
    ) -> None:
        self.store.setValue("output_dir", str(output_dir) if output_dir else "")
        self.store.setValue("quality_level", level)
        self.store.setValue("use_word", use_word)
        self.store.setValue("keep_metadata", keep_metadata)
        self.store.sync()
