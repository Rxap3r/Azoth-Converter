"""Remove metadata from PNG, WebP, GIF, HEIC/AVIF and TIFF images without touching the picture.

For PNG, WebP, GIF and HEIC/AVIF the file's building blocks are copied byte for byte and
only the blocks that hold metadata are left out (or, for HEIC/AVIF, blanked in place), so
the picture data is not decoded or re-compressed at all. JPEG is in ``jpeg_tools.py``.
TIFF stores its metadata between the picture's own settings, so it is rewritten with the
same lossless compression; ``metadata.clean_bytes`` then checks that every pixel is
unchanged.

Each function takes the picture's EXIF ``orientation``: when it isn't 1, a minimal EXIF
block that holds only the orientation is written, so the picture stays upright.
"""

from __future__ import annotations

import io
import struct
import zlib

# --- PNG -----------------------------------------------------------------------

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
# Chunks that affect how the picture looks (or animates). Everything else is dropped:
# text chunks (tEXt/zTXt/iTXt: author, software, XMP, AI prompts), eXIf, tIME, and
# chunks private to one program.
PNG_KEEP = {
    b"IHDR", b"PLTE", b"IDAT", b"IEND", b"tRNS", b"gAMA", b"cHRM", b"sRGB", b"iCCP",
    b"sBIT", b"bKGD", b"pHYs", b"acTL", b"fcTL", b"fdAT", b"cICP", b"mDCV", b"cLLI",
}  # fmt: skip


def _png_chunk(kind: bytes, body: bytes) -> bytes:
    crc = zlib.crc32(kind + body) & 0xFFFFFFFF
    return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", crc)


def _png_chunks(data: bytes):
    if not data.startswith(PNG_SIGNATURE):
        raise ValueError("not a PNG file")
    i = len(PNG_SIGNATURE)
    while i + 8 <= len(data):
        length, kind = struct.unpack(">I4s", data[i : i + 8])
        end = i + 12 + length
        if end > len(data):
            raise ValueError("damaged PNG file")
        yield kind, data[i:end]
        i = end
        if kind == b"IEND":
            return


def _exif_body(orientation: int) -> bytes:
    """A TIFF-style EXIF block (without the "Exif\\0\\0" prefix) holding only the orientation."""
    from PIL import Image

    exif = Image.Exif()
    exif[0x0112] = orientation
    return exif.tobytes()[6:]


def strip_png(data: bytes, *, orientation: int = 1) -> bytes:
    out = [PNG_SIGNATURE]
    for kind, chunk in _png_chunks(data):
        if kind in PNG_KEEP:
            out.append(chunk)
        if kind == b"IHDR" and orientation != 1:
            out.append(_png_chunk(b"eXIf", _exif_body(orientation)))
    return b"".join(out)


# --- WebP ----------------------------------------------------------------------

WEBP_KEEP = {b"VP8X", b"VP8 ", b"VP8L", b"ALPH", b"ANIM", b"ANMF", b"ICCP"}
_VP8X_EXIF, _VP8X_XMP = 0x08, 0x04


def _webp_chunks(data: bytes):
    if data[:4] != b"RIFF" or data[8:12] != b"WEBP":
        raise ValueError("not a WebP file")
    end = min(len(data), 8 + struct.unpack("<I", data[4:8])[0])
    i = 12
    while i + 8 <= end:
        kind, size = struct.unpack("<4sI", data[i : i + 8])
        stop = i + 8 + size + (size & 1)  # chunks are padded to an even length
        if i + 8 + size > end:
            raise ValueError("damaged WebP file")
        yield kind, data[i : min(stop, end)]
        i = stop


def strip_webp(data: bytes, *, orientation: int = 1) -> bytes:
    chunks = [(k, c) for k, c in _webp_chunks(data) if k in WEBP_KEEP]
    if chunks and chunks[0][0] == b"VP8X":  # extended format: header flags list the extras
        header = bytearray(chunks[0][1])
        flags = header[8] & ~(_VP8X_EXIF | _VP8X_XMP)
        if orientation != 1:
            flags |= _VP8X_EXIF
            body = _exif_body(orientation)
            chunks.append((b"EXIF", struct.pack("<4sI", b"EXIF", len(body)) + body))
            if len(body) & 1:
                chunks[-1] = (b"EXIF", chunks[-1][1] + b"\x00")
        header[8] = flags
        chunks[0] = (b"VP8X", bytes(header))
    body = b"WEBP" + b"".join(c for _, c in chunks)
    return b"RIFF" + struct.pack("<I", len(body)) + body


# --- GIF -----------------------------------------------------------------------

# Application extensions that affect playback or colours: looping and the colour profile.
GIF_KEEP_APPS = (b"NETSCAPE2.0", b"ANIMEXTS1.0", b"ICCRGBG1012")


