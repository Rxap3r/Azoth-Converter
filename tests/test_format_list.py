from pathlib import Path

import pytest

from fileconv.converters.office import find_soffice
from fileconv.format_list import build_markdown

DOC = Path(__file__).resolve().parent.parent / "docs" / "FORMATS.md"


@pytest.mark.skipif(find_soffice() is None, reason="LibreOffice not installed")
def test_formats_doc_is_up_to_date():
    expected = build_markdown()
    assert DOC.read_text(encoding="utf-8") == expected, (
        "docs/FORMATS.md is out of date. Run: fileconv formats --markdown docs/FORMATS.md"
    )
