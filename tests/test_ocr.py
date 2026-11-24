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


def visible_letters(page: pymupdf.Page) -> list[tuple[str, float, float]]:
    """Each hidden letter with where it is on the page as you see it (rotation applied)."""
    letters = []
    for block in page.get_text("rawdict")["blocks"]:
        for line in block.get("lines", []):
            for span in line["spans"]:
                for char in span["chars"]:
                    at = pymupdf.Point(char["origin"]) * page.rotation_matrix
                    letters.append((char["c"], at.x, at.y))
    return letters


def assert_text_upright(page: pymupdf.Page, word: str = "Invoice") -> None:
    """The hidden text runs left to right on the visible page, starting at the top left,
    as in the picture. (Sideways hidden text would select wrongly in PDF viewers.)"""
    letters = visible_letters(page)
    text = "".join(c for c, _, _ in letters)
    start = text.index(word)
    run = letters[start : start + len(word)]
    xs = [x for _, x, _ in run]
    ys = [y for _, _, y in run]
    assert all(a < b for a, b in zip(xs, xs[1:], strict=False)), run  # left to right
    assert max(ys) - min(ys) < 2, run  # on one line
    assert xs[0] < page.rect.width / 4 and ys[0] < page.rect.height / 4, run  # top left


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
    with pytest.raises(ConversionError, match="already has text that you can select"):
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
        assert_text_upright(result[0])


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
    with pytest.raises(ConversionError, match="found no text"):
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
    assert "already has text that you can select" in capsys.readouterr().err


def test_cli_convert_with_ocr(tmp_path):
    photo = make_text_scan(tmp_path / "letter.png", LETTER)
    args = ["convert", str(photo), "--to", "pdf", "--ocr", "--language", "eng", "-q"]
    assert cli([*args, "-o", str(tmp_path / "o")]) == 0
    with pymupdf.open(tmp_path / "o" / "letter.pdf") as doc:
        assert "Thank you for your order" in doc[0].get_text()


def test_searchable_pdf_to_word_uses_its_hidden_text(tmp_path, monkeypatch):
    """A searchable scan (picture + invisible text) becomes a Word file with that text,
    not a picture: pdf2docx can't see hidden text, so the text layer is used."""
    photo = make_text_scan(tmp_path / "letter.png", LETTER)
    [pdf] = Engine().convert(photo, "pdf", tmp_path / "a", options={"ocr": True}).outputs
    # Its text is read from the PDF, not recognised again.
    monkeypatch.setattr(ocr, "_text_layer", lambda *a: pytest.fail("recognised again"))
    for target in ("docx", "txt"):
        [out] = Engine().convert(pdf, target, tmp_path / "b").outputs
        text = out.read_text(encoding="utf-8") if target == "txt" else docx_text(out)
        for line in LETTER:
            assert line in text


@pytest.mark.parametrize("rotation", [90, 180, 270])
def test_sideways_or_upside_down_scan_is_read(tmp_path, rotation):
    """A page shown the wrong way up is read and turned the right way up. The picture
    stays byte for byte the same; the hidden text sits on the words."""
    picture = make_text_scan(tmp_path / "p.png", LETTER)
    doc = pymupdf.open()
    page = doc.new_page(width=500, height=300)
    page.insert_image(page.rect, filename=str(picture))
    page.set_rotation(rotation)  # shown sideways or upside down
    doc.save(tmp_path / "turned.pdf")
    doc.close()
    out = ocr.make_searchable(tmp_path / "turned.pdf", tmp_path / "out.pdf", "eng")
    with pymupdf.open(out) as result:
        assert result[0].rotation == 0  # upright now
        with pymupdf.open(tmp_path / "turned.pdf") as original:
            assert pictures(result) == pictures(original)
        text = result[0].get_text()
        for line in LETTER:
            assert line in text
        assert_text_upright(result[0])


def test_sideways_photo_to_text(tmp_path):
    from PIL import Image

    upright = make_text_scan(tmp_path / "upright.png", LETTER)
    sideways = tmp_path / "sideways.png"
    Image.open(upright).rotate(90, expand=True).save(sideways)  # no rotation info in the file
    [out] = (
        Engine().convert(sideways, "txt", tmp_path / "o", options={"ocr_language": "eng"}).outputs
    )
    text = out.read_text(encoding="utf-8")
    for line in LETTER:
        assert line in text


def test_reading_score():
    assert ocr.reading_score("Thank you for your order.") > 0.8
    assert ocr.reading_score("By) e) — QD ® Q > < o. Q® 2 ja") < 0.3
    assert ocr.reading_score("") == 0


