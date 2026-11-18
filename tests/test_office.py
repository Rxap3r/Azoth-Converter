"""Office conversions. These need LibreOffice and are skipped without it."""

import pymupdf
import pytest

from azoth.converters.office import find_soffice
from azoth.engine import Engine

pytestmark = pytest.mark.skipif(find_soffice() is None, reason="LibreOffice not installed")


def test_word_to_pdf(sample_docx, tmp_path):
    [out] = Engine().convert(sample_docx, "pdf", tmp_path / "o").outputs
    assert out.name == "report.pdf"
    with pymupdf.open(out) as doc:
        text = doc[0].get_text()
    assert "Quarterly Report" in text
    assert "cell 11" in text


def test_word_to_pdf_to_word_round_trip(sample_docx, tmp_path):
    import docx

    [pdf] = Engine().convert(sample_docx, "pdf", tmp_path / "a").outputs
    [back] = Engine().convert(pdf, "docx", tmp_path / "b").outputs
    d = docx.Document(back)
    text = "\n".join(p.text for p in d.paragraphs)
    assert "Quarterly Report" in text
    assert len(d.tables) == 1


def test_word_to_png_uses_two_steps(sample_docx, tmp_path):
    engine = Engine()
    route = engine.find_route("docx", "png")
    assert [(s.src, s.dst) for s in route] == [("docx", "pdf"), ("pdf", "png")]
    [out] = engine.convert(sample_docx, "png", tmp_path, options={"dpi": 50}).outputs
    assert out.name == "report.png"


def test_csv_to_xlsx_and_pdf(tmp_path):
    csv = tmp_path / "budget.csv"
    csv.write_text("Item,Amount\nRent,1200\nFood,450\nÜberzeit,30\n", encoding="utf-8")
    engine = Engine()
    [xlsx] = engine.convert(csv, "xlsx", tmp_path / "x").outputs
    [pdf] = engine.convert(xlsx, "pdf", tmp_path / "p").outputs
    with pymupdf.open(pdf) as doc:
        text = doc[0].get_text()
    assert "Rent" in text and "Überzeit" in text


def test_docx_to_odt_and_txt(sample_docx, tmp_path):
    engine = Engine()
    [odt] = engine.convert(sample_docx, "odt", tmp_path).outputs
    [txt] = engine.convert(odt, "txt", tmp_path).outputs
    assert "Quarterly Report" in txt.read_text(encoding="utf-8-sig")


def test_photos_in_word_reach_pdf_unchanged(tmp_path):
    """1:1 quality: a JPEG photo in a Word file must not be re-compressed or downscaled."""
    import docx
    from docx.shared import Inches
    from PIL import Image

    photo = tmp_path / "photo.jpg"
    img = Image.new("RGB", (1200, 800))
    pixels = [(x * 7 % 256, y * 3 % 256, (x + y) % 256) for y in range(800) for x in range(1200)]
    img.putdata(pixels)
    img.save(photo, quality=95)
    d = docx.Document()
    d.add_picture(str(photo), width=Inches(6))
    d.save(tmp_path / "with_photo.docx")

    [pdf] = Engine().convert(tmp_path / "with_photo.docx", "pdf", tmp_path / "o").outputs
    with pymupdf.open(pdf) as doc:
        xref = doc[0].get_images()[0][0]
        embedded = doc.extract_image(xref)["image"]
    assert embedded == photo.read_bytes()


def test_libreoffice_leaves_no_temp_files(sample_docx, tmp_path, private_tmp):
    Engine().convert(sample_docx, "pdf", tmp_path / "o")
    assert list(private_tmp.iterdir()) == []
