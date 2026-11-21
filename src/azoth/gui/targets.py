"""Which targets the window offers for the files in the list, and the notes shown for them.

No Qt here, so this logic is easy to test and stays the same when the look changes.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from .. import formats, metadata, ranking
from ..engine import Engine

CLEAN_TARGET = "clean"  # not a format: same format, metadata removed (see metadata.py)
CLEAN_NOTE = (
    "Saves a copy without the hidden information: GPS location, camera, date, author, "
    "comments and preview pictures. The picture itself stays exactly the same. "
    "Next to the original, the copy is called “name (clean)”."
)
CLEAN_TILE = ("Remove metadata only", "Same format, no location or camera data")

# Short tile text: what each target is good for, in a word or two.
_PURPOSE = {
    "jpg": "Photos", "png": "Lossless", "webp": "Websites", "bmp": "Old apps",
    "tiff": "Print", "gif": "Simple", "ico": "Icon", "heic": "iPhone",
    "avif": "Small files", "pdf": "Document", "docx": "Word", "doc": "Old Word",
    "odt": "OpenDocument", "rtf": "Rich text", "txt": "Plain text", "xlsx": "Excel",
    "xls": "Old Excel", "ods": "OpenDocument", "csv": "Plain table",
    "pptx": "PowerPoint", "ppt": "Old PowerPoint", "odp": "OpenDocument",
}  # fmt: skip
_DISPLAY = {"webp": "WebP", "docx": "DOCX"}


def display_name(format_id: str) -> str:
    """How a format is written in the app: "JPG", "WebP", "PDF" …"""
    return _DISPLAY.get(format_id, format_id.upper())


def tile_text(format_id: str) -> tuple[str, str]:
    """(title, what it's good for) for a target tile."""
    return display_name(format_id), _PURPOSE.get(format_id, formats.FORMATS[format_id].name)


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


def ocr_mode(file_formats: FileFormats, target: str | None) -> str | None:
    """Whether the "Text recognition" choices apply: "always" when photos (or scans in
    PDFs) become text or Word, "optional" when photos become a PDF, else None."""
    sources = source_formats(file_formats)
    images = any(formats.FORMATS[s].category == formats.IMAGE for s in sources)
    if target in ("docx", "txt") and (images or "pdf" in sources):
        return "always"
    if target == "pdf" and images:
        return "optional"
    return None


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
