"""Conversions should be as close to 1:1 as possible. These tests check that."""

import io

import pymupdf
import pytest
from PIL import Image, ImageChops

from azoth.converters.jpeg_tools import strip_jpeg_metadata
from azoth.engine import Engine


def _two_colour_photo(path, orientation=None):
    """Displays red on top, blue at the bottom (after applying EXIF orientation)."""
    shown = Image.new("RGB", (400, 300), "blue")
    shown.paste(Image.new("RGB", (400, 150), "red"), (0, 0))
    exif = Image.Exif()
    exif[0x010F] = "SecretCamera"
    exif.get_ifd(0x8825)[2] = (47.0, 22.0, 0.0)  # GPS latitude
    stored = shown
    if orientation == 6:  # stored sideways; viewers rotate 90° clockwise
        stored = shown.rotate(90, expand=True)
        exif[0x0112] = 6
    stored.save(path, quality=95, exif=exif)
    return path


def test_strip_jpeg_metadata_is_lossless(tmp_path):
    src = _two_colour_photo(tmp_path / "p.jpg")
    clean = strip_jpeg_metadata(src.read_bytes())
    with Image.open(io.BytesIO(clean)) as a, Image.open(src) as b:
        assert a.getexif() == {} or 0x8825 not in a.getexif()
        assert ImageChops.difference(a.convert("RGB"), b.convert("RGB")).getbbox() is None
    assert b"SecretCamera" not in clean


def test_jpg_to_pdf_embeds_photo_unchanged(tmp_path):
    src = _two_colour_photo(tmp_path / "p.jpg")
    [pdf] = Engine().convert(src, "pdf", tmp_path / "o").outputs
    with pymupdf.open(pdf) as doc:
        embedded = doc.extract_image(doc[0].get_images()[0][0])["image"]
    assert embedded == strip_jpeg_metadata(src.read_bytes())  # no re-compression
    assert b"SecretCamera" not in pdf.read_bytes()  # metadata gone


def test_jpg_to_pdf_keeps_metadata_when_asked(tmp_path):
    src = _two_colour_photo(tmp_path / "p.jpg")
    [pdf] = Engine().convert(src, "pdf", tmp_path / "o", options={"keep_metadata": True}).outputs
    with pymupdf.open(pdf) as doc:
        embedded = doc.extract_image(doc[0].get_images()[0][0])["image"]
    assert embedded == src.read_bytes()


def test_rotated_phone_photo_is_upright_in_pdf(tmp_path):
    src = _two_colour_photo(tmp_path / "p.jpg", orientation=6)
    [pdf] = Engine().convert(src, "pdf", tmp_path / "o").outputs
    with pymupdf.open(pdf) as doc:
        page = doc[0]
        assert page.rect.width > page.rect.height  # landscape, like the photo is shown
        pix = page.get_pixmap(dpi=36)
        top = pix.pixel(pix.width // 2, 2)
        bottom = pix.pixel(pix.width // 2, pix.height - 3)
    assert top[0] > 200 and top[2] < 60  # red on top
    assert bottom[2] > 200 and bottom[0] < 60  # blue at the bottom


def test_png_to_pdf_is_lossless_and_keeps_transparency(sample_png, tmp_path):
    [pdf] = Engine().convert(sample_png, "pdf", tmp_path / "o").outputs
    with pymupdf.open(pdf) as doc:
        xref = doc[0].get_images()[0][0]
        info = doc.extract_image(xref)
        assert info["smask"] > 0  # transparency stored
        pix = pymupdf.Pixmap(doc, xref)
        stored = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    with Image.open(sample_png) as original:
        # Compare the visible part; fully transparent pixels have no meaningful colour.
        visible = (40, 0, original.width, original.height)
        diff = ImageChops.difference(original.convert("RGB").crop(visible), stored.crop(visible))
        assert diff.getbbox() is None


@pytest.mark.parametrize("src_format", ["PNG", "BMP", "TIFF"])
def test_lossless_source_to_webp_is_pixel_perfect(tmp_path, src_format):
    src = tmp_path / f"img.{src_format.lower()}"
    img = Image.new("RGB", (64, 64))
    img.putdata([(x * 4, y * 4, (x * y) % 256) for y in range(64) for x in range(64)])
    img.save(src, format=src_format)
    [out] = Engine().convert(src, "webp", tmp_path / "o").outputs
    with Image.open(out) as converted:
        assert ImageChops.difference(img, converted.convert("RGB")).getbbox() is None


def test_pdf_to_image_default_is_print_quality(sample_pdf, tmp_path):
    result = Engine().convert(sample_pdf, "png", tmp_path / "o")
    with Image.open(result.outputs[0]) as im:
        width, height = im.size
        assert abs(width - 2480) <= 1 and abs(height - 3508) <= 1  # A4 at 300 DPI


def test_quality_levels_and_limits():
    from azoth import quality

    assert quality.resolve_options({}) == {"level": "maximum", "quality": 95, "dpi": 300}
    compact = quality.resolve_options({"level": "compact"})
    assert compact["quality"] >= quality.MIN_IMAGE_QUALITY and compact["dpi"] >= quality.MIN_DPI
    # Too-low values are raised to the minimum, never accepted.
    low = quality.resolve_options({"quality": 10, "dpi": 30})
    assert low["quality"] == quality.MIN_IMAGE_QUALITY and low["dpi"] == quality.MIN_DPI
    assert quality.resolve_options({"level": "nonsense"})["level"] == "maximum"


def test_cli_rejects_too_low_quality(sample_png, tmp_path, capsys):
    from azoth.cli import main

    with pytest.raises(SystemExit):
        main(["convert", str(sample_png), "--to", "jpg", "--quality", "20"])
    assert "between 75 and 100" in capsys.readouterr().err
    assert (
        main(
            [
                "convert",
                str(sample_png),
                "--to",
                "jpg",
                "--level",
                "compact",
                "-o",
                str(tmp_path),
                "-q",
            ]
        )
        == 0
    )


def test_lower_level_gives_smaller_photo(tmp_path):
    src = tmp_path / "photo.png"
    img = Image.new("RGB", (400, 300))
    pixels = [(x * y % 256, x * 3 % 256, y * 5 % 256) for y in range(300) for x in range(400)]
    img.putdata(pixels)
    img.save(src)
    [best] = Engine().convert(src, "jpg", tmp_path / "a", options={"level": "maximum"}).outputs
    [small] = Engine().convert(src, "jpg", tmp_path / "b", options={"level": "compact"}).outputs
    assert small.stat().st_size < best.stat().st_size
