"""PDF → Excel: tables in a PDF become real Excel cells.

PyMuPDF finds the tables (by their lines) and their cells, including merged ones.
The text of each cell is read from its box (PyMuPDF's own table text mixes up
spaces and decimal points). Each page becomes one sheet; text outside the tables is
kept too, one PDF line per row, so nothing on the page is lost.

Options: ``tables_only`` leaves out the text outside the tables; ``one_sheet`` puts all
pages on one sheet, where a table that goes on over several pages (with its header row
repeated on each page, as in bank statements) becomes one continuous table.

Numbers become real numbers (so Excel can calculate with them) only where their
meaning is clear: "12'400", "CHF 240.00", "8.1 %". "1.234" or "1,234" alone could be
one thousand or one point something, so such numbers stay text unless the rest of
the document shows which is the decimal sign. Numbers with leading zeros (IDs, postal
codes) and very long numbers (account numbers) stay text as well.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path

import pymupdf

from .base import ConversionContext, ConversionError, Converter
from .pdf import is_probably_scanned, open_pdf

POINTS_PER_CHAR = 5.25  # Excel column width unit (one "0" in Calibri 11) in PDF points
MAX_DIGITS = 15  # Excel keeps 15 significant digits; longer numbers stay text
CURRENCIES = ("CHF", "EUR", "USD", "GBP", "Fr.", "SFr.", "€", "$", "£")
_TEXT_FLAGS = pymupdf.TEXTFLAGS_DICT & ~pymupdf.TEXT_PRESERVE_LIGATURES  # "ﬃ" → "ffi"
_BOLD, _ITALIC = 16, 2  # PyMuPDF span flags
_NUMBER = re.compile(r"[+\-−]?\d(?:[\d'’ .,  ]*\d)?")
# Word's bullets in the Symbol and Wingdings fonts are private characters: "•" instead.
_SYMBOL_BULLETS = {0xF0B7: "•", 0xF0A7: "▪", 0xF0D8: "➢", 0xF0FC: "✓"}
_GROUP_SEPARATORS = "'’   "  # only ever used between thousands


# --- Reading the PDF ------------------------------------------------------------------


@dataclass
class Cell:
    row: int
    col: int
    rowspan: int
    colspan: int
    text: str = ""
    bold: bool = False
    italic: bool = False
    color: int = 0  # sRGB of the text
    fill: tuple[float, float, float] | None = None
    align: str | None = None  # "center" or "right" when the PDF text sits that way


@dataclass
class Table:
    top: float
    rows: int
    cols: int
    widths: list[float]  # column widths in points
    cells: list[Cell] = field(default_factory=list)


@dataclass
class TextRow:
    top: float
    texts: list[str]  # lines side by side on the page, left to right


def _span_center(span: dict) -> pymupdf.Point:
    x0, y0, x1, y1 = span["bbox"]
    return pymupdf.Point((x0 + x1) / 2, (y0 + y1) / 2)


def _boundaries(starts: list[float | None], end: float) -> list[float]:
    """Fill in missing column (or row) starts, so every one has a position."""
    known = [s for s in starts if s is not None]
    result, last = [], known[0] if known else 0.0
    for s in starts:
        last = s if s is not None else last
        result.append(last)
    return [*result, end]


def _read_table(tab, spans: list[dict], fills: list[tuple[pymupdf.Rect, tuple]]) -> Table:
    rows = tab.rows
    ncols = tab.col_count
    col_starts: list[float | None] = [None] * ncols
    for row in rows:
        for j, c in enumerate(row.cells):
            if c is not None and col_starts[j] is None:
                col_starts[j] = c[0]
    xs = _boundaries(col_starts, tab.bbox[2])
    ys = [row.bbox[1] for row in rows] + [tab.bbox[3]]
    table = Table(top=tab.bbox[1], rows=len(rows), cols=ncols, widths=[])
    table.widths = [max(xs[j + 1] - xs[j], 0) for j in range(ncols)]
    for i, row in enumerate(rows):
        for j, c in enumerate(row.cells):
            if c is None:
                continue  # covered by a merged cell
            rect = pymupdf.Rect(c)
            colspan = sum(1 for k in range(j, ncols) if xs[k] < rect.x1 - 1)
            rowspan = sum(1 for k in range(i, len(rows)) if ys[k] < rect.y1 - 1)
            cell = Cell(i, j, max(rowspan, 1), max(colspan, 1))
            mine = [s for s in spans if rect.contains(_span_center(s))]
            for s in mine:
                s["_used"] = True
            _fill_cell(cell, rect, mine, fills)
            table.cells.append(cell)
    return table


def _fill_cell(cell: Cell, rect: pymupdf.Rect, spans: list[dict], fills) -> None:
    lines: dict[tuple, list[dict]] = {}
    for s in spans:
        lines.setdefault(s["_line"], []).append(s)
    ordered = sorted(lines.values(), key=lambda ss: (round(ss[0]["bbox"][1]), ss[0]["bbox"][0]))
    # Line breaks inside a cell are almost always the PDF wrapping long text.
    cell.text = " ".join(t for t in ("".join(s["text"] for s in ss).strip() for ss in ordered) if t)
    visible = [s for s in spans if s["text"].strip()]
    if visible:
        cell.bold = all(s["flags"] & _BOLD or "bold" in s["font"].lower() for s in visible)
        cell.italic = all(s["flags"] & _ITALIC for s in visible)
        cell.color = visible[0]["color"]
        left = min(s["bbox"][0] for s in visible) - rect.x0
        right = rect.x1 - max(s["bbox"][2] for s in visible)
        if left > 4 and abs(left - right) < 3:
            cell.align = "center"
        elif left > right + 4:
            cell.align = "right"
    center = pymupdf.Point((rect.x0 + rect.x1) / 2, (rect.y0 + rect.y1) / 2)
    around = [(r, color) for r, color in fills if r.contains(center)]
    if around:
        cell.fill = min(around, key=lambda rc: rc[0].get_area())[1]


def _filled_rects(page: pymupdf.Page) -> list[tuple[pymupdf.Rect, tuple]]:
    """Coloured backgrounds on the page (white ones are ignored)."""
    result = []
    for d in page.get_drawings():
        fill = d.get("fill")
        if fill and tuple(round(c, 3) for c in fill[:3]) != (1.0, 1.0, 1.0):
            result.append((pymupdf.Rect(d["rect"]), tuple(fill[:3])))
    return result


def read_page(page: pymupdf.Page) -> list[Table | TextRow]:
    """Tables and the other text lines of a page, from top to bottom."""
    spans: list[dict] = []
    for b, block in enumerate(page.get_text("dict", flags=_TEXT_FLAGS)["blocks"]):
        for n, line in enumerate(block.get("lines", [])):
            for s in line["spans"]:
                s["_line"] = (b, n)
                spans.append(s)
    fills = _filled_rects(page)
    items: list[Table | TextRow] = []
    try:
        found = page.find_tables().tables
    except Exception:  # a damaged drawing on the page: keep its text at least
        found = []
    for tab in found:
        items.append(_read_table(tab, spans, fills))

    lines: dict[tuple, list[dict]] = {}
    for s in spans:
        if not s.get("_used"):
            lines.setdefault(s["_line"], []).append(s)
    placed: list[tuple[float, float, float, str]] = []  # (top, bottom, left, text)
    for ss in lines.values():
        text = "".join(s["text"] for s in ss).strip()
        if text:
            box = pymupdf.Rect(ss[0]["bbox"])
            for s in ss[1:]:
                box |= s["bbox"]
            placed.append((box.y0, box.y1, box.x0, text))
    # Lines at the same height ("Date: …      Invoice no. …") share one row.
    placed.sort()
    group: list[tuple[float, float, float, str]] = []
    for line in [*placed, None]:
        if group and (line is None or line[0] > (group[0][0] + group[0][1]) / 2):
            items.append(TextRow(group[0][0], [t for *_, t in sorted(group, key=lambda g: g[2])]))
            group = []
        if line is not None:
            group.append(line)
    items.sort(key=lambda it: it.top)
    return items


# --- Numbers --------------------------------------------------------------------------


def _split_affixes(text: str) -> tuple[str, str, str]:
    """("CHF ", "240.00", "") for "CHF 240.00"; ("", "8.1", " %") for "8.1 %"."""
    prefix = suffix = ""
    for cur in CURRENCIES:
        if text.startswith(cur) and len(text) > len(cur):
            prefix, text = text[: len(cur)], text[len(cur) :]
            break
    if text.endswith("%"):
        suffix, text = "%", text[:-1]
    else:
        for cur in CURRENCIES:
            if text.endswith(cur) and len(text) > len(cur):
                suffix, text = text[-len(cur) :], text[: -len(cur)]
                break
    core = text.strip()
    prefix += text[: len(text) - len(text.lstrip())]
    suffix = text[len(text.rstrip()) :] + suffix
    return prefix, core, suffix


def decimal_hint(evidence: list[str]) -> str | None:
    """Which decimal sign ("." or ",") the numbers in a document use, if they show it."""
    votes = {".": 0, ",": 0}
    for text in evidence:
        core = _split_affixes(text.strip())[1]
        if not _NUMBER.fullmatch(core):
            continue
        dots, commas = core.count("."), core.count(",")
        if dots and commas:  # "1,234.50": the last sign is the decimal one
            votes["." if core.rfind(".") > core.rfind(",") else ","] += 1
        elif dots + commas > 1:  # "1.234.567": these sign group thousands
            votes["," if dots else "."] += 1
        elif dots + commas == 1:
            sep = "." if dots else ","
            after = len(core) - core.index(sep) - 1
            if after != 3 or any(g in core for g in _GROUP_SEPARATORS):
                votes[sep] += 1  # "45.50", "12'400.750"
    if votes["."] and not votes[","]:
        return "."
    if votes[","] and not votes["."]:
        return ","
    return None


def _valid_groups(integer: str, separators: str) -> bool:
    groups = re.split(f"[{re.escape(separators)}]", integer) if separators else [integer]
    return (1 <= len(groups[0]) <= 3 or len(groups) == 1) and all(len(g) == 3 for g in groups[1:])


def parse_number(text: str, hint: str | None = None) -> tuple[int | float, str] | None:
    """(value, Excel number format) when ``text`` is clearly a number, else None.

    ``hint``: the document's decimal sign, from ``decimal_hint``.
    """
    prefix, core, suffix = _split_affixes(text.strip())
    if not _NUMBER.fullmatch(core):
        return None
    sign = -1 if core[0] in "-−" else 1
    core = core.lstrip("+-−")
    dots, commas = core.count("."), core.count(",")
    if dots and commas:
        decimal = "." if core.rfind(".") > core.rfind(",") else ","
    elif dots + commas == 1:
        sep = "." if dots else ","
        after = len(core) - core.index(sep) - 1
        if after != 3 or any(g in core for g in _GROUP_SEPARATORS):
            decimal = sep  # "45.50", "12'400.750"
        elif hint is None:
            return None  # "1.234": one thousand or one point two? Unclear: keep the text.
        else:
            decimal = sep if hint == sep else ""
    else:
        decimal = ""  # "1.234.567", "1,234,567" (only thousands) or no sign at all
    if decimal:
        integer, _, fraction = core.rpartition(decimal)
    else:
        integer, fraction = core, ""
    group_chars = set(re.sub(r"\d", "", integer))
    if len(group_chars) > 1 or any(c == decimal for c in group_chars):
        return None
    if not _valid_groups(integer, "".join(group_chars)) or not fraction.isdigit() and fraction:
        return None
    digits = re.sub(r"\D", "", integer)
    if len(digits) > 1 and digits[0] == "0":
        return None  # "007", "0041": a code, not a number
    if len(digits.lstrip("0")) + len(fraction) > MAX_DIGITS:
        return None
    try:
        value = Decimal(f"{digits}.{fraction}" if fraction else digits) * sign
    except InvalidOperation:
        return None
    number_format = ("#,##0" if group_chars else "0") + (
        "." + "0" * len(fraction) if fraction else ""
    )
    if suffix.strip() == "%":
        value /= 100
        number_format += "%"
        suffix = ""
    if prefix:
        number_format = f'"{prefix}"' + number_format
    if suffix:
        number_format += f'"{suffix}"'
    if number_format == "0":
        number_format = "General"
    result = float(value) if fraction or "%" in number_format else int(value)
    return result, number_format


# --- Writing the workbook -------------------------------------------------------------


def _clean(text: str) -> str:
    """Text without the control characters an Excel file can't hold."""
    from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE

    return ILLEGAL_CHARACTERS_RE.sub("", text.translate(_SYMBOL_BULLETS))


