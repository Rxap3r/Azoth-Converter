"""Paths to files shipped with the app (works from source and in the packaged .exe)."""

from __future__ import annotations

from pathlib import Path

RESOURCES = Path(__file__).resolve().parent.parent / "resources"


def icon_path() -> Path:
    return RESOURCES / "icon.png"


def resources_dir() -> Path:
    return RESOURCES
