"""PDF tools: merge, split, edit pages. Lossless, safe with originals, readable errors."""

from __future__ import annotations

import io

import pymupdf
import pytest
from PIL import Image

from azoth import pdf_tools
from azoth.cli import main as cli
from azoth.converters import ConversionError
from azoth.pdf_tools import PageEdit


def make_pdf(path, labels, *, photo=False, toc=True, rotation=0):
    """One page per label, with the label as text (and a JPEG photo if asked)."""
    doc = pymupdf.open()
    jpeg = None
    if photo:
        buf = io.BytesIO()
        Image.new("RGB", (200, 120), (200, 80, 40)).save(buf, "JPEG", quality=90)
        jpeg = buf.getvalue()
    for label in labels:
        page = doc.new_page()
        page.insert_text((72, 72), label, fontsize=20)
        if jpeg:
            page.insert_image(pymupdf.Rect(72, 100, 272, 220), stream=jpeg)
        if rotation:
            page.set_rotation(rotation)
    if toc:
        doc.set_toc([[1, f"{labels[0]} chapter", 1]])
    doc.save(path)
    doc.close()
    return path


def texts(path):
    with pymupdf.open(path) as doc:
        return [page.get_text().strip() for page in doc]


def rotations(path):
    with pymupdf.open(path) as doc:
        return [page.rotation for page in doc]


def images(path):
    with pymupdf.open(path) as doc:
        return [doc.extract_image(x[0])["image"] for page in doc for x in page.get_images()]


# --- merge ---------------------------------------------------------------------------


def test_merge_keeps_order_bookmarks_and_pictures(tmp_path):
    a = make_pdf(tmp_path / "a.pdf", ["A1", "A2"], photo=True)
    b = make_pdf(tmp_path / "b.pdf", ["B1"])
    before = a.read_bytes()
    out = pdf_tools.merge([b, a], tmp_path / "out" / "Merged.pdf")
    assert texts(out) == ["B1", "A1", "A2"]
    assert images(out) == images(a)  # the photos are copied byte for byte
    with pymupdf.open(out) as doc:
        assert doc.get_toc() == [[1, "B1 chapter", 1], [1, "A1 chapter", 2]]
    assert a.read_bytes() == before


def test_merge_never_overwrites(tmp_path):
    a = make_pdf(tmp_path / "a.pdf", ["A"])
    b = make_pdf(tmp_path / "b.pdf", ["B"])
    first = pdf_tools.merge([a, b], tmp_path / "Merged.pdf")
    second = pdf_tools.merge([a, b], tmp_path / "Merged.pdf")
    assert second.name == "Merged (1).pdf" and first.exists()
    # Even when asked to overwrite, a source file is never the target.
    third = pdf_tools.merge([a, b], a, overwrite=True)
    assert third != a and texts(a) == ["A"]


def test_merge_needs_two_readable_pdfs(tmp_path):
    a = make_pdf(tmp_path / "a.pdf", ["A"])
    with pytest.raises(ConversionError, match="two or more"):
        pdf_tools.merge([a], tmp_path / "m.pdf")
    locked = tmp_path / "locked.pdf"
    doc = pymupdf.open()
    doc.new_page()
    doc.save(locked, encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="pw", owner_pw="pw")
    doc.close()
    with pytest.raises(ConversionError, match="password"):
        pdf_tools.merge([a, locked], tmp_path / "m.pdf")
    assert not (tmp_path / "m.pdf").exists()


def test_failed_save_leaves_nothing_behind(tmp_path, private_tmp, monkeypatch):
    a = make_pdf(tmp_path / "a.pdf", ["A"])
    b = make_pdf(tmp_path / "b.pdf", ["B"])

    def broken_save(self, *args, **kwargs):
        raise RuntimeError("disk full")

    monkeypatch.setattr(pymupdf.Document, "save", broken_save)
    with pytest.raises(ConversionError, match="Cannot save"):
        pdf_tools.merge([a, b], tmp_path / "Merged.pdf")
    assert not (tmp_path / "Merged.pdf").exists()
    assert list(private_tmp.iterdir()) == []  # temporary folder removed


# --- split ---------------------------------------------------------------------------


def test_parse_ranges():
    assert pdf_tools.parse_ranges("1-3, 5, 8-", 10) == [[0, 1, 2], [4], [7, 8, 9]]
    assert pdf_tools.parse_ranges("-2; 4–5", 6) == [[0, 1], [3, 4]]  # en dash and ;
    for bad, message in [
        ("", "Enter the pages"),
        ("abc", "is not a page range"),
        ("0", "is not in the PDF"),
        ("12", "is not in the PDF"),
        ("5-3", "is not in the PDF"),
        ("-", "is not a page range"),
    ]:
        with pytest.raises(ConversionError, match=message):
            pdf_tools.parse_ranges(bad, 10)


