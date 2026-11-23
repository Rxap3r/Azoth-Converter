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
VIDEO = "video"
AUDIO = "audio"

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
    # Video
    Format("mp4", "MP4 video", VIDEO, ("mp4", "m4v")),
    Format("mov", "QuickTime video (iPhone)", VIDEO, ("mov", "qt")),
    Format("mkv", "Matroska video", VIDEO, ("mkv",)),
    Format("webm", "WebM video", VIDEO, ("webm",)),
    Format("avi", "AVI video", VIDEO, ("avi",)),
    Format("wmv", "Windows Media video", VIDEO, ("wmv", "asf")),
    Format("mpg", "MPEG video (DVD)", VIDEO, ("mpg", "mpeg", "vob")),
    Format("mts", "AVCHD video (camcorder)", VIDEO, ("mts", "m2ts")),
    Format("flv", "Flash video", VIDEO, ("flv",)),
    Format("3gp", "3GP video (old phones)", VIDEO, ("3gp", "3g2")),
    # Audio
    Format("mp3", "MP3 audio", AUDIO, ("mp3",)),
    Format("m4a", "M4A audio (AAC or Apple Lossless)", AUDIO, ("m4a", "m4b")),
    Format("wav", "WAV audio", AUDIO, ("wav",)),
    Format("flac", "FLAC audio (lossless)", AUDIO, ("flac",)),
    Format("ogg", "Ogg Vorbis audio", AUDIO, ("ogg", "oga")),
    Format("opus", "Opus audio", AUDIO, ("opus",)),
    Format("aac", "AAC audio", AUDIO, ("aac",)),
    Format("wma", "Windows Media audio", AUDIO, ("wma",)),
    Format("aiff", "AIFF audio", AUDIO, ("aiff", "aif")),
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


_MP4_BRANDS = {
    b"isom", b"iso2", b"iso4", b"iso5", b"iso6", b"mp41", b"mp42", b"avc1", b"M4V ",
    b"M4VH", b"M4VP", b"dash", b"mmp4", b"MSNV", b"XAVC", b"f4v ", b"NDAS",
}  # fmt: skip


def _is_transport_stream(head: bytes) -> bool:
    """MPEG transport stream: a 0x47 every 188 bytes (camcorders: every 192)."""
    return (len(head) > 380 and head[0] == head[188] == head[376] == 0x47) or (
        len(head) > 392 and head[4] == head[196] == head[388] == 0x47
    )


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
        if brand == b"qt  ":
            return "mov"
        if brand in (b"M4A ", b"M4B ", b"M4P "):
            return "m4a"
        if brand.startswith((b"3gp", b"3g2")):
            return "3gp"
        if brand in _MP4_BRANDS:
            return "mp4"
    if head[4:8] in (b"moov", b"mdat", b"wide", b"free") and from_extension(path) in (
        FORMATS["mov"],
        FORMATS["mp4"],
    ):
        return from_extension(path).id  # old QuickTime files without "ftyp"
    if head.startswith(b"\x1a\x45\xdf\xa3"):  # Matroska / WebM
        return "webm" if b"webm" in head[:64] else "mkv"
    if head[:4] == b"RIFF" and head[8:12] == b"AVI ":
        return "avi"
    if head[:4] == b"RIFF" and head[8:12] == b"WAVE":
        return "wav"
    if head[:4] == b"FORM" and head[8:12] in (b"AIFF", b"AIFC"):
        return "aiff"
    if head.startswith(b"0&\xb2\x75\x8e\x66\xcf\x11"):  # Windows Media (ASF)
        ext = from_extension(path)
        return "wma" if ext is not None and ext.id == "wma" else "wmv"
    if head.startswith(b"fLaC"):
        return "flac"
    if head.startswith(b"OggS"):
        return "opus" if b"OpusHead" in head[:64] else "ogg"
    if head.startswith(b"FLV\x01"):
        return "flv"
    if head.startswith(b"\x00\x00\x01\xba"):
        return "mpg"
    if _is_transport_stream(head):
        return "mts"
    if len(head) > 1 and head[0] == 0xFF and head[1] & 0xE0 == 0xE0:  # an audio frame
        layer = (head[1] >> 1) & 3
        if layer == 1:
            return "mp3"
        if layer == 0 and head[1] & 0xF0 == 0xF0:
            return "aac"  # raw AAC (ADTS)
    if head.startswith(b"ID3"):
        return "mp3"  # a tag first; almost always MP3
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
            head = fh.read(400)
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
