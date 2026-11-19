"""Show and remove the hidden information in photos (location, camera, date, author …).

The picture itself is never changed: the metadata is cut out of the file and the picture
data is copied as it is (see ``converters/strip.py`` and ``converters/jpeg_tools.py``).
Before a cleaned file is saved, both versions are decoded and compared pixel by pixel,
and the cleaned one is checked again for leftover metadata. If either check fails,
nothing is written.

Kept on purpose, because they change how the picture looks: the colour profile, the
orientation (so the photo stays upright), the resolution (DPI) and animation timing.
"""

from __future__ import annotations

import io
import struct
from dataclasses import dataclass, field
from pathlib import Path

from PIL import ExifTags, Image, ImageSequence

from . import formats
from .converters import ConversionError, jpeg_tools, strip
from .converters import images as _images  # registers the HEIC opener
from .engine import check_file_name, unique_path

CLEANABLE = ["jpg", "png", "webp", "gif", "tiff"]
if _images.HEIF_SUPPORTED:
    CLEANABLE.append("heic")
if _images.AVIF_SUPPORTED:
    CLEANABLE.append("avif")

CLEAN_SUFFIX = " (clean)"  # added to the name when the copy goes next to the original

_STRIPPERS = {
    "jpg": jpeg_tools.strip_jpeg_metadata,
    "png": strip.strip_png,
    "webp": strip.strip_webp,
    "gif": strip.strip_gif,
    "tiff": strip.strip_tiff,
    "heic": strip.strip_heif,
    "avif": strip.strip_heif,
}

GPS = ExifTags.IFD.GPSInfo
EXIF = ExifTags.IFD.Exif

# EXIF tags shown by name: (where, tag) → label. "base" is the main EXIF block.
_NAMED = [
    ("Camera", [("base", 0x010F), ("base", 0x0110)]),  # make, model
    ("Lens", [("exif", 0xA433), ("exif", 0xA434)]),
    ("Date taken", [("exif", 0x9003), ("base", 0x0132)]),
    ("Serial number", [("exif", 0xA431), ("exif", 0xA435)]),
    ("Owner / author", [("exif", 0xA430), ("base", 0x013B), ("base", 0x9C9D)]),
    ("Copyright", [("base", 0x8298)]),
    ("Description", [("base", 0x010E), ("exif", 0x9286), ("base", 0x9C9C), ("base", 0x9C9B)]),
    ("Software", [("base", 0x0131)]),
    ("Computer", [("base", 0x013C)]),
]
# EXIF tags that only describe the picture's layout: not private, and kept by every format.
_LAYOUT_TAGS = {
    0x0112, 0x011A, 0x011B, 0x0128, 0x0213, 0x8769, 0x8825, 0xA005,
    # TIFF picture structure (written by the TIFF format itself)
    0x00FE, 0x00FF, 0x0100, 0x0101, 0x0102, 0x0103, 0x0106, 0x0107, 0x010A, 0x0111, 0x0115,
    0x0116, 0x0117, 0x011C, 0x013D, 0x0140, 0x0142, 0x0143, 0x0144, 0x0145, 0x0152, 0x0153,
    0x0212, 0x0214, 0x8773,
}  # fmt: skip
_EXIF_HARMLESS = {0x9000, 0xA000, 0x9101, 0xA001, 0xA002, 0xA003, 0xA005}  # versions, size


@dataclass(frozen=True)
class Finding:
    label: str
    detail: str

    def __str__(self) -> str:
        return f"{self.label}: {self.detail}"


@dataclass
class CleanResult:
    source: Path
    output: Path
    removed: list[Finding] = field(default_factory=list)


def _text(value) -> str:
    if isinstance(value, bytes):
        if value[:8] in (b"ASCII\x00\x00\x00", b"UNICODE\x00", b"\x00" * 8):  # UserComment
            value = value[8:]
        try:
            value = value.decode("utf-16-le") if b"\x00" in value[1::2] else value.decode()
        except UnicodeDecodeError:
            value = value.decode("latin-1")
    text = " ".join(str(value).replace("\x00", " ").split())
    return text if len(text) <= 80 else text[:77] + "…"


def _coordinate(values, ref) -> float | None:
    try:
        degrees, minutes, seconds = (float(v) for v in values)
    except (TypeError, ValueError, ZeroDivisionError):
        return None
    result = degrees + minutes / 60 + seconds / 3600
    return -result if _text(ref) in ("S", "W") else result


def _location(gps) -> str:
    lat = _coordinate(gps.get(2), gps.get(1))
    lon = _coordinate(gps.get(4), gps.get(3))
    if lat is None or lon is None:
        return "GPS data (where the photo was taken)"
    ns = "N" if lat >= 0 else "S"
    ew = "E" if lon >= 0 else "W"
    return f"{abs(lat):.5f}° {ns}, {abs(lon):.5f}° {ew}"