def _hex(color: tuple[float, float, float]) -> str:
    return "".join(f"{round(max(0.0, min(1.0, c)) * 255):02X}" for c in color)


def _set_text(cell, text: str) -> None:
    cell.value = _clean(text)
    cell.data_type = "s"  # "=SUM(…)" in a PDF stays text, never becomes a formula


class _SheetWriter:
    """Writes tables and text rows one below the other on one sheet."""

    def __init__(self, ws, hint: str | None, join_tables: bool = False) -> None:
        from openpyxl.styles import Border, Side

        self.ws = ws
        self.hint = hint
        self.join_tables = join_tables  # a table going on over pages becomes one
        self.row = 1  # the next free row
        self.widths: dict[int, float] = {}  # column → width in Excel units
        self.last_table: Table | None = None  # the table just written, if nothing followed
        thin = Side(style="thin", color="808080")
        self.border = Border(left=thin, right=thin, top=thin, bottom=thin)

    def add(self, item: Table | TextRow) -> None:
        if isinstance(item, TextRow):
            self._gap_after_table()
            for col, text in enumerate(item.texts, start=1):
                _set_text(self.ws.cell(self.row, col), text)
            self.row += 1
        elif self.join_tables and _continues(self.last_table, item):
            # The same table goes on (a long list over several pages): its repeated
            # header row is left out, so the sheet holds one table that can be sorted.
            self._table(item, skip_header=True)
        else:
            self._gap_after_table()
            self._table(item)

    def finish(self) -> None:
        from openpyxl.utils import get_column_letter

        for j, w in self.widths.items():
            self.ws.column_dimensions[get_column_letter(j)].width = round(min(max(w, 4), 100), 1)

    def _gap_after_table(self) -> None:
        if self.last_table is not None:
            self.row += 1  # one empty row after each table
            self.last_table = None

    def _table(self, table: Table, skip_header: bool = False) -> None:
        for j, w in enumerate(table.widths, start=1):
            self.widths[j] = max(self.widths.get(j, 0), w / POINTS_PER_CHAR)
        first = 1 if skip_header else 0
        for c in table.cells:
            if c.row >= first:
                self._cell(c, self.row + c.row - first)
        self.row += table.rows - first
        self.last_table = table

    def _cell(self, c: Cell, r: int) -> None:
        from openpyxl.styles import Alignment, Font, PatternFill

        col = 1 + c.col
        if c.rowspan > 1 or c.colspan > 1:
            self.ws.merge_cells(
                start_row=r, start_column=col,
                end_row=r + c.rowspan - 1, end_column=col + c.colspan - 1,
            )  # fmt: skip
            for rr in range(r, r + c.rowspan):
                for cc in range(col, col + c.colspan):
                    self.ws.cell(rr, cc).border = self.border
        cell = self.ws.cell(r, col)
        parsed = parse_number(c.text, self.hint) if c.text else None
        if parsed:
            cell.value, cell.number_format = parsed
        elif c.text:
            _set_text(cell, c.text)
        cell.border = self.border
        cell.font = Font(
            name="Calibri",
            size=11,
            bold=c.bold,
            italic=c.italic,
            color=f"{c.color:06X}" if c.color else None,
        )
        if c.fill:
            cell.fill = PatternFill("solid", fgColor=_hex(c.fill))
        cell.alignment = Alignment(horizontal=c.align, vertical="top", wrap_text=len(c.text) > 30)


