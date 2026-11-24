"""Removing metadata from PDF, Word, Excel and PowerPoint files: everything private
goes, the content stays exactly the same."""

from __future__ import annotations

import io
import re
import zipfile

import pymupdf
import pytest
from conftest import make_pdf

from azoth import doc_metadata, metadata
from azoth.cli import main as cli
from azoth.converters import ConversionError

NAME = "Max Muster"  # made up
TEMPLATE = r"file:///C:\Users\MaxMuster\Templates\Letter.dotx"
FOLDER = r"C:\Users\MaxMuster\Documents\Budget\\"


def _rewrite(path, changes: dict[str, callable]):
    """Change parts of an Office file in place (to add what real Office files contain)."""
    with zipfile.ZipFile(path) as zf:
        parts = [(i, zf.read(i)) for i in zf.infolist()]
    extra = changes.pop("_new", {})
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for info, data in parts:
            zf.writestr(info, changes.get(info.filename, lambda d: d)(data))
        for name, data in extra.items():
            zf.writestr(name, data)


def _part(path, name: str) -> bytes:
    with zipfile.ZipFile(path) as zf:
        return zf.read(name)


def make_word(path):
    import docx

    doc = docx.Document()
    doc.add_paragraph("The plan for next year")
    doc.add_comment(doc.paragraphs[0].runs, text="Check the numbers", author=NAME, initials="MM")
    props = doc.core_properties
    props.author, props.last_modified_by, props.title = NAME, NAME, "Secret plan"
    doc.save(path)
    tracked = (
        b'<w:p w:rsidR="00AB12CD"><w:ins w:id="90" w:author="' + NAME.encode() + b'" '
        b'w:date="2026-01-05T10:00:00Z"><w:r><w:t xml:space="preserve">Added later </w:t>'
        b"</w:r></w:ins></w:p>"
    )
    rels = (
        b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<Relationships '
        b'xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship '
        b'Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/'
        b'attachedTemplate" Target="' + TEMPLATE.encode() + b'" TargetMode="External"/>'
        b"</Relationships>"
    )
    _rewrite(
        path,
        {
            "word/document.xml": lambda d: d.replace(b"<w:sectPr", tracked + b"<w:sectPr", 1),
            "docProps/app.xml": lambda d: d.replace(
                b"</Properties>", b"<Company>ACME Secret Ltd</Company></Properties>"
            ),
            "_new": {"word/_rels/settings.xml.rels": rels},
        },
    )
    return path


def make_excel(path):
    import openpyxl
    from openpyxl.comments import Comment

    wb = openpyxl.Workbook()
    wb.active["A1"] = "Budget 2027"
    wb.active["A1"].comment = Comment("Too high?", NAME)
    wb.properties.creator = NAME
    wb.save(path)
    saved_in = (
        b'<mc:AlternateContent xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility'
        b'/2006"><mc:Choice Requires="x15ac"><x15ac:absPath url="' + FOLDER.encode() + b'" '
        b'xmlns:x15ac="http://schemas.microsoft.com/office/spreadsheetml/2010/11/ac"/>'
        b"</mc:Choice></mc:AlternateContent>"
    )
    _rewrite(
        path,
        {
            "xl/workbook.xml": lambda d: re.sub(
                rb"(<workbook\b[^>]*>)", lambda m: m.group(1) + saved_in, d, count=1
            )
        },
    )
    return path


def make_powerpoint(path):
    import pptx

    deck = pptx.Presentation()
    deck.slides.add_slide(deck.slide_layouts[0]).shapes.title.text = "Launch plan"
    deck.core_properties.author = NAME
    deck.save(path)
    return path


