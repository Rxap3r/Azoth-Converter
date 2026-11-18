import pymupdf
import pytest
from conftest import make_pdf, make_scanned_pdf
from PIL import Image

from fileconv.converters import ConversionError
from fileconv.converters.pdf import merge_pdfs, split_pdf
from fileconv.engine import Engine


def test_pdf_to_png_one_file_per_page(sample_pdf, tmp_path):
    out = tmp_path / "out"
    result = Engine().convert(sample_pdf, "png", out, options={"dpi": 72})
    names = sorted(p.name for p in result.outputs)
    assert names == ["letter_page001.png", "letter_page002.png", "letter_page003.png"]
    with Image.open(result.outputs[0]) as im:
        assert im.size == (595, 842)  # A4 at 72 DPI


def test_single_page_pdf_keeps_plain_name(tmp_path):
    src = make_pdf(tmp_path / "one.pdf", ["only page"])
    [out] = Engine().convert(src, "jpg", tmp_path / "o").outputs
    assert out.name == "one.jpg"


def test_pdf_to_multipage_tiff(sample_pdf, tmp_path):
    [out] = Engine().convert(sample_pdf, "tiff", tmp_path, options={"dpi": 50}).outputs
    with Image.open(out) as im:
        assert im.n_frames == 3


def test_pdf_to_text(sample_pdf, tmp_path):
    [out] = Engine().convert(sample_pdf, "txt", tmp_path).outputs
    text = out.read_text(encoding="utf-8")
    assert "First page text" in text and "Third page" in text


def test_pdf_to_word(tmp_path, sample_docx):
    import docx

    pdf = make_pdf(tmp_path / "invoice.pdf", ["Invoice number 2024-117", "Thank you"])
    [out] = Engine().convert(pdf, "docx", tmp_path / "o").outputs
    text = "\n".join(p.text for p in docx.Document(out).paragraphs)
    assert "Invoice number 2024-117" in text
    assert "Thank you" in text


def test_scanned_pdf_to_word_gives_clear_error(tmp_path, sample_png):
    pdf = make_scanned_pdf(tmp_path / "scan.pdf", sample_png)
    with pytest.raises(ConversionError, match="scan"):
        Engine().convert(pdf, "docx", tmp_path / "o")


def test_password_protected_pdf(tmp_path):
    src = make_pdf(tmp_path / "plain.pdf", ["secret"])
    locked = tmp_path / "locked.pdf"
    with pymupdf.open(src) as doc:
        doc.save(locked, encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="pw", owner_pw="pw")
    with pytest.raises(ConversionError, match="password"):
        Engine().convert(locked, "png", tmp_path / "o")


def test_images_to_pdf(sample_png, tmp_path):
    [out] = Engine().convert(sample_png, "pdf", tmp_path).outputs
    with pymupdf.open(out) as doc:
        assert doc.page_count == 1


def test_merge_and_split(tmp_path):
    a = make_pdf(tmp_path / "a.pdf", ["A1", "A2"])
    b = make_pdf(tmp_path / "b.pdf", ["B1"])
    merged = merge_pdfs([a, b], tmp_path / "merged.pdf")
    with pymupdf.open(merged) as doc:
        assert doc.page_count == 3
        assert "B1" in doc[2].get_text()
    pages = split_pdf(merged, tmp_path / "pages")
    assert [p.name for p in pages] == [
        "merged_page001.pdf",
        "merged_page002.pdf",
        "merged_page003.pdf",
    ]
