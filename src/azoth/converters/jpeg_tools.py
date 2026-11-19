"""Lossless JPEG helpers: remove metadata without touching the picture data."""

from __future__ import annotations

# Segments that carry metadata. Kept: APP0 (JFIF, without its preview picture),
# APP2 (only the ICC colour profile) and APP14 (Adobe colour transform): they affect
# how the picture looks.
_METADATA_MARKERS = {
    0xE1,  # APP1: EXIF (camera, date, GPS) and XMP
    0xE3, 0xE4, 0xE5, 0xE6, 0xE7, 0xE8, 0xE9, 0xEA, 0xEB, 0xEC,  # APP3-12: vendor data
    0xED,  # APP13: Photoshop / IPTC (captions, author, location)
    0xEF,  # APP15
    0xFE,  # COM: free-text comment
}  # fmt: skip


def _segments(data: bytes):
    """Yield ``(marker, segment_bytes)`` for every part of a JPEG up to its end marker.

    ``segment_bytes`` includes the marker itself. The compressed picture data after a
    start-of-scan marker is part of that scan's segment. Raises ``ValueError`` for
    damaged files. Anything after the end-of-image marker is not yielded.
    """
    if data[:2] != b"\xff\xd8":
        raise ValueError("not a JPEG file")
    yield 0xD8, b"\xff\xd8"
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
            yield 0xD9, b"\xff\xd9"
            return
        if marker == 0x01 or 0xD0 <= marker <= 0xD7:  # markers without a length
            yield marker, bytes((0xFF, marker))
            continue
        if i + 2 > n:
            raise ValueError("damaged JPEG file")
        length = int.from_bytes(data[i : i + 2], "big")
        end = i + length
        if length < 2 or end > n:
            raise ValueError("damaged JPEG file")
        if marker == 0xDA:  # start of scan: compressed data follows until the next marker
            while end < n - 1:
                nxt = data[end + 1]
                if data[end] == 0xFF and nxt != 0x00 and not 0xD0 <= nxt <= 0xD7 and nxt != 0xFF:
                    break  # a real marker (0x00 = escaped byte, D0-D7 = restart markers)
                end += 1
            else:
                end = n
        yield marker, bytes((0xFF, marker)) + data[i:end]
        i = end
    # No end marker: a cut-off file. Viewers still show what's there, so we do too.


def _keep(marker: int, segment: bytes) -> bytes | None:
    """The segment to write, possibly shortened, or None to drop it."""
    if marker in _METADATA_MARKERS:
        return None
    payload = segment[4:]
    if marker == 0xE0:  # APP0
        if not payload.startswith(b"JFIF\x00") or len(payload) < 14:
            return None  # JFXX: a preview picture
        if payload[12] or payload[13]:  # JFIF with an embedded preview picture
            body = payload[:12] + b"\x00\x00"
            return b"\xff\xe0" + (len(body) + 2).to_bytes(2, "big") + body
    if marker == 0xE2 and not payload.startswith(b"ICC_PROFILE\x00"):
        return None  # e.g. MPF (index of extra pictures) or FlashPix data
    return segment


def exif_orientation_segment(orientation: int) -> bytes:
    """An APP1 segment with an EXIF block that holds only the picture's orientation."""
    from PIL import Image

    exif = Image.Exif()
    exif[0x0112] = orientation
    body = exif.tobytes()  # starts with "Exif\0\0"
    return b"\xff\xe1" + (len(body) + 2).to_bytes(2, "big") + body


def strip_jpeg_metadata(data: bytes, *, orientation: int = 1) -> bytes:
    """Return the JPEG without EXIF/GPS/XMP/IPTC/comments, preview pictures and any
    data appended after the picture (extra images, motion-photo videos).

    The compressed picture data is copied byte for byte, so there is no quality loss
    at all. With an ``orientation`` other than 1, a minimal EXIF block that holds only
    the orientation is written, so the picture is still shown the right way up.
    """
    kept = [s for m, segment in _segments(data) if (s := _keep(m, segment)) is not None]
    if orientation != 1:
        position = 2 if kept[1].startswith(b"\xff\xe0") else 1  # after SOI and JFIF
        kept.insert(position, exif_orientation_segment(orientation))
    return b"".join(kept)


def has_data_after_image(data: bytes) -> bool:
    """True if something (e.g. a second picture or a video) follows the picture's end."""
    size = sum(len(segment) for _, segment in _segments(data))
    return len(data.rstrip(b"\x00")) > size  # some cameras pad with zero bytes


def removed_segments(data: bytes) -> list[tuple[int, bytes]]:
    """``(marker, segment)`` for the segments :func:`strip_jpeg_metadata` drops or shortens."""
    return [(m, segment) for m, segment in _segments(data) if _keep(m, segment) != segment]
