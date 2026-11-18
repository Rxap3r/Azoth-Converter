"""Remembers a few choices between launches.

Stored only on this computer (on Windows in the registry under
HKEY_CURRENT_USER\\Software\\Azoth Converter). Only preferences are kept: no file
names, no history. The uninstaller removes them.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings

ORGANIZATION = "Azoth Converter"
APPLICATION = "Azoth Converter"


def open_settings() -> QSettings:
    return QSettings(
        QSettings.defaultFormat(), QSettings.Scope.UserScope, ORGANIZATION, APPLICATION
    )


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