def _has_xmp(xmp) -> bool:
    if isinstance(xmp, str):
        xmp = xmp.encode("utf-8", "replace")
    return bool(xmp) and b"rdf:" in xmp  # an empty XMP packet holds nothing


def _ifd(exif: Image.Exif, tag: int) -> dict:
    try:
        return dict(exif.get_ifd(tag))
    except Exception:  # unusual data from some cameras: report it as "other" instead
        return {}


def _orientation_only(exif_bytes: bytes) -> bool:
    """True for an EXIF block that holds nothing but the orientation (that one is kept)."""
    exif = Image.Exif()
    try:
        exif.load(exif_bytes)
        return set(exif) <= {0x0112} and not _ifd(exif, ExifTags.IFD.IFD1)
    except Exception:
        return False


def _has_other_blocks(fmt: str, data: bytes) -> bool:
    """True if the file has metadata blocks besides the ones listed by name."""
    if fmt == "jpg":
        return any(
            not (s[4:].startswith(b"Exif\x00\x00") and _orientation_only(s[4:]))
            for m, s in jpeg_tools.removed_segments(data)
        )
    if fmt == "png":
        return any(
            k not in strip.PNG_KEEP and not (k == b"eXIf" and _orientation_only(c[8:-4]))
            for k, c in strip._png_chunks(data)
        )
    if fmt == "webp":
        return any(
            k not in strip.WEBP_KEEP and not (k == b"EXIF" and _orientation_only(c[8:]))
            for k, c in strip._webp_chunks(data)
        )
    if fmt == "gif":
        return bool(strip.gif_metadata_blocks(data))
    return False  # HEIC/AVIF and TIFF: everything is listed by name


def _from_pillow(im: Image.Image) -> list[Finding]:
    found: list[Finding] = []
    exif = im.getexif()
    blocks = {"base": exif, "exif": _ifd(exif, EXIF)}
    gps = _ifd(exif, GPS)
    if gps:
        found.append(Finding("Location (GPS)", _location(gps)))
    named: set[tuple[str, int]] = set()
    for label, tags in _NAMED:
        values = []
        for where, tag in tags:
            named.add((where, tag))
            value = _text(blocks[where].get(tag, "")) if tag in blocks[where] else ""
            if value and value not in values:
                values.append(value)
        if values:
            found.append(Finding(label, " ".join(values)))
    if 0x927C in blocks["exif"]:
        found.append(Finding("Camera maker data", "hidden settings stored by the camera"))
    if im.format != "TIFF" and _ifd(exif, ExifTags.IFD.IFD1):  # in TIFF: the next page
        found.append(
            Finding("Preview picture", "a small copy of the photo; it may show cropped parts")
        )
    other = [t for t in blocks["base"] if t not in _LAYOUT_TAGS and ("base", t) not in named]
    other += [t for t in blocks["exif"] if t not in _EXIF_HARMLESS and ("exif", t) not in named]
    other = [t for t in other if t != 0x927C]
    if other:
        found.append(Finding("Other photo details", f"{len(other)} more EXIF entries"))

    info = im.info
    tags = getattr(im, "tag_v2", {})
    if any(_has_xmp(x) for x in (info.get("xmp"), info.get("XML:com.adobe.xmp"), tags.get(700))):
        found.append(Finding("XMP data", "editing history, keywords, sometimes a location"))
    if info.get("photoshop") or 33723 in tags or 34377 in tags:
        found.append(Finding("IPTC / Photoshop data", "captions, keywords, author, place"))
    comment = info.get("comment")
    if comment:
        found.append(Finding("Comment", _text(comment)))
    text = {k: v for k, v in getattr(im, "text", {}).items() if k != "XML:com.adobe.xmp"}
    if text:
        found.append(Finding("Text fields", ", ".join(sorted(text))))
    return found


def _open(data: bytes) -> Image.Image:
    return Image.open(io.BytesIO(data))


def inspect_bytes(fmt: str, data: bytes) -> list[Finding]:
    """What private information an image file contains (empty list: nothing found)."""
    try:
        with _open(data) as im:
            found = _from_pillow(im)
            if fmt == "tiff":  # every page has its own tags
                for page in ImageSequence.Iterator(im):
                    found += [f for f in _from_pillow(page) if f not in found]
    except Exception as exc:
        raise ConversionError(f"Could not read the image: {exc}") from exc
    try:
        if fmt == "jpg" and jpeg_tools.has_data_after_image(data):
            found.append(
                Finding("Extra data", "hidden after the picture, e.g. a second photo or a video")
            )
        if not found and _has_other_blocks(fmt, data):
            found.append(Finding("Other hidden data", "stored by a camera or program"))
    except (ValueError, IndexError, struct.error):
        pass  # damaged file: the cleaning step reports that itself
    return found