def _gif_sub_blocks(data: bytes, i: int) -> int:
    """Index just after a chain of data sub-blocks starting at ``i``."""
    while True:
        if i >= len(data):
            raise ValueError("damaged GIF file")
        size = data[i]
        i += 1 + size
        if size == 0:
            return i


def _gif_blocks(data: bytes):
    """Yield ``(kind, bytes)``; kind is "header", "image", "trailer" or the extension's name."""
    if data[:6] not in (b"GIF87a", b"GIF89a"):
        raise ValueError("not a GIF file")
    packed = data[10]
    i = 13 + (3 * 2 ** ((packed & 7) + 1) if packed & 0x80 else 0)
    yield "header", data[:i]
    while i < len(data):
        start = i
        kind = data[i]
        if kind == 0x3B:
            yield "trailer", b"\x3b"
            return
        if kind == 0x2C:  # image: descriptor, optional colour table, compressed pixels
            packed = data[i + 9]
            i += 10 + (3 * 2 ** ((packed & 7) + 1) if packed & 0x80 else 0)
            i = _gif_sub_blocks(data, i + 1)  # +1: LZW code size
            yield "image", data[start:i]
        elif kind == 0x21:
            label = data[i + 1]
            name = {0xF9: "frame timing", 0x01: "text", 0xFE: "comment"}.get(label, "unknown")
            if label == 0xFF:
                ident = data[i + 3 : i + 3 + data[i + 2]]
                name = "app " + ident.decode("latin-1", "replace")
                name = "keep" if ident in GIF_KEEP_APPS else name
            i = _gif_sub_blocks(data, i + 2)
            yield name, data[start:i]
        else:
            raise ValueError("damaged GIF file")
    yield "trailer", b"\x3b"  # cut-off file: end it properly


_GIF_KEEP = {"header", "image", "trailer", "frame timing", "text", "keep"}


def strip_gif(data: bytes, *, orientation: int = 1) -> bytes:
    return b"".join(block for kind, block in _gif_blocks(data) if kind in _GIF_KEEP)


def gif_metadata_blocks(data: bytes) -> list[str]:
    return [kind for kind, _ in _gif_blocks(data) if kind not in _GIF_KEEP]


# --- HEIC / AVIF -----------------------------------------------------------------
#
# These files keep EXIF and XMP as separate "items" whose bytes sit somewhere in the
# file, located through an index (the "iloc" box). Removing them would move other
# data and mean rewriting that index; instead their bytes are overwritten in place
# with an empty EXIF / XMP block of the same size. The picture data and every
# offset stay exactly as they were.

_XMP_TYPES = (b"application/rdf+xml", b"application/xmp+xml")
_EMPTY_XMP = (
    b'<?xpacket begin="" id="W5M0MpCehiHzreSzNTczkc9d"?><x:xmpmeta xmlns:x="adobe:ns:meta/"/>'
)
_XMP_END = b'<?xpacket end="w"?>'
# 4 bytes: where the TIFF header starts; "Exif\0\0"; an empty big-endian TIFF block
_EMPTY_EXIF = b"\x00\x00\x00\x06Exif\x00\x00" + b"MM\x00\x2a\x00\x00\x00\x08" + b"\x00" * 6


def _boxes(data: bytes, start: int, end: int):
    """Yield ``(type, payload_start, box_end)`` for the boxes between ``start`` and ``end``."""
    i = start
    while i + 8 <= end:
        size, kind = struct.unpack(">I4s", data[i : i + 8])
        header = 8
        if size == 1:
            size = struct.unpack(">Q", data[i + 8 : i + 16])[0]
            header = 16
        elif size == 0:
            size = end - i
        if size < header or i + size > end:
            raise ValueError("damaged HEIC/AVIF file")
        yield kind, i + header, i + size
        i += size


def _read_uint(data: bytes, i: int, size: int) -> tuple[int, int]:
    return (int.from_bytes(data[i : i + size], "big") if size else 0), i + size