def test_sideways_photo_to_searchable_pdf_is_turned_upright(tmp_path):
    from PIL import Image

    upright = make_text_scan(tmp_path / "upright.png", LETTER)
    sideways = tmp_path / "sideways.png"
    Image.open(upright).rotate(90, expand=True).save(sideways)  # a screenshot turned left
    [out] = Engine().convert(sideways, "pdf", tmp_path / "o", options={"ocr": True}).outputs
    with pymupdf.open(out) as doc:
        page = doc[0]
        assert page.rotation == 90  # shown turned back to the right
        assert page.rect.width > page.rect.height  # landscape, like the upright text
        assert "Invoice number 4711" in page.get_text()
        assert_text_upright(page)


def test_turning_pages_can_be_switched_off(tmp_path):
    picture = make_text_scan(tmp_path / "p.png", LETTER)
    doc = pymupdf.open()
    page = doc.new_page(width=500, height=300)
    page.insert_image(page.rect, filename=str(picture))
    page.set_rotation(180)  # upside down
    doc.save(tmp_path / "turned.pdf")
    doc.close()
    out = ocr.make_searchable(
        tmp_path / "turned.pdf", tmp_path / "out.pdf", "eng", turn_pages=False
    )
    with pymupdf.open(out) as result:
        assert result[0].rotation == 180  # left as it was
        assert "Invoice number 4711" in result[0].get_text()  # but read correctly
    assert (
        cli(
            [
                "pdf",
                "ocr",
                str(tmp_path / "turned.pdf"),
                "--keep-rotation",
                "-o",
                str(tmp_path / "c.pdf"),
            ]
        )
        == 0
    )
    with pymupdf.open(tmp_path / "c.pdf") as result:
        assert result[0].rotation == 180


def test_selection_box_covers_the_letters(tmp_path):
    """The hidden word's box (what PDF viewers highlight when you select it) sits on the
    letters in the picture: not lower, not higher."""
    from PIL import Image, ImageOps

    photo = make_text_scan(tmp_path / "line.png", ["Invoice number 4711 Typography"])
    [out] = Engine().convert(photo, "pdf", tmp_path / "o", options={"ocr": True}).outputs
    with pymupdf.open(out) as doc:
        page = doc[0]
        box = next(pymupdf.Rect(w[:4]) for w in page.get_text("words") if w[4] == "Invoice")
        # Where the letters really are: the dark rows of the picture, in page units.
        image = ImageOps.invert(Image.open(photo).convert("L"))
        ink = image.getbbox()
        scale = page.rect.height / image.height
        top, bottom = ink[1] * scale, ink[3] * scale
        height = bottom - top
        assert abs(box.y0 - top) < 0.25 * height, (box, top, bottom)
        assert abs(box.y1 - bottom) < 0.25 * height, (box, top, bottom)


def test_hidden_text_font_has_one_set_of_measurements(tmp_path):
    """Viewers read a font's height either from the PDF or from the font file. Both must
    agree, or the selection box moves (Edge put it below the words with MuPDF's font)."""
    photo = make_text_scan(tmp_path / "line.png", ["Cœur, l’été: 5 € – Grüße"])
    [out] = (
        Engine()
        .convert(photo, "pdf", tmp_path / "o", options={"ocr": True, "ocr_language": "fra"})
        .outputs
    )
    with pymupdf.open(out) as doc:
        fonts = doc[0].get_fonts(full=True)
        assert fonts and all("GlyphLess" not in f[3] for f in fonts)
        for xref, *_ in fonts:
            name, ext, _type, data = doc.extract_font(xref)
            font = pymupdf.Font(fontbuffer=data)
            descriptor = next(
                x
                for x in range(1, doc.xref_length())
                if "/FontDescriptor" in doc.xref_object(x) and "/Ascent" in doc.xref_object(x)
            )
            ascent = float(doc.xref_get_key(descriptor, "Ascent")[1])
            descent = float(doc.xref_get_key(descriptor, "Descent")[1])
            assert abs(ascent / 1000 - font.ascender) < 0.01
            assert abs(descent / 1000 - font.descender) < 0.01
            # Exactly one font size high: Firefox draws the box one font size high from
            # the ascent, other viewers from ascent to descent. Both then agree.
            assert abs(font.ascender - font.descender - 1) < 0.01
        text = doc[0].get_text()
        assert "€" in text or "Gr" in text  # accents and symbols survive in the hidden text


def test_reading_does_not_freeze_the_app(tmp_path):
    """The OCR engine blocks Python while it reads a page; it runs in a helper process so
    the window keeps responding (Windows showed "Not responding" before)."""
    import time

    scan = scanned_pdf(tmp_path / "scan.pdf", [make_text_scan(tmp_path / "p.png", LETTER)])
    pauses = []
    worker = threading.Thread(target=ocr.make_searchable, args=(scan, tmp_path / "o.pdf", "eng"))
    worker.start()
    last = time.perf_counter()
    while worker.is_alive():
        time.sleep(0.01)
        now = time.perf_counter()
        pauses.append(now - last)
        last = now
    worker.join()
    assert (tmp_path / "o.pdf").exists()
    assert max(pauses) < 0.5  # the window gets to redraw many times a second