def inspect(path: Path | str) -> list[Finding]:
    path = Path(path)
    fmt = _cleanable_format(path)
    return inspect_bytes(fmt, path.read_bytes())


def _cleanable_format(path: Path) -> str:
    if not path.is_file():
        raise ConversionError(f"File not found: {path}")
    fmt = formats.detect(path)
    if fmt is None or fmt.id not in CLEANABLE:
        kind = fmt.name if fmt else "this kind of file"
        names = ", ".join({"webp": "WebP"}.get(f, f.upper()) for f in CLEANABLE)
        raise ConversionError(
            f"Removing metadata works for photos and images ({names}), not for {kind}."
        )
    return fmt.id


def _strip(fmt: str, data: bytes, orientation: int) -> bytes:
    try:
        return _STRIPPERS[fmt](data, orientation=orientation)
    except (ValueError, IndexError, OSError) as exc:  # damaged or unusual files
        raise ConversionError(f"Could not remove the metadata: {exc}") from exc


def _frames(im: Image.Image):
    for frame in ImageSequence.Iterator(im):
        yield frame.mode, frame.size, frame.tobytes()


def _same_picture(a: bytes, b: bytes, *, compare_orientation: bool = True) -> bool:
    with _open(a) as x, _open(b) as y:
        if getattr(x, "n_frames", 1) != getattr(y, "n_frames", 1):
            return False
        if compare_orientation and x.getexif().get(0x0112, 1) != y.getexif().get(0x0112, 1):
            return False
        if x.info.get("icc_profile") != y.info.get("icc_profile"):
            return False
        return all(f == g for f, g in zip(_frames(x), _frames(y), strict=True))


def clean_bytes(fmt: str, data: bytes) -> bytes:
    """The image without metadata. Raises ``ConversionError`` if that isn't possible
    without changing the picture."""
    try:
        with _open(data) as im:
            orientation = im.getexif().get(0x0112, 1)
    except Exception as exc:
        raise ConversionError(f"Could not read the image: {exc}") from exc
    if fmt in ("heic", "avif"):
        orientation = 1  # kept in the file's own image properties
    if fmt == "tiff":
        orientation = 1  # Pillow turns TIFF pages upright when reading; they're saved that way
    cleaned = _strip(fmt, data, orientation)
    try:
        same = _same_picture(data, cleaned, compare_orientation=fmt != "tiff")
    except Exception:
        same = False
    if not same:
        raise ConversionError(
            "The metadata can't be removed from this file without changing the picture. "
            "Nothing was saved."
        )
    left = inspect_bytes(fmt, cleaned)
    if left:
        raise ConversionError(
            "Some metadata could not be removed ("
            + ", ".join(f.label for f in left)
            + "). Nothing was saved."
        )
    return cleaned


def output_path(source: Path, fmt: str, output_dir: Path | None, name: str | None = None) -> Path:
    """Next to the original: ``photo (clean).jpg``. In another folder: the same name.

    ``name`` (without extension) replaces the original's name.
    """
    suffix = (
        source.suffix
        if source.suffix.lower().lstrip(".") in formats.FORMATS[fmt].extensions
        else f".{formats.FORMATS[fmt].extension}"
    )
    folder = output_dir if output_dir is not None else source.parent
    if name is not None:
        return folder / f"{check_file_name(name, suffix.lstrip('.'))}{suffix}"
    if folder.resolve() == source.parent.resolve():
        return folder / f"{source.stem}{CLEAN_SUFFIX}{suffix}"
    return folder / f"{source.stem}{suffix}"


def clean_file(
    source: Path | str,
    output_dir: Path | str | None = None,
    *,
    overwrite: bool = False,
    name: str | None = None,
) -> CleanResult:
    """Save a copy of ``source`` without metadata. The original is never changed."""
    source = Path(source)
    fmt = _cleanable_format(source)
    data = source.read_bytes()
    removed = inspect_bytes(fmt, data)
    cleaned = clean_bytes(fmt, data)

    folder = Path(output_dir) if output_dir is not None else None
    if folder is not None:
        folder.mkdir(parents=True, exist_ok=True)
    target = output_path(source, fmt, folder, name)
    if not overwrite or target.resolve() == source.resolve():
        target = unique_path(target)
    try:
        target.write_bytes(cleaned)
    except OSError as exc:
        raise ConversionError(f"Could not save {target.name}: {exc.strerror or exc}") from exc
    return CleanResult(source=source, output=target, removed=removed)
