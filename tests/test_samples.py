"""The committed sample files are recognised correctly and the bad ones fail politely."""

from pathlib import Path

import pytest

from fileconv import formats
from fileconv.converters import ConversionError
from fileconv.engine import Engine

SAMPLES = Path(__file__).resolve().parent.parent / "samples"

EXPECTED = {
    "word/formatted_report.docx": "docx",
    "word/formatted_report.odt": "odt",
    "word/formatted_report.rtf": "rtf",
    "word/formatted_report.doc": "doc",
    "pdf/invoice.pdf": "pdf",
    "excel/budget_with_formulas_and_chart.xlsx": "xlsx",
    "excel/budget_with_formulas_and_chart.ods": "ods",
    "excel/budget_with_formulas_and_chart.xls": "xls",
    "excel/contacts.csv": "csv",
    "powerpoint/presentation.pptx": "pptx",
    "powerpoint/presentation.odp": "odp",
    "powerpoint/presentation.ppt": "ppt",
    "images/photo_with_gps_rotated.jpg": "jpg",
    "images/iphone_photo.heic": "heic",
    "images/animated.gif": "gif",
    "images/two_pages.tiff": "tiff",
    "images/photo.webp": "webp",
    "images/photo.bmp": "bmp",
    "other/notes_unicode.txt": "txt",
    "other/png_with_wrong_extension.txt": "png",
}


@pytest.mark.parametrize(("name", "expected"), EXPECTED.items())
def test_samples_detected(name, expected):
    path = SAMPLES / name
    if not path.exists():
        pytest.skip(f"{name} not generated (run samples/generate.py)")
    assert formats.detect(path).id == expected


@pytest.mark.parametrize(
    ("name", "target", "message"),
    [
        ("pdf/scanned_letter_no_text.pdf", "docx", "scan"),
        ("pdf/password_protected_test123.pdf", "docx", "password"),
        ("other/broken_not_really.pdf", "png", "damaged"),
    ],
)
def test_problem_samples_fail_with_clear_message(tmp_path, name, target, message):
    path = SAMPLES / name
    if not path.exists():
        pytest.skip(f"{name} not generated (run samples/generate.py)")
    with pytest.raises(ConversionError, match=message):
        Engine().convert(path, target, tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_pdf_to_word_keeps_tables_and_images(tmp_path):
    import docx

    path = SAMPLES / "pdf/report_made_from_word.pdf"
    if not path.exists():
        pytest.skip("sample not generated")
    [out] = Engine().convert(path, "docx", tmp_path).outputs
    d = docx.Document(out)
    text = "\n".join(p.text for p in d.paragraphs)
    assert "Annual Report 2026" in text
    assert len(d.tables) >= 1
    assert len(d.inline_shapes) >= 1