def make_annotated_pdf(path):
    make_pdf(path, ["Contract page one", "Page two"])
    doc = pymupdf.open(path)
    doc.set_metadata({"author": NAME, "title": "Contract", "producer": "SecretWriter 1.0"})
    doc.set_xml_metadata(f"<x:xmpmeta xmlns:x='adobe:ns:meta/'><a>{NAME}</a></x:xmpmeta>")
    note = doc[0].add_text_annot((100, 100), "Please sign here")
    note.set_info(title=NAME)
    note.update()
    doc.save(path, incremental=True, encryption=pymupdf.PDF_ENCRYPT_KEEP)  # an earlier version
    doc.close()
    return path


def _labels(path) -> set[str]:
    return {f.label for f in metadata.inspect(path)}


def test_word_metadata_is_found(tmp_path):
    found = {f.label: f.detail for f in metadata.inspect(make_word(tmp_path / "plan.docx"))}
    assert found["Author"] == NAME and found["Title"] == "Secret plan"
    assert found["Company"] == "ACME Secret Ltd"
    assert NAME in found["Names of reviewers"]
    assert "Edit history" in found and found["Template path"] == TEMPLATE


def test_word_cleaned_keeps_text_comments_and_changes(tmp_path):
    import docx

    src = make_word(tmp_path / "plan.docx")
    original = src.read_bytes()
    result = metadata.clean_file(src)
    assert src.read_bytes() == original  # the original is never changed
    assert result.output.name == "plan (clean).docx"
    assert metadata.inspect(result.output) == []
    assert {"Author", "Company", "Edit history"} <= {f.label for f in result.removed}

    raw = b"".join(_part(result.output, n) for n in zipfile.ZipFile(result.output).namelist())
    for secret in (NAME.encode(), b"ACME", b"MaxMuster", b"rsid", b"2026-01-05"):
        assert secret not in raw
    cleaned = docx.Document(result.output)
    assert [c.text for c in cleaned.comments] == ["Check the numbers"]
    assert [c.author for c in cleaned.comments] == [doc_metadata.ANONYMOUS]
    body = _part(result.output, "word/document.xml")
    assert b"<w:ins" in body and b"Added later " in body  # the tracked change stays
    assert b'Target="Letter.dotx"' in _part(result.output, "word/_rels/settings.xml.rels")
    assert cleaned.paragraphs[0].text == "The plan for next year"


def test_untouched_parts_are_copied_unchanged(tmp_path):
    src = make_word(tmp_path / "plan.docx")
    out = metadata.clean_file(src).output
    with zipfile.ZipFile(src) as a, zipfile.ZipFile(out) as b:
        assert a.namelist() == b.namelist()  # same parts, same order
        for name in a.namelist():
            if not name.startswith(("docProps/", "word/")):
                assert a.read(name) == b.read(name), name


def test_excel_cleaned(tmp_path):
    import openpyxl

    src = make_excel(tmp_path / "budget.xlsx")
    found = {f.label: f.detail for f in metadata.inspect(src)}
    assert found["Saved in folder"] == FOLDER and NAME in found["Names of reviewers"]
    out = metadata.clean_file(src).output
    assert metadata.inspect(out) == []
    assert b"absPath" not in _part(out, "xl/workbook.xml")
    cell = openpyxl.load_workbook(out).active["A1"]
    assert cell.value == "Budget 2027" and cell.comment.text.endswith("Too high?")
    assert cell.comment.author == doc_metadata.ANONYMOUS


def test_powerpoint_cleaned(tmp_path):
    import pptx

    src = make_powerpoint(tmp_path / "launch.pptx")
    assert "Author" in _labels(src)
    out = metadata.clean_file(src).output
    assert metadata.inspect(out) == []
    deck = pptx.Presentation(out)
    assert deck.slides[0].shapes.title.text == "Launch plan" and deck.core_properties.author == ""