def test_split_every_page(tmp_path):
    src = make_pdf(tmp_path / "report.pdf", ["P1", "P2", "P3"])
    out = pdf_tools.split(src, pdf_tools.split_folder(src))
    assert [p.name for p in out] == [
        "report_page001.pdf",
        "report_page002.pdf",
        "report_page003.pdf",
    ]
    assert out[0].parent == tmp_path / "report_pages"
    assert [texts(p) for p in out] == [["P1"], ["P2"], ["P3"]]


def test_split_by_ranges_and_no_overwrite(tmp_path):
    src = make_pdf(tmp_path / "report.pdf", ["P1", "P2", "P3", "P4"], photo=True)
    groups = pdf_tools.parse_ranges("1-2, 4", 4)
    out = pdf_tools.split(src, tmp_path / "parts", groups)
    assert [p.name for p in out] == ["report (pages 1-2).pdf", "report (page 4).pdf"]
    assert texts(out[0]) == ["P1", "P2"] and texts(out[1]) == ["P4"]
    assert images(out[1]) == images(src)[3:]  # pictures unchanged
    again = pdf_tools.split(src, tmp_path / "parts", groups)
    assert again[0].name == "report (pages 1-2) (1).pdf"


# --- edit pages ----------------------------------------------------------------------


def test_edit_reorders_deletes_and_rotates(tmp_path):
    src = make_pdf(tmp_path / "scan.pdf", ["S1", "S2", "S3", "S4"], photo=True)
    before = src.read_bytes()
    out = pdf_tools.edit_pages(
        src,
        pdf_tools.edited_path(src),
        [PageEdit(3), PageEdit(0, 90), PageEdit(2, 270)],  # page 2 deleted
    )
    assert out.name == "scan (edited).pdf"
    assert texts(out) == ["S4", "S1", "S3"]
    assert rotations(out) == [0, 90, 270]
    assert images(out) == [images(src)[i] for i in (3, 0, 2)]
    assert src.read_bytes() == before  # the original is never changed


def test_edit_adds_to_existing_rotation(tmp_path):
    src = make_pdf(tmp_path / "turned.pdf", ["T1"], rotation=90)
    out = pdf_tools.edit_pages(src, tmp_path / "out.pdf", [PageEdit(0, 180)])
    assert rotations(out) == [270]
    out = pdf_tools.edit_pages(src, tmp_path / "back.pdf", [PageEdit(0, 270)])
    assert rotations(out) == [0]


def test_edit_keeps_bookmarks_of_kept_pages(tmp_path):
    src = make_pdf(tmp_path / "book.pdf", ["B1", "B2"])
    out = pdf_tools.edit_pages(src, tmp_path / "out.pdf", [PageEdit(1), PageEdit(0)])
    with pymupdf.open(out) as doc:
        assert doc.get_toc() == [[1, "B1 chapter", 2]]  # follows its page


@pytest.mark.parametrize(
    ("pages", "message"),
    [
        ([], "one or more pages"),
        ([PageEdit(5)], "are not in this PDF"),
        ([PageEdit(0), PageEdit(0)], "only one time"),
        ([PageEdit(0, 45)], "steps of 90"),
    ],
)
def test_edit_rejects_bad_requests(tmp_path, pages, message):
    src = make_pdf(tmp_path / "x.pdf", ["X1", "X2"])
    with pytest.raises(ConversionError, match=message):
        pdf_tools.edit_pages(src, tmp_path / "out.pdf", pages)
    assert not (tmp_path / "out.pdf").exists()


def test_thumbnails(tmp_path):
    src = make_pdf(tmp_path / "t.pdf", ["T1", "T2"])
    pictures = list(pdf_tools.thumbnails(src, width=60))
    assert [i for i, _ in pictures] == [0, 1]
    with Image.open(io.BytesIO(pictures[0][1])) as im:
        assert im.width == 60


# --- command line --------------------------------------------------------------------


def test_cli_split_ranges_and_edit(tmp_path, capsys):
    src = make_pdf(tmp_path / "doc.pdf", ["D1", "D2", "D3"])
    assert cli(["pdf", "split", str(src), "--ranges", "1-2, 3"]) == 0
    assert sorted(p.name for p in (tmp_path / "doc_pages").iterdir()) == [
        "doc (page 3).pdf",
        "doc (pages 1-2).pdf",
    ]
    assert cli(["pdf", "edit", str(src), "--delete", "2", "--rotate", "1=90"]) == 0
    out = tmp_path / "doc (edited).pdf"
    assert texts(out) == ["D1", "D3"] and rotations(out) == [90, 0]
    assert cli(["pdf", "edit", str(src), "--pages", "3,1", "-o", str(tmp_path / "r.pdf")]) == 0
    assert texts(tmp_path / "r.pdf") == ["D3", "D1"]

    capsys.readouterr()
    assert cli(["pdf", "edit", str(src), "--rotate", "1=45"]) == 1
    assert "Use the form page=degrees" in capsys.readouterr().err
    assert cli(["pdf", "split", str(src), "--ranges", "9"]) == 1
    assert "is not in the PDF" in capsys.readouterr().err
