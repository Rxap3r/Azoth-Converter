"""Text recognition (OCR): photos and scans → text, Word and searchable PDFs."""

from __future__ import annotations

import hashlib
import threading
from pathlib import Path

import docx
import pymupdf
import pytest
from conftest import make_pdf, make_text_scan

from azoth import ocr
from azoth.cli import main as cli
from azoth.converters import ConversionCancelled, ConversionError
from azoth.engine import Engine

pytestmark = pytest.mark.usefixtures("ocr_ready")

LETTER = ["Invoice number 4711", "Thank you for your order"]
GERMAN = ["Grüße aus Zürich", "Straße und Größe"]
SAMPLES = Path(__file__).resolve().parent.parent / "samples"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def scanned_pdf(path: Path, pictures: list[Path], rotate: int = 0) -> Path:
    """A scanner's PDF: one picture per page, no text."""
    doc = pymupdf.open()
    for picture in pictures:
        page = doc.new_page(width=500, height=300)
        page.insert_image(page.rect, filename=str(picture))
        page.set_rotation(rotate)
    doc.save(path)
    doc.close()
    return path


def pictures(doc: pymupdf.Document) -> list[bytes]:
    """The pixels of every picture (unpacked, so lossless re-packing doesn't count)."""
    return [doc.xref_stream(img[0]) for page in doc for img in page.get_images(full=True)]


def docx_text(path: Path) -> str:
    return "\n".join(p.text for p in docx.Document(str(path)).paragraphs)


# --- languages ------------------------------------------------------------------------


def test_four_languages_are_shipped():
    assert ocr.available_languages() == ["eng", "deu", "fra", "ita"]


@pytest.mark.parametrize(
    ("locale_name", "expected"),
    [
        ("de_CH", "deu"),
        ("fr-FR", "fra"),
        ("it", "ita"),
        ("en_US", "eng"),
        ("German_Switzerland", "deu"),
        ("ja_JP", "eng"),  # not shipped: English
        ("", "eng"),
    ],
)
def test_default_language_follows_the_computer(locale_name, expected):
    assert ocr.default_language(locale_name) == expected


def test_unknown_language_is_refused(tmp_path):
    scan = scanned_pdf(tmp_path / "scan.pdf", [make_text_scan(tmp_path / "p.png", LETTER)])
    with pytest.raises(ConversionError, match="language"):
        ocr.make_searchable(scan, tmp_path / "out.pdf", "xyz")


# --- photos and scans → text and Word ---------------------------------------------------


@pytest.mark.parametrize("target", ["txt", "docx"])
def test_photo_of_a_letter_to_text_and_word(tmp_path, target):
    photo = make_text_scan(tmp_path / "letter.png", LETTER)
    [out] = Engine().convert(photo, target, tmp_path / "o", options={"ocr_language": "eng"}).outputs
    text = out.read_text(encoding="utf-8") if target == "txt" else docx_text(out)
    for line in LETTER:
        assert line in text


def test_german_umlauts_and_sharp_s(tmp_path):
    photo = make_text_scan(tmp_path / "brief.png", GERMAN)
    [out] = Engine().convert(photo, "txt", tmp_path / "o", options={"ocr_language": "deu"}).outputs
    text = out.read_text(encoding="utf-8")
    for line in GERMAN:
        assert line in text


def test_scanned_pdf_to_word_reads_every_page(tmp_path):
    pages = [
        make_text_scan(tmp_path / "1.png", ["First page says hello"]),
        make_text_scan(tmp_path / "2.png", ["Second page says goodbye"]),
    ]
    scan = scanned_pdf(tmp_path / "scan.pdf", pages)
    [out] = Engine().convert(scan, "docx", tmp_path / "o").outputs
    text = docx_text(out)
    assert text.index("First page says hello") < text.index("Second page says goodbye")
    assert "\f" not in text


def test_scanned_pdf_to_text_separates_pages(tmp_path):
    pages = [make_text_scan(tmp_path / f"{i}.png", [f"Page number {i}"]) for i in (1, 2)]
    scan = scanned_pdf(tmp_path / "scan.pdf", pages)
    [out] = Engine().convert(scan, "txt", tmp_path / "o").outputs
    first, second = out.read_text(encoding="utf-8").split("\f")
    assert "Page number 1" in first and "Page number 2" in second


def test_text_pdf_to_word_still_uses_the_layout_converter(tmp_path):
    pdf = make_pdf(tmp_path / "real.pdf", ["Real text, no scan"])
    [out] = Engine().convert(pdf, "docx", tmp_path / "o").outputs
    assert "Real text, no scan" in docx_text(out)


def test_rough_sample_scan_is_read(tmp_path):
    path = SAMPLES / "pdf" / "scanned_letter_no_text.pdf"
    if not path.exists():
        pytest.skip("samples not generated (run samples/generate.py)")
    [out] = Engine().convert(path, "docx", tmp_path).outputs
    text = docx_text(out)
    assert "Thank you for your order" in text
    assert "Sample Company" in text


def test_ocr_quality_note():
    route = Engine().find_route("jpg", "docx")
    notes = Engine().quality_notes(route)
    assert any("OCR" in n and "Check names and numbers" in n for n in notes)


# --- searchable PDF ---------------------------------------------------------------------


