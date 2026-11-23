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


# --- removing photo metadata (azoth clean) ---------------------------------------


def _part(data: bytes, start: bytes, end: bytes | None = None) -> bytes:
    i = data.index(start)
    return data[i : data.index(end, i) + len(end)] if end else data[i:]


def test_clean_jpeg_keeps_compressed_picture_byte_for_byte(tmp_path):
    from azoth import metadata

    src = _two_colour_photo(tmp_path / "p.jpg", orientation=6)
    original = src.read_bytes()
    cleaned = metadata.clean_bytes("jpg", original)
    # Everything from the first quantisation table to the end marker is the picture.
    assert _part(cleaned, b"\xff\xdb") == _part(original, b"\xff\xdb")
    assert b"SecretCamera" not in cleaned
    with Image.open(io.BytesIO(cleaned)) as im:
        assert dict(im.getexif()) == {0x0112: 6}  # still shown upright


def test_clean_png_and_webp_keep_picture_data_byte_for_byte():
    from azoth import metadata
    from azoth.converters import strip

    exif = Image.Exif()
    exif[0x010F] = "SecretCamera"
    img = Image.new("RGBA", (50, 40), (10, 200, 30, 128))
    for fmt, chunks, picture_kinds in (
        ("png", strip._png_chunks, {b"IDAT"}),
        ("webp", strip._webp_chunks, {b"ALPH", b"VP8 ", b"VP8L"}),
    ):
        buf = io.BytesIO()
        img.save(buf, fmt, exif=exif.tobytes())
        original = buf.getvalue()
        cleaned = metadata.clean_bytes(fmt, original)
        assert b"SecretCamera" not in cleaned
        before = [c for k, c in chunks(original) if k in picture_kinds]
        after = [c for k, c in chunks(cleaned) if k in picture_kinds]
        assert before and after == before, fmt


def test_clean_keeps_colour_profile():
    from PIL import ImageCms

    from azoth import metadata

    icc = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
    exif = Image.Exif()
    exif[0x010F] = "SecretCamera"
    for fmt in ("JPEG", "PNG", "WEBP", "TIFF"):
        buf = io.BytesIO()
        Image.new("RGB", (20, 20), "red").save(buf, fmt, exif=exif.tobytes(), icc_profile=icc)
        cleaned = metadata.clean_bytes({"JPEG": "jpg"}.get(fmt, fmt.lower()), buf.getvalue())
        with Image.open(io.BytesIO(cleaned)) as im:
            assert im.info.get("icc_profile") == icc, fmt


def test_jpg_to_pdf_drops_data_hidden_after_the_photo(tmp_path):
    src = _two_colour_photo(tmp_path / "p.jpg")
    src.write_bytes(src.read_bytes() + b"\xff\xd8SecretTrailer")  # e.g. motion-photo video
    [pdf] = Engine().convert(src, "pdf", tmp_path / "o").outputs
    with pymupdf.open(pdf) as doc:
        embedded = doc.extract_image(doc[0].get_images()[0][0])["image"]
    assert b"SecretTrailer" not in embedded
    assert embedded.endswith(b"\xff\xd9")


# --- PDF tools (merge, split, edit pages) -------------------------------------------


def test_pdf_tools_copy_pages_without_redrawing(tmp_path):
    from azoth import pdf_tools

    src = tmp_path / "photos.pdf"
    doc = pymupdf.open()
    for colour in ((200, 30, 30), (30, 160, 60)):
        buf = io.BytesIO()
        Image.new("RGB", (300, 200), colour).save(buf, "JPEG", quality=92)
        page = doc.new_page()
        page.insert_text((72, 60), "Holiday", fontsize=18)
        page.insert_image(pymupdf.Rect(72, 80, 372, 280), stream=buf.getvalue())
    doc.save(src)
    doc.close()

    def pages(path):
        with pymupdf.open(path) as d:
            return [
                (p.read_contents(), [d.extract_image(x[0])["image"] for x in p.get_images()])
                for p in d
            ]

    original = pages(src)
    edited = pdf_tools.edit_pages(
        src, tmp_path / "e.pdf", [pdf_tools.PageEdit(1, 90), pdf_tools.PageEdit(0)]
    )
    assert pages(edited) == [original[1], original[0]]  # same drawing, same photo bytes
    merged = pdf_tools.merge([src, src], tmp_path / "m.pdf")
    assert pages(merged) == original * 2
    [part] = pdf_tools.split(src, tmp_path / "s", [[1]])
    assert pages(part) == [original[1]]


