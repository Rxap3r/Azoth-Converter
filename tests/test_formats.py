import pytest
from PIL import Image

from fileconv import formats


@pytest.mark.parametrize(
    ("pil_format", "ext", "expected"),
    [
        ("PNG", "png", "png"),
        ("JPEG", "jpg", "jpg"),
        ("GIF", "gif", "gif"),
        ("WEBP", "webp", "webp"),
        ("BMP", "bmp", "bmp"),
        ("TIFF", "tif", "tiff"),
        ("ICO", "ico", "ico"),
    ],
)
def test_detect_images(tmp_path, pil_format, ext, expected):
    path = tmp_path / f"x.{ext}"
    Image.new("RGB", (32, 32), "red").save(path, format=pil_format)
    assert formats.detect(path).id == expected


def test_detect_uses_content_not_extension(tmp_path):
    path = tmp_path / "holiday.txt"  # actually a PNG
    Image.new("RGB", (8, 8)).save(path, format="PNG")
    assert formats.detect(path).id == "png"


def test_detect_office_and_pdf(sample_docx, sample_pdf, tmp_path):
    assert formats.detect(sample_docx).id == "docx"
    assert formats.detect(sample_pdf).id == "pdf"
    renamed = tmp_path / "noext"
    renamed.write_bytes(sample_docx.read_bytes())
    assert formats.detect(renamed).id == "docx"


def test_detect_text_by_extension(tmp_path):
    p = tmp_path / "data.csv"
    p.write_text("a,b\n1,2\n")
    assert formats.detect(p).id == "csv"


def test_unknown(tmp_path):
    p = tmp_path / "mystery.bin"
    p.write_bytes(b"\x01\x02\x03")
    assert formats.detect(p) is None


def test_get_accepts_extensions():
    assert formats.get("JPEG").id == "jpg"
    assert formats.get(".tif").id == "tiff"
    with pytest.raises(KeyError):
        formats.get("nope")