def _header(table: Table) -> tuple[str, ...] | None:
    """The texts of the table's first row, if it is a plain row (no merged cells)."""
    first = [c for c in table.cells if c.row == 0]
    if table.rows < 2 or any(c.rowspan > 1 or c.colspan > 1 for c in first):
        return None
    return tuple(c.text for c in sorted(first, key=lambda c: c.col))


def _continues(previous: Table | None, table: Table) -> bool:
    """True if ``table`` carries on ``previous``: same columns, same header row."""
    if previous is None or previous.cols != table.cols:
        return False
    header = _header(table)
    return header is not None and any(header) and header == _header(previous)


def write_workbook(
    pages: list[list[Table | TextRow]], dst: Path, *, one_sheet: bool = False
) -> None:
    """One sheet per page, or with ``one_sheet`` all pages on one sheet, where a table
    that goes on over several pages becomes one table."""
    from openpyxl import Workbook

    hint = decimal_hint(
        [c.text for p in pages for it in p if isinstance(it, Table) for c in it.cells]
    )
    wb = Workbook()
    wb.remove(wb.active)
    wb.properties.creator = None  # not "openpyxl"; nothing about the user either
    if one_sheet:
        sheets = [("All pages", [it for items in pages for it in items])]
    else:
        sheets = [(f"Page {n}", items) for n, items in enumerate(pages, start=1)]
    for name, items in sheets:
        writer = _SheetWriter(wb.create_sheet(name), hint, join_tables=one_sheet)
        for item in items:
            writer.add(item)
        writer.finish()
    wb.save(dst)