def test_pdf_cleaned_pages_stay_exactly_the_same(tmp_path):
    src = make_annotated_pdf(tmp_path / "contract.pdf")
    found = {f.label: f.detail for f in metadata.inspect(src)}
    assert found["Author"] == NAME and found["Software"] == "SecretWriter 1.0"
    assert {"XMP metadata", "Earlier versions", "Names of reviewers"} <= set(found)

    out = metadata.clean_file(src).output
    assert metadata.inspect(out) == []
    assert NAME.encode() not in out.read_bytes() and b"SecretWriter" not in out.read_bytes()
    with pymupdf.open(src) as a, pymupdf.open(out) as b:
        assert b.version_count == 1
        assert [p.read_contents() for p in a] == [p.read_contents() for p in b]
        assert [p.get_text() for p in a] == [p.get_text() for p in b]
        [note] = list(b[0].annots())
        assert note.info["content"] == "Please sign here"  # the note itself stays


def test_pdf_restrictions_are_kept(tmp_path):
    src = make_pdf(tmp_path / "locked.pdf", ["text"])
    doc = pymupdf.open(src)
    doc.set_metadata({"author": NAME})
    data = doc.tobytes(
        encryption=pymupdf.PDF_ENCRYPT_AES_256, owner_pw="owner-secret", permissions=0
    )
    out = doc_metadata.clean_bytes("pdf", data)
    with pymupdf.open("pdf", data) as before, pymupdf.open("pdf", out) as cleaned:
        assert cleaned.permissions == before.permissions != -1  # still restricted
        assert not cleaned.needs_pass and cleaned.metadata["author"] == ""


def test_password_protected_pdf_is_refused(tmp_path):
    src = make_pdf(tmp_path / "plain.pdf", ["secret"])
    locked = tmp_path / "locked.pdf"
    with pymupdf.open(src) as doc:
        doc.save(locked, encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="pw", owner_pw="pw")
    with pytest.raises(ConversionError, match="Remove the password first"):
        metadata.clean_file(locked, tmp_path / "out")
    assert not (tmp_path / "out").exists() or not any((tmp_path / "out").iterdir())


def test_signed_pdf_is_refused(tmp_path, monkeypatch):
    src = make_annotated_pdf(tmp_path / "signed.pdf")
    monkeypatch.setattr(pymupdf.Document, "get_sigflags", lambda self: 3)
    with pytest.raises(ConversionError, match="digital signature"):
        metadata.clean_file(src)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["signed.pdf"]


def test_nothing_saved_if_content_would_change(tmp_path, monkeypatch):
    src = make_word(tmp_path / "plan.docx")
    real = doc_metadata._clean_part

    def careless(name, data):
        data = real(name, data)
        return data.replace(b"next year", b"last year") if name == "word/document.xml" else data

    monkeypatch.setattr(doc_metadata, "_clean_part", careless)
    with pytest.raises(ConversionError, match="changes the content"):
        metadata.clean_file(src)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["plan.docx"]


def test_old_office_formats_get_a_hint(tmp_path):
    from azoth import formats

    src = tmp_path / "old.doc"
    src.write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\0" * 600)
    if formats.detect(src) is None or formats.detect(src).id != "doc":
        pytest.skip("not detected as DOC")
    with pytest.raises(ConversionError, match="Convert it to DOCX first"):
        metadata.inspect(src)


def test_clean_command_works_for_documents(tmp_path, capsys):
    src = make_word(tmp_path / "plan.docx")
    assert cli(["clean", str(src)]) == 0
    assert (tmp_path / "plan (clean).docx").exists()


def test_damaged_office_file_gives_clear_error():
    with pytest.raises(ConversionError, match="Cannot read"):
        doc_metadata.inspect_bytes("docx", b"PK\x03\x04 not really a zip")
    with pytest.raises(ConversionError, match="has a password"):
        doc_metadata.clean_bytes("xlsx", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\0" * 100)


def test_round_trip_through_io_is_unchanged():
    # A file that has nothing to remove stays valid and still has nothing to remove.
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("[Content_Types].xml", "<Types/>")
        zf.writestr("xl/workbook.xml", "<workbook/>")
    cleaned = doc_metadata.clean_bytes("xlsx", buf.getvalue())
    assert doc_metadata.inspect_bytes("xlsx", cleaned) == []
