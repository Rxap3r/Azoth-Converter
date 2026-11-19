"""Which targets the window offers for the files in the list, and the notes shown for them.

No Qt here, so this logic is easy to test and stays the same when the look changes.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from .. import formats, metadata, ranking
from ..engine import Engine

CLEAN_TARGET = "clean"  # not a format: same format, metadata removed (see metadata.py)
CLEAN_LABEL = "Same format, remove metadata (location, camera, date)"
CLEAN_NOTE = (
    "Saves a copy without the hidden information: GPS location, camera, date, author, "
    "comments and preview pictures. The picture itself stays exactly the same. "
    "Next to the original, the copy is called “name (clean)”."
)
NO_COMMON_TARGET = "These files have no target format in common. Convert them in separate groups."

FileFormats = Iterable[formats.Format | None]  # None: a file of unknown type


@dataclass(frozen=True)
class Choices:
    formats: list[formats.Format]
    """Target formats every file can be converted to, most useful first."""
    can_clean: bool
    """True if "Same format, remove metadata" works for every file."""

    def __bool__(self) -> bool:
        return bool(self.formats) or self.can_clean


def source_formats(file_formats: FileFormats) -> list[str]:
    """The different format ids in the list, in order, without unknown files."""
    ids: list[str] = []
    for fmt in file_formats:
        if fmt is not None and fmt.id not in ids:
            ids.append(fmt.id)
    return ids


def single_category(file_formats: FileFormats) -> str | None:
    """The kind of files in the list (e.g. "image"), if they're all the same kind."""
    categories = {f.category for f in file_formats if f is not None}
    return categories.pop() if len(categories) == 1 else None


def choices(engine: Engine, file_formats: FileFormats) -> Choices:
    file_formats = list(file_formats)
    sources = source_formats(file_formats)
    if not sources:
        return Choices([], False)
    # A file that already has the target format is simply skipped, so a target is
    # offered if every file either converts to it or already is it, and at least one
    # file actually needs converting.
    allowed = [{t.id for t in engine.targets_for(s)} | {s} for s in sources]
    common = [
        fmt
        for fmt in formats.FORMATS.values()
        if all(fmt.id in a for a in allowed) and sources != [fmt.id]
    ]
    categories = [f.category for f in file_formats if f is not None]
    return Choices(
        formats=ranking.rank(common, categories),
        can_clean=all(s in metadata.CLEANABLE for s in sources),
    )


def notes(engine: Engine, file_formats: FileFormats, target: str | None) -> list[str]:
    """Quality notes for converting the files to ``target`` (e.g. "GIF has 256 colours")."""
    if target == CLEAN_TARGET:
        return [CLEAN_NOTE]
    result: list[str] = []
    if target:
        for src in source_formats(file_formats):
            route = engine.find_route(src, target)
            for note in engine.quality_notes(route) if route else []:
                if note not in result:
                    result.append(note)
    return result