def test_make_searchable_keeps_the_pages_exactly(tmp_path):
    pages = [make_text_scan(tmp_path / f"{i}.png", [f"Contract page {i}"]) for i in (1, 2)]
    scan = scanned_pdf(tmp_path / "scan.pdf", pages)
    before = digest(scan)
    out = ocr.make_searchable(scan, ocr.searchable_path(scan), "eng")
    assert out.name == "scan (searchable).pdf"
    assert digest(scan) == before  # the original is never changed
    with pymupdf.open(scan) as original, pymupdf.open(out) as result:
        assert result.page_count == 2
        assert pictures(result) == pictures(original)  # same pictures, byte for byte, no extra
        for i, page in enumerate(result):
            assert f"Contract page {i + 1}" in page.get_text()
            assert page.search_for("Contract")
            # Invisible text: the page looks exactly like the original.
            assert page.get_pixmap(dpi=72).samples == original[i].get_pixmap(dpi=72).samples


def test_make_searchable_never_overwrites(tmp_path):
    scan = scanned_pdf(tmp_path / "scan.pdf", [make_text_scan(tmp_path / "p.png", LETTER)])
    existing = ocr.searchable_path(scan)
    existing.write_bytes(b"keep me")
    out = ocr.make_searchable(scan, existing, "eng")
    assert out != existing and existing.read_bytes() == b"keep me"


def test_make_searchable_refuses_pdf_with_text(tmp_path):
    pdf = make_pdf(tmp_path / "real.pdf", ["This PDF has real text already"])
    with pytest.raises(ConversionError, match="already has selectable text"):
        ocr.make_searchable(pdf, tmp_path / "out.pdf", "eng")
    assert not (tmp_path / "out.pdf").exists()


def test_only_scanned_pages_get_text(tmp_path):
    scan = scanned_pdf(tmp_path / "mixed.pdf", [make_text_scan(tmp_path / "p.png", LETTER)])
    with pymupdf.open(scan) as doc:
        page = doc.new_page()
        page.insert_text((72, 72), "A real text page with plenty of words", fontsize=14)
        doc.saveIncr()
    out = ocr.make_searchable(scan, tmp_path / "out.pdf", "eng")
    with pymupdf.open(out) as doc:
        assert "Invoice number 4711" in doc[0].get_text()
        assert doc[1].get_text().count("A real text page") == 1  # not doubled


@pytest.mark.parametrize("rotation", [90, 180, 270])
def test_rotated_scan_pages(tmp_path, rotation):
    """A scanner that stores the page sideways and marks it as turned: the text is read
    upright and lands where it is on the visible page."""
    from PIL import Image

    upright = make_text_scan(tmp_path / "p.png", LETTER)
    stored = tmp_path / "stored.png"
    # The stored picture is turned so that the page's rotation shows it upright.
    Image.open(upright).rotate(rotation, expand=True).save(stored)
    doc = pymupdf.open()
    width, height = (300, 500) if rotation in (90, 270) else (500, 300)
    page = doc.new_page(width=width, height=height)
    page.insert_image(page.rect, filename=str(stored))
    page.set_rotation(rotation)
    doc.save(tmp_path / "turned.pdf")
    out = ocr.make_searchable(tmp_path / "turned.pdf", tmp_path / "out.pdf", "eng")
    with pymupdf.open(out) as result:
        text = result[0].get_text()
        assert "Invoice number 4711" in text
        # The word sits at the top left of the visible page, as in the upright picture.
        word = next(w for w in result[0].get_text("words") if w[4] == "Invoice")
        assert word[0] < 100 and word[1] < 100  # words are in visible-page coordinates


def test_photo_to_searchable_pdf(tmp_path):
    photo = make_text_scan(tmp_path / "receipt.png", LETTER)
    plain = Engine().convert(photo, "pdf", tmp_path / "plain").outputs[0]
    [out] = Engine().convert(photo, "pdf", tmp_path / "ocr", options={"ocr": True}).outputs
    with pymupdf.open(plain) as a, pymupdf.open(out) as b:
        assert pictures(a) == pictures(b)  # the picture is stored exactly the same
        assert a[0].get_text().strip() == ""
        assert "Invoice number 4711" in b[0].get_text()


def test_cancel_stops_and_saves_nothing(tmp_path):
    scan = scanned_pdf(tmp_path / "scan.pdf", [make_text_scan(tmp_path / "p.png", LETTER)])
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(ConversionCancelled):
        ocr.make_searchable(scan, tmp_path / "out.pdf", "eng", cancel=cancel)
    assert not (tmp_path / "out.pdf").exists()


def test_picture_without_text(tmp_path, sample_png):
    with pytest.raises(ConversionError, match="No text was found"):
        Engine().convert(sample_png, "txt", tmp_path / "o")
    assert not (tmp_path / "o" / "logo.txt").exists()


# --- command line ----------------------------------------------------------------------


def test_cli_pdf_ocr(tmp_path, capsys):
    scan = scanned_pdf(tmp_path / "scan.pdf", [make_text_scan(tmp_path / "p.png", GERMAN)])
    assert cli(["pdf", "ocr", str(scan), "--language", "deu"]) == 0
    out = tmp_path / "scan (searchable).pdf"
    with pymupdf.open(out) as doc:
        assert "Grüße aus Zürich" in doc[0].get_text()
    assert cli(["pdf", "ocr", str(out)]) == 1
    assert "already has selectable text" in capsys.readouterr().err


def test_cli_convert_with_ocr(tmp_path):
    photo = make_text_scan(tmp_path / "letter.png", LETTER)
    args = ["convert", str(photo), "--to", "pdf", "--ocr", "--language", "eng", "-q"]
    assert cli([*args, "-o", str(tmp_path / "o")]) == 0
    with pymupdf.open(tmp_path / "o" / "letter.pdf") as doc:
        assert "Thank you for your order" in doc[0].get_text()
