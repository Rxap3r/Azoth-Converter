"""PDF → Excel: tables become cells, numbers only become numbers when they're clear."""

import pymupdf
import pytest
from conftest import make_pdf, make_scanned_pdf
from openpyxl import load_workbook

from azoth.converters import ConversionError
from azoth.converters.pdf_excel import decimal_hint, parse_number
from azoth.engine import Engine

TABLE_HTML = """
<p>Monthly report</p>
<table>
<tr><th colspan="3" style="background-color:#ccddee">Sales (CHF)</th></tr>
<tr><th>Item</th><th>Amount</th><th>Share</th></tr>
<tr><td>Chairs, black</td><td>CHF 1'240.50</td><td>8.1 %</td></tr>
<tr><td>Lamps</td><td>CHF 45.00</td><td>12 %</td></tr>
<tr><td>=SUM(A1:A2)</td><td>007</td><td>1.234</td></tr>
</table>
<p>Thank you</p>
"""


def make_table_pdf(path, html=TABLE_HTML):
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    css = "th, td {border: 1px solid black; padding: 4px;} body {font-family: sans-serif;}"
    page.insert_htmlbox(pymupdf.Rect(50, 50, 545, 800), html, css=css)
    doc.save(path)
    doc.close()
    return path


def values(ws):
    return [[c.value for c in row if c.value is not None] for row in ws.iter_rows()]


def test_table_becomes_cells(tmp_path):
    src = make_table_pdf(tmp_path / "report.pdf")
    [out] = Engine().convert(src, "xlsx", tmp_path / "out").outputs
    assert out.name == "report.xlsx"
    ws = load_workbook(out).worksheets[0]
    assert ws.title == "Page 1"
    rows = [r for r in values(ws) if r]
    assert rows[0] == ["Monthly report"]
    assert rows[1] == ["Sales (CHF)"]
    assert rows[2] == ["Item", "Amount", "Share"]
    assert rows[3] == ["Chairs, black", 1240.5, 0.081]
    assert rows[-1] == ["Thank you"]
    # The title spans the three columns and keeps its background colour.
    title = next(c for row in ws.iter_rows() for c in row if c.value == "Sales (CHF)")
    assert any(title.coordinate in rng and rng.size["columns"] == 3 for rng in ws.merged_cells)
    assert title.fill.fgColor.rgb.endswith("CCDDEE")
    assert title.font.bold
    # Numbers show as in the PDF.
    amount = next(c for row in ws.iter_rows() for c in row if c.value == 1240.5)
    assert amount.number_format == '"CHF "#,##0.00'


def test_unclear_values_stay_text(tmp_path):
    src = make_table_pdf(tmp_path / "report.pdf")
    [out] = Engine().convert(src, "xlsx", tmp_path).outputs
    ws = load_workbook(out).worksheets[0]
    row = next(r for r in values(ws) if r and r[0] == "=SUM(A1:A2)")
    assert row[:2] == ["=SUM(A1:A2)", "007"]  # never a formula, or a code as a number
    assert row[2] == 1.234  # "1.234" is clear here: the table writes "45.00", "8.1"
    cell = next(c for r in ws.iter_rows() for c in r if c.value == "=SUM(A1:A2)")
    assert cell.data_type == "s"


def test_one_sheet_per_page_and_text_kept(sample_pdf, tmp_path):
    [out] = Engine().convert(sample_pdf, "xlsx", tmp_path).outputs
    wb = load_workbook(out)
    assert wb.sheetnames == ["Page 1", "Page 2", "Page 3"]
    assert any("First page text" in str(v) for r in values(wb["Page 1"]) for v in r)


def test_workbook_does_not_name_a_creator(sample_pdf, tmp_path):
    [out] = Engine().convert(sample_pdf, "xlsx", tmp_path).outputs
    import zipfile

    core = zipfile.ZipFile(out).read("docProps/core.xml").decode()
    assert "creator" not in core and "openpyxl" not in core


def test_scan_is_refused_with_a_clear_message(tmp_path, sample_png):
    src = make_scanned_pdf(tmp_path / "scan.pdf", sample_png)
    with pytest.raises(ConversionError, match="scan"):
        Engine().convert(src, "xlsx", tmp_path / "out")


def test_pdf_offers_excel_after_word():
    targets = [t.id for t in Engine().targets_for("pdf")]
    assert "xlsx" in targets
    assert "csv" not in targets and "ods" not in targets  # would lose all sheets but one


def test_cancel_between_pages(tmp_path):
    from azoth.converters import ConversionCancelled

    src = make_pdf(tmp_path / "long.pdf", ["a", "b", "c"])
    with pytest.raises(ConversionCancelled):
        Engine().convert(src, "xlsx", tmp_path / "out", cancel_event=_set())
    assert not (tmp_path / "out" / "long.xlsx").exists()


@pytest.mark.parametrize(
    ("text", "hint", "expected"),
    [
        ("12'400", None, (12400, "#,##0")),
        ("12’400.75", None, (12400.75, "#,##0.00")),
        ("1,234.50", None, (1234.5, "#,##0.00")),
        ("1.234,50", None, (1234.5, "#,##0.00")),
        ("1.234.567", None, (1234567, "#,##0")),
        ("45,50", None, (45.5, "0.00")),
        ("-3", None, (-3, "General")),
        ("−3.5", None, (-3.5, "0.0")),
        ("8.1 %", None, (0.081, "0.0%")),
        ("CHF 240.00", None, (240, '"CHF "0.00')),
        ("240.00 €", None, (240, '0.00" €"')),
        ("1.234", ".", (1.234, "0.000")),
        ("1.234", ",", (1234, "#,##0")),
        ("0.5", None, (0.5, "0.0")),
    ],
)
def test_clear_numbers(text, hint, expected):
    assert parse_number(text, hint) == expected


