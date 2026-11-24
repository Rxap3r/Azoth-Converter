"""Removing photo metadata: everything private goes, the picture stays exactly the same."""

from __future__ import annotations

import io
import struct

import pytest
from PIL import Image, ImageSequence, PngImagePlugin

from azoth import metadata
from azoth.cli import main as cli
from azoth.converters import ConversionError, strip
from azoth.converters.images import AVIF_SUPPORTED, HEIF_SUPPORTED

SECRETS = (b"SecretCamera", b"SecretAuthor", b"SecretComment", b"SecretTrailer", b"SecretPlace")
XMP = (
    '<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF '
    'xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"><rdf:Description '
    'xmlns:dc="http://purl.org/dc/elements/1.1/" dc:creator="SecretAuthor"/>'
    "</rdf:RDF></x:xmpmeta>"
)


def private_exif(orientation: int | None = None) -> bytes:
    exif = Image.Exif()
    exif[0x010F] = "SecretCamera"
    exif[0x013B] = "SecretAuthor"
    exif.get_ifd(0x8825).update({1: "N", 2: (47.0, 22.0, 10.0), 3: "E", 4: (8.0, 32.0, 0.0)})
    exif.get_ifd(0x8769)[0x9003] = "2026:01:01 10:00:00"
    if orientation:
        exif[0x0112] = orientation
    return exif.tobytes()


