from pathlib import Path

from fileconv.format_list import build_markdown, conversion_table

DOC = Path(__file__).resolve().parent.parent / "docs" / "FORMATS.md"


def test_formats_doc_is_up_to_date():
    assert DOC.read_text(encoding="utf-8") == build_markdown(), (
        "docs/FORMATS.md is out of date. Run: fileconv formats --markdown docs/FORMATS.md"
    )


def test_conversion_table_splits_libreoffice_targets():
    rows = {r.format.id: r for r in conversion_table()}
    pdf = rows["pdf"]
    assert "docx" in {t.id for t in pdf.right_away}
    assert "odt" in {t.id for t in pdf.needs_libreoffice}
    assert rows["docx"].right_away == []
    assert "pdf" in {t.id for t in rows["docx"].needs_libreoffice}
