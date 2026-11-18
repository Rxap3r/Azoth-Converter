"""Known file formats and content-based format detection.

Detection looks at the file's first bytes ("magic numbers") first and only
falls back to the file extension when the content is ambiguous, so a renamed
file is still recognised correctly.
"""

from __future__ import annotations

import zipfile
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Format:
    id: str
    name: str
    category: str
    extensions: tuple[str, ...]

    @property
    def extension(self) -> str:
        """Preferred extension, without the dot."""
        return self.extensions[0]


IMAGE = "image"
PDF = "pdf"
DOCUMENT = "document"
SPREADSHEET = "spreadsheet"
PRESENTATION = "presentation"

_ALL = [
    # Images
    Format("jpg", "JPEG image", IMAGE, ("jpg", "jpeg", "jfif", "jpe")),
    Format("png", "PNG image", IMAGE, ("png",)),
    Format("webp", "WebP image", IMAGE, ("webp",)),
    Format("bmp", "Bitmap image", IMAGE, ("bmp", "dib")),
    Format("tiff", "TIFF image", IMAGE, ("tiff", "tif")),
    Format("gif", "GIF image", IMAGE, ("gif",)),
    Format("ico", "Windows icon", IMAGE, ("ico",)),
    Format("heic", "HEIC/HEIF image (iPhone)", IMAGE, ("heic", "heif")),
    Format("avif", "AVIF image", IMAGE, ("avif",)),
    # PDF
    Format("pdf", "PDF document", PDF, ("pdf",)),
    # Text documents
    Format("docx", "Word document", DOCUMENT, ("docx",)),
    Format("doc", "Word 97-2003 document", DOCUMENT, ("doc",)),
    Format("odt", "OpenDocument text", DOCUMENT, ("odt",)),
    Format("rtf", "Rich Text Format", DOCUMENT, ("rtf",)),
    Format("txt", "Plain text", DOCUMENT, ("txt",)),
    # Spreadsheets
    Format("xlsx", "Excel workbook", SPREADSHEET, ("xlsx",)),
    Format("xls", "Excel 97-2003 workbook", SPREADSHEET, ("xls",)),
    Format("ods", "OpenDocument spreadsheet", SPREADSHEET, ("ods",)),
    Format("csv", "CSV (comma-separated values)", SPREADSHEET, ("csv",)),
    # Presentations
    Format("pptx", "PowerPoint presentation", PRESENTATION, ("pptx",)),
    Format("ppt", "PowerPoint 97-2003 presentation", PRESENTATION, ("ppt",)),
    Format("odp", "OpenDocument presentation", PRESENTATION, ("odp",)),
]

FORMATS: dict[str, Format] = {f.id: f for f in _ALL}
_BY_EXTENSION: dict[str, Format] = {ext: f for f in _ALL for ext in f.extensions}


def get(format_id: str) -> Format:
    """Look up a format by id or by any of its extensions (case-insensitive)."""
    key = format_id.lower().lstrip(".")
    fmt = FORMATS.get(key) or _BY_EXTENSION.get(key)
    if fmt is None:
        raise KeyError(f"Unknown format: {format_id}")
    return fmt


def from_extension(path: Path) -> Format | None:
    return _BY_EXTENSION.get(path.suffix.lower().lstrip("."))


_ODF_MIMETYPES = {
    b"application/vnd.oasis.opendocument.text": "odt",
    b"application/vnd.oasis.opendocument.spreadsheet": "ods",
    b"application/vnd.oasis.opendocument.presentation": "odp",
}


def _detect_zip(path: Path) -> str | None:
    """Tell Office Open XML and OpenDocument files apart (both are ZIP files)."""
    try:
        with zipfile.ZipFile(path) as zf:
            names = set(zf.namelist())
            if "mimetype" in names:
                return _ODF_MIMETYPES.get(zf.read("mimetype").strip())
            if "word/document.xml" in names:
                return "docx"
            if "xl/workbook.xml" in names:
                return "xlsx"
            if "ppt/presentation.xml" in names:
                return "pptx"
    except (zipfile.BadZipFile, OSError, KeyError):
        return None
    return None


def _detect_magic(path: Path, head: bytes) -> str | None:
    if head.startswith(b"%PDF-"):
        return "pdf"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if head.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if head.startswith((b"GIF87a", b"GIF89a")):
        return "gif"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "webp"
    if head.startswith(b"BM"):
        return "bmp"
    if head.startswith((b"II*\x00", b"MM\x00*")):
        return "tiff"
    if head.startswith(b"\x00\x00\x01\x00"):
        return "ico"
    if head[4:8] == b"ftyp":
        brand = head[8:12]
        if brand in (b"avif", b"avis"):
            return "avif"
        if brand in (b"heic", b"heix", b"hevc", b"hevx", b"mif1", b"msf1", b"heim", b"heis"):
            return "heic"
    if head.startswith(b"{\\rtf"):
        return "rtf"
    if head.startswith(b"PK\x03\x04"):
        return _detect_zip(path)
    if head.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
        # Legacy OLE container (doc/xls/ppt): the extension tells which one.
        ext = from_extension(path)
        if ext is not None and ext.id in ("doc", "xls", "ppt"):
            return ext.id
        return None
    return None


def detect(path: Path) -> Format | None:
    """Return the format of ``path``, or ``None`` if it is not recognised."""
    path = Path(path)
    try:
        with path.open("rb") as fh:
            head = fh.read(32)
    except OSError:
        return None
    found = _detect_magic(path, head)
    if found is not None:
        return FORMATS[found]
    # Plain-text formats have no magic bytes; trust the extension for those.
    ext = from_extension(path)
    if ext is not None and ext.id in ("txt", "csv"):
        return ext
    # An empty or unrecognised file with a known extension: let the engine decide.
    return ext