class PdfToExcelConverter(Converter):
    id = "pdf-xlsx"
    label = "PyMuPDF + openpyxl"
    priority = 20

    def first_only(self, src: str, dst: str) -> bool:
        return True  # no Word → PDF → Excel chains

    def final_only(self, src: str, dst: str) -> bool:
        return True  # one sheet per page: CSV would keep only the first

    def capabilities(self) -> Iterable[tuple[str, str]]:
        yield "pdf", "xlsx"

    def quality_note(self, src: str, dst: str) -> str | None:
        return (
            "Tables with visible lines become Excel cells, one sheet per page; other text "
            "is kept line by line. Numbers become real numbers only where their meaning "
            "is clear. Check important figures."
        )

    def convert(self, src: Path, dst: Path, ctx: ConversionContext) -> list[Path]:
        if is_probably_scanned(src):
            raise ConversionError(
                "This PDF looks like a scan: pictures of pages, with no text that you can "
                "select. Azoth Converter cannot read tables from scans. Convert the PDF to "
                "Word instead, which uses text recognition."
            )
        tables_only = bool(ctx.option("tables_only", False))
        pages: list[list[Table | TextRow]] = []
        with open_pdf(src) as doc:
            total = doc.page_count
            for i, page in enumerate(doc):
                ctx.check_cancelled()
                ctx.progress(i / max(total, 1), f"Page {i + 1}/{total}")
                items = read_page(page)
                if tables_only:
                    items = [it for it in items if isinstance(it, Table)]
                pages.append(items)
        if not any(pages):
            if tables_only:
                raise ConversionError(
                    "Azoth Converter found no tables with visible lines in this PDF. To get "
                    "the text line by line, do not select “Tables only”."
                )
            raise ConversionError("This PDF has no text for Excel.")
        ctx.check_cancelled()
        write_workbook(pages, dst, one_sheet=bool(ctx.option("one_sheet", False)))
        return [dst]