# --- Compress PDF ------------------------------------------------------------------


def test_compress_levels_respect_the_minimums():
    from azoth.quality import COMPRESS_LEVELS, MIN_DPI, MIN_IMAGE_QUALITY

    assert COMPRESS_LEVELS[0].dpi == 0  # the lightest level never touches pictures
    for level in COMPRESS_LEVELS[1:]:
        assert level.dpi >= MIN_DPI and level.image_quality >= MIN_IMAGE_QUALITY
        assert level.threshold_dpi > level.dpi


@pytest.mark.parametrize("level", ["balanced", "strong"])
def test_compressed_pictures_never_drop_below_the_level_dpi(tmp_path, level):
    """Even compressing again and again never makes pictures blurrier than promised."""
    from azoth import pdf_tools
    from azoth.quality import COMPRESS_BY_ID

    target = COMPRESS_BY_ID[level].dpi
    src = tmp_path / "photos.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    for i, px in enumerate((600, 1000, 1500, 2200, 4000)):
        buf = io.BytesIO()
        Image.effect_noise((px, px), 60).convert("RGB").save(buf, "JPEG", quality=95)
        page.insert_image(pymupdf.Rect(20 + i * 110, 50, 120 + i * 110, 150), stream=buf.getvalue())
    doc.save(src)
    doc.close()
    current = src
    for n in range(3):
        try:
            current = pdf_tools.compress(current, tmp_path / f"c{n}.pdf", level)
        except pdf_tools.NotSmaller:
            break
        with pymupdf.open(current) as result:
            for info in result[0].get_image_info():
                width_inch = (info["bbox"][2] - info["bbox"][0]) / 72
                assert info["width"] / width_inch >= target - 1


def test_compress_keeps_small_jpg_photos_byte_for_byte(tmp_path):
    """Photos that are not reduced in size are not re-saved as a worse JPG either."""
    from azoth import pdf_tools

    src = tmp_path / "mixed.pdf"
    small = io.BytesIO()
    Image.effect_noise((300, 200), 60).convert("RGB").save(small, "JPEG", quality=92)
    big = io.BytesIO()
    Image.effect_noise((3000, 2000), 60).convert("RGB").save(big, "JPEG", quality=95)
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_image(pymupdf.Rect(50, 50, 350, 250), stream=small.getvalue())
    page.insert_image(pymupdf.Rect(50, 300, 250, 433), stream=big.getvalue())
    doc.save(src)
    doc.close()
    for level in ("balanced", "strong"):
        out = pdf_tools.compress(src, tmp_path / f"{level}.pdf", level)
        with pymupdf.open(out) as result:
            first = result[0].get_image_info(xrefs=True)[0]
            assert result.extract_image(first["xref"])["image"] == small.getvalue()


def test_ocr_reads_pages_sharp_enough():
    from azoth import quality

    assert quality.OCR_DPI >= 300  # small print becomes unreadable below this


def test_searchable_pdf_keeps_jpg_scans_byte_for_byte(tmp_path, ocr_ready):
    """Text recognition only adds invisible text: scanned JPG pages are never re-saved."""
    from conftest import make_text_scan

    from azoth import ocr

    scan = make_text_scan(tmp_path / "page.png", ["Searchable but unchanged"])
    jpg = io.BytesIO()
    Image.open(scan).convert("RGB").save(jpg, "JPEG", quality=85)
    src = tmp_path / "scan.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=500, height=300)
    page.insert_image(page.rect, stream=jpg.getvalue())
    doc.save(src)
    doc.close()
    out = ocr.make_searchable(src, tmp_path / "out.pdf", "eng")
    with pymupdf.open(out) as result:
        [image] = result[0].get_images()
        assert result.extract_image(image[0])["image"] == jpg.getvalue()
        assert "Searchable but unchanged" in result[0].get_text()


