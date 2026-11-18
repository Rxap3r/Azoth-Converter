"""Lossless JPEG helpers: remove metadata without touching the picture data."""

from __future__ import annotations

# Segments that carry metadata. Kept: APP0 (JFIF), APP2 (ICC colour profile),
# APP14 (Adobe colour transform): they affect how the picture looks.
_METADATA_MARKERS = {
    0xE1,  # APP1: EXIF (camera, date, GPS) and XMP
    0xE3, 0xE4, 0xE5, 0xE6, 0xE7, 0xE8, 0xE9, 0xEA, 0xEB, 0xEC,  # APP3-12: vendor data
    0xED,  # APP13: Photoshop / IPTC (captions, author, location)
    0xEF,  # APP15
    0xFE,  # COM: free-text comment
}  # fmt: skip


def strip_jpeg_metadata(data: bytes) -> bytes:
    """Return the JPEG without EXIF/GPS/XMP/IPTC/comments. The image data is copied
    byte for byte, so there is no quality loss at all."""
    if data[:2] != b"\xff\xd8":
        raise ValueError("not a JPEG file")
    out = bytearray(b"\xff\xd8")
    i = 2
    n = len(data)
    while i < n:
        if data[i] != 0xFF:
            raise ValueError("damaged JPEG file")
        while i < n and data[i] == 0xFF:  # fill bytes
            i += 1
        if i >= n:
            break
        marker = data[i]
        i += 1
        if marker == 0xD9:  # end of image
            out += b"\xff\xd9"
            break
        if marker == 0x01 or 0xD0 <= marker <= 0xD7:  # markers without a length
            out += bytes((0xFF, marker))
            continue
        if i + 2 > n:
            raise ValueError("damaged JPEG file")
        length = int.from_bytes(data[i : i + 2], "big")
        segment = data[i : i + length]
        if marker == 0xDA:  # start of scan: the rest is compressed picture data
            out += bytes((0xFF, marker)) + data[i:]
            break
        if marker not in _METADATA_MARKERS:
            out += bytes((0xFF, marker)) + segment
        i += length
    return bytes(out)