def picture(size=(64, 48)) -> Image.Image:
    img = Image.new("RGB", size, "blue")
    img.paste(Image.new("RGB", (size[0], size[1] // 2), "red"))
    return img


def make(fmt: str, orientation: int | None = None) -> bytes:
    img, exif, buf = picture(), private_exif(orientation), io.BytesIO()
    if fmt == "jpg":
        img.save(buf, "JPEG", exif=exif, comment=b"SecretComment", xmp=XMP.encode(), quality=90)
        return buf.getvalue() + b"\xff\xd8SecretTrailer"  # e.g. a motion-photo video
    if fmt == "png":
        info = PngImagePlugin.PngInfo()
        info.add_text("Author", "SecretAuthor")
        info.add_itxt("XML:com.adobe.xmp", XMP)
        img.save(buf, "PNG", exif=exif, pnginfo=info)
    elif fmt == "webp":
        img.save(buf, "WEBP", exif=exif, xmp=XMP.encode(), quality=80)
    elif fmt == "gif":
        frames = [img.convert("P"), img.rotate(180).convert("P")]
        frames[0].save(
            buf, "GIF", save_all=True, append_images=frames[1:], duration=200, loop=0,
            comment=b"SecretComment",
        )  # fmt: skip
    elif fmt == "tiff":
        img.save(buf, "TIFF", exif=exif)
    elif fmt in ("heic", "avif"):
        img.save(buf, "HEIF" if fmt == "heic" else "AVIF", exif=exif, xmp=XMP.encode(), quality=80)
    return buf.getvalue()


FORMATS = [
    "jpg",
    "png",
    "webp",
    "gif",
    "tiff",
    pytest.param("heic", marks=pytest.mark.skipif(not HEIF_SUPPORTED, reason="no HEIC")),
    pytest.param("avif", marks=pytest.mark.skipif(not AVIF_SUPPORTED, reason="no AVIF")),
]


def pixels(data: bytes) -> list[bytes]:
    with Image.open(io.BytesIO(data)) as im:
        return [ImageSequence_frame.tobytes() for ImageSequence_frame in ImageSequence.Iterator(im)]


@pytest.mark.parametrize("fmt", FORMATS)
def test_private_data_removed_and_picture_unchanged(fmt):
    original = make(fmt)
    found = {f.label for f in metadata.inspect_bytes(fmt, original)}
    assert found  # there was something to remove
    cleaned = metadata.clean_bytes(fmt, original)
    for secret in SECRETS:
        assert secret not in cleaned
    assert metadata.inspect_bytes(fmt, cleaned) == []
    assert pixels(cleaned) == pixels(original)


@pytest.mark.parametrize("fmt", ["jpg", "png", "webp", "tiff"])
def test_inspect_lists_location_and_camera(fmt):
    found = {f.label: f.detail for f in metadata.inspect_bytes(fmt, make(fmt))}
    assert found["Location (GPS)"] == "47.36944° N, 8.53333° E"
    assert found["Camera"] == "SecretCamera"
    assert found["Owner / author"] == "SecretAuthor"
    assert found["Date taken"] == "2026:01:01 10:00:00"


def test_inspect_lists_jpeg_extras():
    found = {f.label for f in metadata.inspect_bytes("jpg", make("jpg"))}
    assert {"XMP data", "Comment", "Extra data"} <= found


@pytest.mark.parametrize("fmt", ["jpg", "png", "webp", "tiff"])
def test_rotated_photo_stays_upright(fmt):
    original = make(fmt, orientation=6)
    cleaned = metadata.clean_bytes(fmt, original)
    with Image.open(io.BytesIO(original)) as a, Image.open(io.BytesIO(cleaned)) as b:
        from PIL import ImageOps

        shown_a, shown_b = ImageOps.exif_transpose(a), ImageOps.exif_transpose(b)
        assert shown_a.size == shown_b.size == (48, 64)
        assert shown_a.tobytes() == shown_b.tobytes()
        if fmt != "tiff":  # TIFF pages are saved upright, without an orientation tag
            assert dict(b.getexif()) == {0x0112: 6}  # only the orientation is left


def test_animated_gif_keeps_frames_and_looping():
    cleaned = metadata.clean_bytes("gif", make("gif"))
    with Image.open(io.BytesIO(cleaned)) as im:
        assert im.n_frames == 2
        assert im.info.get("loop") == 0
        assert im.info.get("duration") == 200
        assert "comment" not in im.info


def test_gif_xmp_application_block_removed():
    data = make("gif")
    xmp_block = b"\x21\xff\x0bXMP DataXMP" + bytes([12]) + b"SecretAuthor" + b"\x00"
    with_xmp = data[:-1] + xmp_block + b"\x3b"
    assert strip.gif_metadata_blocks(with_xmp) == ["comment", "app XMP DataXMP"]
    cleaned = metadata.clean_bytes("gif", with_xmp)
    assert b"SecretAuthor" not in cleaned and b"NETSCAPE2.0" in cleaned


def test_multi_page_lzw_tiff(tmp_path):
    pages = [picture(), picture().rotate(180)]
    buf = io.BytesIO()
    pages[0].save(
        buf, "TIFF", save_all=True, append_images=pages[1:], compression="tiff_lzw",
        tiffinfo={315: "SecretAuthor", 270: "SecretPlace"},
    )  # fmt: skip
    original = buf.getvalue()
    cleaned = metadata.clean_bytes("tiff", original)
    assert b"SecretAuthor" not in cleaned and b"SecretPlace" not in cleaned
    assert pixels(cleaned) == pixels(original)
    with Image.open(io.BytesIO(cleaned)) as im:
        assert im.n_frames == 2
        assert im.info["compression"] == "tiff_lzw"


def test_jpeg_compressed_tiff_is_refused(tmp_path):
    src = tmp_path / "scan.tif"
    picture().save(src, "TIFF", compression="jpeg", tiffinfo={315: "SecretAuthor"})
    with pytest.raises(ConversionError, match="changes the picture"):
        metadata.clean_file(src, tmp_path / "out")
    assert not (tmp_path / "out").exists() or not any((tmp_path / "out").iterdir())


@pytest.mark.skipif(not HEIF_SUPPORTED, reason="no HEIC")
def test_heic_cleaned_in_place_keeps_size():
    original = make("heic")
    cleaned = metadata.clean_bytes("heic", original)
    assert len(cleaned) == len(original)  # nothing moved: only metadata bytes blanked
    assert strip.heif_metadata_items(original) == ["exif", "xmp"]
    with Image.open(io.BytesIO(cleaned)) as im:
        assert not im.getexif().get_ifd(0x8825)
        assert b"rdf:" not in (im.info.get("xmp") or b"")


def test_clean_file_names_and_never_overwrites(tmp_path):
    src = tmp_path / "IMG_0001.jpg"
    src.write_bytes(make("jpg"))
    before = src.read_bytes()

    first = metadata.clean_file(src)
    assert first.output == tmp_path / "IMG_0001 (clean).jpg"
    assert {f.label for f in first.removed} >= {"Location (GPS)", "Camera"}
    second = metadata.clean_file(src)
    assert second.output == tmp_path / "IMG_0001 (clean) (1).jpg"

    other = metadata.clean_file(src, tmp_path / "to share")
    assert other.output == tmp_path / "to share" / "IMG_0001.jpg"  # same name elsewhere
    assert src.read_bytes() == before  # the original is never changed

    named = metadata.clean_file(src, name="For Anna")
    assert named.output == tmp_path / "For Anna.jpg"
    with pytest.raises(ConversionError):
        metadata.clean_file(src, name="../up")


def test_clean_file_overwrite_replaces_old_copy_only(tmp_path):
    src = tmp_path / "photo.jpg"
    src.write_bytes(make("jpg"))
    old = tmp_path / "photo (clean).jpg"
    old.write_bytes(b"old")
    result = metadata.clean_file(src, overwrite=True)
    assert result.output == old and old.read_bytes() != b"old"
    # Even with overwrite, the original can't be replaced (same folder and same name).
    result = metadata.clean_file(src, tmp_path, overwrite=True)
    assert result.output == old


def test_wrong_extension_is_detected_by_content(tmp_path):
    src = tmp_path / "photo.dat"
    src.write_bytes(make("png"))
    result = metadata.clean_file(src)
    assert result.output.name == "photo (clean).png"


def test_unsupported_files_are_refused(tmp_path):
    notes = tmp_path / "notes.txt"
    notes.write_text("plain text")
    with pytest.raises(ConversionError, match="photos and images"):
        metadata.clean_file(notes)
    with pytest.raises(ConversionError, match="Cannot find the file"):
        metadata.clean_file(tmp_path / "missing.jpg")


def test_nothing_is_saved_if_the_picture_would_change(tmp_path, monkeypatch):
    src = tmp_path / "photo.png"
    src.write_bytes(make("png"))

    def broken(data, *, orientation=1):
        img = Image.new("RGB", (64, 48), "green")
        buf = io.BytesIO()
        img.save(buf, "PNG")
        return buf.getvalue()

    monkeypatch.setitem(metadata._STRIPPERS, "png", broken)
    with pytest.raises(ConversionError, match="without a change to the picture"):
        metadata.clean_file(src)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["photo.png"]


def test_nothing_is_saved_if_metadata_is_left(tmp_path, monkeypatch):
    src = tmp_path / "photo.png"
    src.write_bytes(make("png"))
    monkeypatch.setitem(metadata._STRIPPERS, "png", lambda data, orientation=1: data)
    with pytest.raises(ConversionError, match="cannot remove some metadata"):
        metadata.clean_file(src)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["photo.png"]


def test_damaged_files_give_a_readable_error(tmp_path):
    src = tmp_path / "broken.webp"
    data = bytearray(make("webp"))
    data[16:20] = struct.pack("<I", 10**6)  # a chunk claims to be far too big
    src.write_bytes(bytes(data))
    with pytest.raises(ConversionError):
        metadata.clean_file(src)


def test_cli_clean_and_show(tmp_path, capsys):
    src = tmp_path / "photo.jpg"
    src.write_bytes(make("jpg"))
    assert cli(["clean", "--show", str(src)]) == 0
    shown = capsys.readouterr().out
    assert "Location (GPS): 47.36944° N, 8.53333° E" in shown
    assert sorted(p.name for p in tmp_path.iterdir()) == ["photo.jpg"]  # --show changes nothing

    assert cli(["clean", str(src), "-o", str(tmp_path / "out")]) == 0
    assert "removed: Location (GPS)" in capsys.readouterr().out
    assert cli(["clean", "--show", str(tmp_path / "out" / "photo.jpg")]) == 0
    assert "no metadata found" in capsys.readouterr().out


def test_cli_clean_reports_failures(tmp_path, capsys):
    notes = tmp_path / "notes.txt"
    notes.write_text("plain text")
    assert cli(["clean", str(notes)]) == 1
    assert "photos and images" in capsys.readouterr().err


def test_orientation_alone_is_not_reported():
    exif = Image.Exif()
    exif[0x0112] = 6
    buf = io.BytesIO()
    picture().save(buf, "JPEG", exif=exif.tobytes())
    assert metadata.inspect_bytes("jpg", buf.getvalue()) == []


def test_unnamed_blocks_are_reported_as_other_hidden_data():
    buf = io.BytesIO()
    picture().save(buf, "PNG")
    data = buf.getvalue()
    stamp = strip._png_chunk(b"tIME", b"\x07\xea\x01\x01\x0a\x00\x00")  # when it was edited
    data = data[:33] + stamp + data[33:]  # right after IHDR
    assert [f.label for f in metadata.inspect_bytes("png", data)] == ["Other hidden data"]
    assert b"tIME" not in metadata.clean_bytes("png", data)