def test_picture_size_only_changes_when_asked(tmp_path):
    """Pictures keep all their pixels by default; a chosen size shrinks them cleanly, and
    with "Don't enlarge smaller pictures" small ones stay exactly as they are."""
    from azoth import resize

    src = tmp_path / "flat.png"
    Image.new("RGB", (640, 480), (12, 120, 200)).save(src)
    engine = Engine()
    same = engine.convert(src, "bmp", tmp_path / "a")
    with Image.open(same.outputs[0]) as im:
        assert im.size == (640, 480)
    small = engine.convert(src, "bmp", tmp_path / "b", options={"resize": resize.parse("50%")})
    with Image.open(small.outputs[0]) as im:
        assert im.size == (320, 240)
        assert im.getextrema() == ((12, 12), (120, 120), (200, 200))  # no colour shift
    kept = engine.convert(
        src, "bmp", tmp_path / "c", options={"resize": resize.parse("1000", enlarge=False)}
    )
    with Image.open(kept.outputs[0]) as im, Image.open(src) as original:
        assert im.size == (640, 480)
        assert not ImageChops.difference(im.convert("RGB"), original.convert("RGB")).getbbox()


def test_ai_is_never_used_unless_asked():
    """AI-invented detail isn't 1:1: it is off in every default, and smaller pictures
    never go through it."""
    from azoth import resize

    assert not resize.Resize(resize.PERCENT, percent=200).ai
    assert not resize.parse("2000").ai and not resize.parse("400%").ai
    assert not resize.uses_ai(resize.parse("400%"), 100, 100)
    assert not resize.uses_ai(resize.Resize(resize.PERCENT, percent=50, ai=True), 100, 100)


def test_removing_document_metadata_keeps_the_content_exactly(tmp_path):
    """Cleaning a PDF or Word file changes only metadata: same page content and text."""
    import docx
    import pymupdf
    from conftest import make_pdf

    from azoth import metadata

    pdf = make_pdf(tmp_path / "a.pdf", ["Page one", "Page two"])
    with pymupdf.open(pdf) as doc:
        doc.set_metadata({"author": "Someone"})
        doc.saveIncr()
    out = metadata.clean_file(pdf).output
    with pymupdf.open(pdf) as a, pymupdf.open(out) as b:
        assert [p.read_contents() for p in a] == [p.read_contents() for p in b]

    word = tmp_path / "w.docx"
    d = docx.Document()
    d.add_paragraph("Exact text  with  spaces")
    d.core_properties.author = "Someone"
    d.save(word)
    cleaned = docx.Document(metadata.clean_file(word).output)
    assert [p.text for p in cleaned.paragraphs] == ["Exact text  with  spaces"]


def test_pdf_to_excel_keeps_every_figure_exactly(tmp_path):
    """PDF → Excel: each number in a table arrives with exactly its printed value (no
    rounding, no float noise like 1240.4999), and every text in the table arrives
    unchanged."""
    from openpyxl import load_workbook

    figures = ["CHF 1'240.50", "0.10", "99'999.99", "-3.75", "12 %", "100", "Office chair"]
    rows = "".join(f"<tr><td>Item {i}</td><td>{f}</td></tr>" for i, f in enumerate(figures))
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_htmlbox(
        pymupdf.Rect(50, 50, 545, 800),
        f"<table>{rows}</table>",
        css="td {border: 1px solid black; padding: 3px;}",
    )
    src = tmp_path / "figures.pdf"
    doc.save(src)
    [out] = Engine().convert(src, "xlsx", tmp_path / "out").outputs
    ws = load_workbook(out).worksheets[0]
    got = [ws.cell(i + 1, 2).value for i in range(len(figures))]
    assert got == [1240.5, 0.1, 99999.99, -3.75, 0.12, 100, "Office chair"]
    assert [ws.cell(i + 1, 1).value for i in range(len(figures))] == [
        f"Item {i}" for i in range(len(figures))
    ]