def _metadata_items(data: bytes) -> list[tuple[str, list[tuple[int, int]]]]:
    """``("exif" | "xmp", [(file offset, length), ...])`` for every metadata item."""
    meta = next(((s, e) for k, s, e in _boxes(data, 0, len(data)) if k == b"meta"), None)
    if meta is None:
        raise ValueError("not a HEIC/AVIF file")
    children = {k: (s, e) for k, s, e in _boxes(data, meta[0] + 4, meta[1])}  # +4: version

    kinds: dict[int, str] = {}
    if b"iinf" in children:
        s, e = children[b"iinf"]
        first = s + (6 if data[s] == 0 else 8)  # version, flags, entry count
        for kind, ps, pe in _boxes(data, first, e):
            if kind != b"infe" or data[ps] < 2:
                continue
            id_size = 2 if data[ps] == 2 else 4
            item_id, i = _read_uint(data, ps + 4, id_size)
            item_type = data[i + 2 : i + 6]
            rest = data[i + 6 : pe].split(b"\x00")
            if item_type == b"Exif":
                kinds[item_id] = "exif"
            elif item_type == b"mime" and len(rest) > 1 and rest[1] in _XMP_TYPES:
                kinds[item_id] = "xmp"
    if not kinds:
        return []

    s, e = children.get(b"iloc", (0, 0))
    if not s:
        raise ValueError("damaged HEIC/AVIF file")
    idat = children.get(b"idat", (0, 0))[0]
    version = data[s]
    offset_size, length_size = data[s + 4] >> 4, data[s + 4] & 15
    base_size, index_size = data[s + 5] >> 4, (data[s + 5] & 15 if version else 0)
    count, i = _read_uint(data, s + 6, 4 if version == 2 else 2)
    found = []
    for _ in range(count):
        item_id, i = _read_uint(data, i, 4 if version == 2 else 2)
        method = 0
        if version in (1, 2):
            method, i = _read_uint(data, i, 2)
            method &= 15
        i += 2  # data reference index
        base, i = _read_uint(data, i, base_size)
        extents, i = _read_uint(data, i, 2)
        spans = []
        for _ in range(extents):
            _, i = _read_uint(data, i, index_size)
            offset, i = _read_uint(data, i, offset_size)
            length, i = _read_uint(data, i, length_size)
            spans.append((base + offset + (idat if method == 1 else 0), length))
        if item_id in kinds:
            if method not in (0, 1) or (method == 1 and not idat):
                raise ValueError("unsupported HEIC/AVIF layout")
            if any(length == 0 or off + length > len(data) for off, length in spans):
                raise ValueError("damaged HEIC/AVIF file")
            found.append((kinds[item_id], spans))
    if i > e:
        raise ValueError("damaged HEIC/AVIF file")
    return found


def strip_heif(data: bytes, *, orientation: int = 1) -> bytes:
    """Blank the EXIF and XMP items. HEIC/AVIF keep the orientation in their own image
    properties, not in EXIF, so the picture stays upright without EXIF."""
    out = bytearray(data)
    for kind, spans in _metadata_items(data):
        total = sum(length for _, length in spans)
        if kind == "exif":
            replacement = _EMPTY_EXIF if total >= len(_EMPTY_EXIF) else b""
        else:
            replacement = _EMPTY_XMP + b" " * (total - len(_EMPTY_XMP) - len(_XMP_END)) + _XMP_END
            replacement = replacement if total >= len(_EMPTY_XMP) + len(_XMP_END) else b""
        replacement = replacement.ljust(total, b"\x00" if kind == "exif" else b" ")
        pos = 0
        for offset, length in spans:
            out[offset : offset + length] = replacement[pos : pos + length]
            pos += length
    return bytes(out)


def heif_metadata_items(data: bytes) -> list[str]:
    return [kind for kind, _ in _metadata_items(data)]


# --- TIFF ----------------------------------------------------------------------

# Compression methods Pillow can write again without any loss.
_TIFF_LOSSLESS = {"raw", "tiff_lzw", "tiff_adobe_deflate", "tiff_deflate", "packbits", "group3",
                  "group4", "tiff_ccitt"}  # fmt: skip


def strip_tiff(data: bytes, *, orientation: int = 1) -> bytes:
    """Rewrite the TIFF with only the tags needed to show the picture (Pillow writes
    those itself), its colour profile and resolution. All pages are kept.

    Pillow already turns pages upright while reading them, so pass ``orientation=1``
    for files read with Pillow (``metadata.clean_bytes`` does)."""
    from PIL import Image, ImageSequence

    with Image.open(io.BytesIO(data)) as im:
        compression = im.info.get("compression", "raw")
        if compression not in _TIFF_LOSSLESS:
            raise ValueError(
                f"this TIFF uses {compression.upper()} compression. Cleaning it changes the picture"
            )
        pages = []
        for frame in ImageSequence.Iterator(im):
            page = frame.copy()  # a plain image: none of the file's tags come along
            page.info = {}
            settings = {"compression": frame.info.get("compression", compression)}
            if frame.info.get("icc_profile"):
                settings["icc_profile"] = frame.info["icc_profile"]
            if frame.info.get("dpi"):
                settings["dpi"] = frame.info["dpi"]
            if orientation != 1:
                settings["tiffinfo"] = {0x0112: orientation}
            pages.append((page, settings))
    buf = io.BytesIO()
    first, settings = pages[0]
    if len(pages) > 1:
        # Pillow applies the first page's settings to all pages.
        settings = {**settings, "save_all": True, "append_images": [p for p, _ in pages[1:]]}
    first.save(buf, format="TIFF", **settings)
    return buf.getvalue()
