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
    "Saves a copy without hidden personal data. Removed: GPS location, camera, date, "
    "author, comments and preview pictures. The content itself stays exactly the same. "
    "Next to the original, the copy is called “name (clean)”."
)
CLEAN_TILE = ("Remove metadata only", "Same format, no hidden personal data")
RESIZE_TARGET = "resize"  # not a format: same format, new picture size (see resize.py)
RESIZE_TILE = ("Change size only", "Same format, new width and height")
RESIZE_NOTE = "Saves a copy in the new size. Next to the original, it is called “name (resized)”."
SHRINK_TARGET = "shrink"  # not a format: any video → a smaller MP4 (option "shrink")
SHRINK_TILE = ("Make smaller", "MP4 for e-mail and messengers")
SHRINK_NOTE = (
    "Saves a much smaller MP4 copy for e-mail and messengers, called “name (smaller)”. "
    "The picture gets a little softer, and videos with more than 30 frames per second are "
    "saved with 30. Videos that are already small aren't made any bigger."
)
SHRINK_SIZES = (
    ("1080", "Full HD (1080p)", "Still sharp on a TV or big screen."),
    ("720", "HD (720p)", "Good for e-mail and messengers: sharp on phones and laptops."),
    ("480", "Small (480p)", "The smallest files; still fine on a phone."),
)

# Short tile text: what each target is good for, in a word or two.
_PURPOSE = {
    "jpg": "Photos", "png": "Lossless", "webp": "Websites", "bmp": "Old apps",
    "tiff": "Print", "gif": "Simple", "ico": "Icon", "heic": "iPhone",
    "avif": "Small files", "pdf": "Document", "docx": "Word", "doc": "Old Word",
    "odt": "OpenDocument", "rtf": "Rich text", "txt": "Plain text", "xlsx": "Excel",
    "xls": "Old Excel", "ods": "OpenDocument", "csv": "Plain table",
    "pptx": "PowerPoint", "ppt": "Old PowerPoint", "odp": "OpenDocument",
    "mp4": "Everywhere", "mov": "Apple", "mkv": "All tracks", "webm": "Websites",
    "avi": "Old players", "mp3": "Music", "m4a": "Apple", "wav": "Studio",
    "flac": "Lossless", "ogg": "Open format", "opus": "Small files",
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
    can_resize: bool = False
    """True if "Same format, new size" works for every file."""
    can_shrink: bool = False
    """True if every file is a video that can be made smaller."""

    def __bool__(self) -> bool:
        return bool(self.formats) or self.can_clean or self.can_resize or self.can_shrink


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
        can_resize=all(engine.can_resize(s, s) for s in sources),
        can_shrink=all(engine.can_shrink(s) for s in sources),
    )


def can_resize(engine: Engine, file_formats: FileFormats, target: str | None) -> bool:
    """Whether the "Picture size" choices apply: every file is a picture that stays a
    picture (``target`` an image format, or "Change size only")."""
    sources = source_formats(file_formats)
    if not sources or target in (None, CLEAN_TARGET, SHRINK_TARGET):
        return False
    return all(engine.can_resize(s, s if target == RESIZE_TARGET else target) for s in sources)


def jobs(file_formats: FileFormats, target: str | None, resizing: bool) -> list[int]:
    """Positions of the files that will be converted. Files that already have the target
    format are skipped, unless they get a new size (then a resized copy is saved)."""
    if target is None:
        return []
    if target == SHRINK_TARGET:  # every video gets a smaller copy, MP4 ones too
        return [i for i, fmt in enumerate(file_formats) if fmt is not None]
    return [
        i
        for i, fmt in enumerate(file_formats)
        if fmt is not None and (resizing or (fmt.id != target and target != RESIZE_TARGET))
    ]


def job_target(target: str, source: formats.Format) -> str:
    """The format a file is converted to ("Change size only": its own)."""
    if target == SHRINK_TARGET:
        return "mp4"
    return source.id if target == RESIZE_TARGET else target


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


MEDIA = (formats.VIDEO, formats.AUDIO)


LOSSY_IMAGES = ("jpg", "webp", "heic", "avif")  # their quality setting matters
PAGED = (formats.PDF, formats.DOCUMENT, formats.SPREADSHEET, formats.PRESENTATION)


def uses_quality(file_formats: FileFormats, target: str | None) -> bool:
    """Whether the Quality choice changes anything, so it's only shown then: photos saved
    in a lossy format, and pages (PDF, Office) saved as pictures. Everything else keeps
    full quality anyway (documents → PDF, video and sound use their own settings)."""
    sources = source_formats(file_formats)
    kinds = {formats.FORMATS[s].category for s in sources}
    if target == RESIZE_TARGET:
        return any(s in LOSSY_IMAGES for s in sources)
    if target not in formats.FORMATS or formats.FORMATS[target].category != formats.IMAGE:
        return False
    if target in LOSSY_IMAGES and formats.IMAGE in kinds:
        return True
    return bool(kinds & set(PAGED))


def first_sentence(text: str) -> str:
    """ "GIF has 256 colours. Best for …" → "GIF has 256 colours." (the rest is shown on
    hover). Dots inside numbers ("8.1") or names ("e.g.") don't end a sentence."""
    import re

    match = re.search(r"(?<!\be\.g)(?<!\bi\.e)\.(?=\s+[A-Z(“\"])", text)
    return text[: match.start() + 1] if match else text


def notes(engine: Engine, file_formats: FileFormats, target: str | None) -> list[str]:
    """Quality notes for converting the files to ``target`` (e.g. "GIF has 256 colours")."""
    if target == CLEAN_TARGET:
        return [CLEAN_NOTE]
    if target == SHRINK_TARGET:
        return [SHRINK_NOTE]
    result: list[str] = [RESIZE_NOTE] if target == RESIZE_TARGET else []
    if target:
        for src in source_formats(file_formats):
            if target == RESIZE_TARGET:
                route = engine.resize_route(src)
            else:
                route = engine.find_route(src, target)
            for note in engine.quality_notes(route) if route else []:
                if note not in result:
                    result.append(note)
    return result