@pytest.mark.parametrize(
    "text",
    [
        "1.234",  # one thousand or one point two: unclear without a hint
        "1,234",
        "007",  # a code
        "0041 44",
        "1234567890123456",  # too long for Excel: an account number
        "12.11.2026",  # a date
        "1'23",  # not thousands
        "Q1",
        "1.234,5.6",
        "",
    ],
)
def test_unclear_numbers_stay_text(text):
    assert parse_number(text) is None


def test_decimal_hint_from_the_document():
    assert decimal_hint(["1'200.50", "Total"]) == "."
    assert decimal_hint(["45,50", "1.234.567"]) == ","
    assert decimal_hint(["1.234", "12"]) is None  # no evidence
    assert decimal_hint(["45.50", "45,50"]) is None  # contradictory


def _set():
    import threading

    event = threading.Event()
    event.set()
    return event


# --- "Tables only" and "All pages on one sheet" ----------------------------------------


def make_statement_pdf(path, pages=3):
    """Like a bank statement: a heading on each page and a table that goes on over the
    pages, its header row repeated on each one."""
    doc = pymupdf.open()
    css = "th, td {border: 1px solid black; padding: 4px;} body {font-family: sans-serif;}"
    for n in range(1, pages + 1):
        rows = "".join(
            f"<tr><td>{n:02d}.0{d}.2026</td><td>Shop {n}{d}</td><td>-{n}{d}.50</td></tr>"
            for d in range(1, 4)
        )
        html = (
            f"<p>Statement, page {n}</p><table><tr><th>Date</th><th>Text</th>"
            f"<th>Amount</th></tr>{rows}</table>"
        )
        doc.new_page(width=595, height=842).insert_htmlbox(
            pymupdf.Rect(50, 50, 545, 800), html, css=css
        )
    doc.save(path)
    doc.close()
    return path


def _convert(src, tmp_path, **options):
    [out] = Engine().convert(src, "xlsx", tmp_path / "out", options=options).outputs
    return load_workbook(out)


def test_tables_only_leaves_out_the_other_text(tmp_path):
    wb = _convert(make_statement_pdf(tmp_path / "s.pdf"), tmp_path, tables_only=True)
    assert wb.sheetnames == ["Page 1", "Page 2", "Page 3"]
    rows = values(wb["Page 2"])
    assert rows[0] == ["Date", "Text", "Amount"]  # the table starts at the top
    assert not any("Statement" in str(v) for r in rows for v in r)


def test_all_pages_on_one_sheet_keeps_everything_in_order(tmp_path):
    wb = _convert(make_statement_pdf(tmp_path / "s.pdf"), tmp_path, one_sheet=True)
    assert wb.sheetnames == ["All pages"]
    rows = [r for r in values(wb.active) if r]
    assert [r[0] for r in rows if str(r[0]).startswith("Statement")] == [
        "Statement, page 1", "Statement, page 2", "Statement, page 3"
    ]  # fmt: skip
    assert sum(r == ["Date", "Text", "Amount"] for r in rows) == 3  # the text sits between


def test_both_make_one_continuous_table(tmp_path):
    """Tables only + one sheet: the table that goes on over the pages becomes one table
    (header once, no empty rows), ready to sort and filter."""
    src = make_statement_pdf(tmp_path / "s.pdf")
    wb = _convert(src, tmp_path, tables_only=True, one_sheet=True)
    rows = values(wb.active)
    assert rows[0] == ["Date", "Text", "Amount"]
    assert len(rows) == 1 + 9 and all(rows)  # header + 3 pages × 3 rows, no gaps
    assert [r[1] for r in rows[1:4]] == ["Shop 11", "Shop 12", "Shop 13"]
    assert rows[-1] == ["03.03.2026", "Shop 33", -33.5]


def test_different_tables_stay_apart_on_one_sheet():
    from azoth.converters.pdf_excel import Cell, Table, _continues

    def table(*header):
        cells = [Cell(0, j, 1, 1, text=t) for j, t in enumerate(header)]
        cells += [Cell(1, j, 1, 1, text="x") for j in range(len(header))]
        return Table(top=0, rows=2, cols=len(header), widths=[50] * len(header), cells=cells)

    assert _continues(table("Date", "Amount"), table("Date", "Amount"))
    assert not _continues(table("Date", "Amount"), table("Item", "Price"))
    assert not _continues(table("Date", "Amount"), table("Date", "Amount", "Total"))
    assert not _continues(None, table("Date", "Amount"))
    assert not _continues(table("", ""), table("", ""))  # empty headers say nothing


def test_tables_only_without_tables_explains(sample_pdf, tmp_path):
    with pytest.raises(ConversionError, match="Tables only"):
        Engine().convert(sample_pdf, "xlsx", tmp_path, options={"tables_only": True})


def test_cli_excel_options(tmp_path, capsys):
    from azoth.cli import main

    src = make_statement_pdf(tmp_path / "s.pdf")
    assert main(["convert", str(src), "--to", "xlsx", "--tables-only", "--one-sheet", "-q"]) == 0
    assert len(values(load_workbook(tmp_path / "s.xlsx").active)) == 10
    assert main(["convert", str(src), "--to", "docx", "--one-sheet"]) == 2
    assert "use --to xlsx" in capsys.readouterr().err
