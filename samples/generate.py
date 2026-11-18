"""Generate the sample files in this folder for manual and automated testing.

Run from the repository root:

    python samples/generate.py

Needs the dev dependencies (pip install -e ".[dev]") and LibreOffice for the
ODT/RTF/DOC/XLS/ODS/ODP/PPT copies and the PDF made from Word.
All content is made up.
"""

from __future__ import annotations

import io
import math
import random
import shutil
import sys
from pathlib import Path

import docx
import pymupdf
from docx.enum.section import WD_ORIENT, WD_SECTION
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK, WD_COLOR_INDEX
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Inches, Pt, RGBColor
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent / "src"))

from fileconv.converters.office import find_soffice  # noqa: E402
from fileconv.engine import Engine  # noqa: E402

random.seed(42)

LOREM = (
    "File conversion should be simple, private and reliable. This paragraph exists "
    "to fill the page with realistic text so line wrapping, justification and "
    "hyphenation can be compared between the original and the converted file. "
)
UNICODE_LINE = (
    "Umlaute und Sonderzeichen: äöü ÄÖÜ ß · é è ê à ç · ñ · ø å · € £ ¥ · « » „“ · ½ ° ± × ÷ · ✓ ★"
)


# --- helpers -------------------------------------------------------------------


def font(size: int) -> ImageFont.ImageFont:
    try:
        return ImageFont.truetype("DejaVuSans.ttf", size)
    except OSError:
        return ImageFont.load_default(size)


def chart_png(width=900, height=450) -> bytes:
    """A simple bar chart image."""
    img = Image.new("RGB", (width, height), "white")
    d = ImageDraw.Draw(img)
    values = [42, 55, 61, 48, 73, 80, 66, 90]
    labels = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug"]
    colors = ["#2a78d6", "#1fa37a", "#e8a33b", "#d6455d"]
    base, left, bar_w = height - 60, 60, (width - 100) // len(values)
    d.line((left, 20, left, base), fill="black", width=2)
    d.line((left, base, width - 20, base), fill="black", width=2)
    for i, (v, label) in enumerate(zip(values, labels, strict=True)):
        x0 = left + 10 + i * bar_w
        top = base - v * (base - 40) / 100
        d.rectangle((x0, top, x0 + bar_w - 20, base), fill=colors[i % len(colors)])
        d.text((x0 + 5, base + 10), label, fill="black", font=font(18))
        d.text((x0 + 5, top - 24), str(v), fill="black", font=font(16))
    d.text((left + 10, 0), "Monthly sales (sample data)", fill="black", font=font(20))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def landscape_photo(width=1600, height=1067) -> Image.Image:
    """A made-up landscape 'photo': sky, sun, hills, a lake."""
    img = Image.new("RGB", (width, height))
    d = ImageDraw.Draw(img)
    for y in range(height):  # sky gradient
        t = y / height
        d.line((0, y, width, y), fill=(int(90 + 120 * t), int(150 + 80 * t), int(235 - 30 * t)))
    d.ellipse((width * 0.72, height * 0.1, width * 0.84, height * 0.28), fill=(255, 230, 120))
    for i, color in enumerate([(70, 120, 80), (50, 100, 60), (35, 80, 45)]):
        pts = [(0, height)]
        for x in range(0, width + 40, 40):
            y = height * (0.45 + 0.1 * i) + math.sin(x / (180 + 60 * i) + i) * 60
            pts.append((x, y))
        pts.append((width, height))
        d.polygon(pts, fill=color)
    d.rectangle((0, height * 0.8, width, height), fill=(60, 110, 170))
    for _ in range(4000):  # a bit of noise so it compresses like a photo
        x, y = random.randrange(width), random.randrange(height)
        r, g, b = img.getpixel((x, y))
        n = random.randint(-25, 25)
        img.putpixel((x, y), (max(0, r + n), max(0, g + n), max(0, b + n)))
    d.text((30, height - 60), "Sample photo - File-Converter", fill="white", font=font(36))
    return img


def shade_cell(cell, hex_color: str) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), hex_color)
    tc_pr.append(shd)


def add_field(paragraph, instruction: str) -> None:
    """Insert a Word field such as PAGE or NUMPAGES."""
    fld = OxmlElement("w:fldSimple")
    fld.set(qn("w:instr"), instruction)
    run = OxmlElement("w:r")
    text = OxmlElement("w:t")
    text.text = "1"
    run.append(text)
    fld.append(run)
    paragraph._p.append(fld)


def add_hyperlink(paragraph, url: str, text: str) -> None:
    part = paragraph.part
    r_id = part.relate_to(
        url,
        "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink",
        is_external=True,
    )
    link = OxmlElement("w:hyperlink")
    link.set(qn("r:id"), r_id)
    run = OxmlElement("w:r")
    r_pr = OxmlElement("w:rPr")
    color = OxmlElement("w:color")
    color.set(qn("w:val"), "0563C1")
    underline = OxmlElement("w:u")
    underline.set(qn("w:val"), "single")
    r_pr.extend([color, underline])
    run.append(r_pr)
    t = OxmlElement("w:t")
    t.text = text
    run.append(t)
    link.append(run)
    paragraph._p.append(link)


def set_columns(section, number: int) -> None:
    cols = section._sectPr.find(qn("w:cols"))
    if cols is None:
        cols = OxmlElement("w:cols")
        section._sectPr.append(cols)
    cols.set(qn("w:num"), str(number))
    cols.set(qn("w:space"), "708")


def page_numbers_in_footer(section) -> None:
    p = section.footer.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.add_run("Page ")
    add_field(p, "PAGE")
    p.add_run(" of ")
    add_field(p, "NUMPAGES")


# --- Word ----------------------------------------------------------------------


def word_formatted_report(path: Path) -> None:
    d = docx.Document()
    section = d.sections[0]
    section.header.paragraphs[0].text = "Sample Company Ltd. · Internal report · CONFIDENTIAL"
    section.header.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.RIGHT
    page_numbers_in_footer(section)

    d.add_heading("Annual Report 2026", 0)
    p = d.add_paragraph("A test document with ")
    p.add_run("bold").bold = True
    p.add_run(", ")
    p.add_run("italic").italic = True
    p.add_run(", ")
    p.add_run("underlined").underline = True
    p.add_run(", ")
    r = p.add_run("coloured")
    r.font.color.rgb = RGBColor(0xC0, 0x1F, 0x3A)
    p.add_run(", ")
    r = p.add_run("highlighted")
    r.font.highlight_color = WD_COLOR_INDEX.YELLOW
    p.add_run(", ")
    r = p.add_run("strikethrough")
    r.font.strike = True
    p.add_run(", H")
    r = p.add_run("2")
    r.font.subscript = True
    p.add_run("O, E = mc")
    r = p.add_run("2")
    r.font.superscript = True
    p.add_run(" and ")
    r = p.add_run("different fonts")
    r.font.name = "Courier New"
    p.add_run(" in ")
    r = p.add_run("different sizes.")
    r.font.size = Pt(16)

    d.add_paragraph(UNICODE_LINE)
    p = d.add_paragraph("Link: ")
    add_hyperlink(p, "https://www.libreoffice.org", "LibreOffice website")

    d.add_heading("1. Summary", 1)
    p = d.add_paragraph(LOREM * 3)
    p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    d.add_heading("1.1 Key points", 2)
    for item in ["Revenue grew by 12 %", "Two new offices opened", "Customer satisfaction 4.6/5"]:
        d.add_paragraph(item, style="List Bullet")
    d.add_heading("1.2 Next steps", 2)
    for item in ["Review the budget", "Hire two developers", "Release version 1.0"]:
        d.add_paragraph(item, style="List Number")
    quote = d.add_paragraph("“Privacy is not an option, and it shouldn't be the price we accept.”")
    quote.style = "Intense Quote"

    d.add_heading("2. Figures", 1)
    d.add_paragraph("Table with a shaded header row, a merged cell and right-aligned numbers:")
    rows = [
        ("Region", "Q1", "Q2", "Q3", "Q4"),
        ("North", "12'400", "13'100", "15'800", "17'250"),
        ("South", "9'870", "10'020", "11'400", "12'900"),
        ("East", "7'300", "7'950", "8'100", "9'600"),
        ("Total", "29'570", "31'070", "35'300", "39'750"),
    ]
    table = d.add_table(rows=len(rows) + 1, cols=5)
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    title_cell = table.cell(0, 0).merge(table.cell(0, 4))
    title_cell.text = "Sales by region (CHF)"
    title_cell.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER
    title_cell.paragraphs[0].runs[0].bold = True
    shade_cell(title_cell, "1F4E79")
    title_cell.paragraphs[0].runs[0].font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
    for r_i, row in enumerate(rows, start=1):
        for c_i, value in enumerate(row):
            cell = table.cell(r_i, c_i)
            cell.text = value
            para = cell.paragraphs[0]
            if c_i > 0:
                para.alignment = WD_ALIGN_PARAGRAPH.RIGHT
            if r_i in (1, len(rows)):
                para.runs[0].bold = True
                shade_cell(cell, "D9E2F3")

    d.add_paragraph()
    d.add_picture(io.BytesIO(chart_png()), width=Inches(5.5))
    d.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
    caption = d.add_paragraph("Figure 1: Monthly sales")
    caption.alignment = WD_ALIGN_PARAGRAPH.CENTER
    caption.runs[0].italic = True

    d.paragraphs[-1].add_run().add_break(WD_BREAK.PAGE)
    d.add_heading("3. Details", 1)
    for i in range(4):
        d.add_heading(f"3.{i + 1} Topic {i + 1}", 2)
        d.add_paragraph(LOREM * 2)

    two_col = d.add_section(WD_SECTION.CONTINUOUS)
    set_columns(two_col, 2)
    d.add_heading("4. Two-column section", 1)
    d.add_paragraph(LOREM * 6)

    landscape = d.add_section(WD_SECTION.NEW_PAGE)
    set_columns(landscape, 1)
    landscape.orientation = WD_ORIENT.LANDSCAPE
    landscape.page_width, landscape.page_height = landscape.page_height, landscape.page_width
    d.add_heading("5. Landscape page with a wide table", 1)
    wide = d.add_table(rows=6, cols=10)
    wide.style = "Light Grid Accent 1"
    for c in range(10):
        wide.cell(0, c).text = f"Column {c + 1}"
    for r in range(1, 6):
        for c in range(10):
            wide.cell(r, c).text = f"{r * c * 7.5:.1f}"
    d.save(path)


def word_letter(path: Path) -> None:
    d = docx.Document()
    for s in d.sections:
        s.left_margin = s.right_margin = Cm(2.5)
    style = d.styles["Normal"]
    style.font.name = "Arial"
    style.font.size = Pt(11)
    sender = d.add_paragraph("Sample Company Ltd.\nExample Street 1\n8000 Zurich\nSwitzerland")
    sender.runs[0].font.size = Pt(9)
    d.add_paragraph()
    d.add_paragraph("Ms Jane Example\nSample Road 12\n3000 Bern")
    d.add_paragraph()
    d.add_paragraph("Zurich, 18 November 2026").alignment = WD_ALIGN_PARAGRAPH.RIGHT
    subject = d.add_paragraph()
    subject.add_run("Your order no. 2026-117").bold = True
    d.add_paragraph("Dear Ms Example,")
    d.add_paragraph(
        "Thank you for your order. We are pleased to confirm the delivery of the items "
        "listed below. Please check the goods on arrival and let us know within 14 days "
        "if anything is missing or damaged."
    )
    items = d.add_table(rows=4, cols=3)
    items.style = "Light List Accent 1"
    for r, row in enumerate(
        [
            ("Item", "Quantity", "Price"),
            ("Office chair", "2", "CHF 480.00"),
            ("Desk lamp", "3", "CHF 135.00"),
            ("Total", "", "CHF 615.00"),
        ]
    ):
        for c, v in enumerate(row):
            items.cell(r, c).text = v
    d.add_paragraph()
    d.add_paragraph("Kind regards,")
    d.add_paragraph("\n\nMax Sample\nCustomer Service")
    d.save(path)


def word_long_document(path: Path, chapters: int = 20) -> None:
    d = docx.Document()
    page_numbers_in_footer(d.sections[0])
    d.add_heading("Long Test Document", 0)
    d.add_paragraph(f"{chapters} chapters, about 40 pages. Used to test speed and page handling.")
    for ch in range(1, chapters + 1):
        d.add_heading(f"Chapter {ch}", 1)
        for sec in range(1, 4):
            d.add_heading(f"{ch}.{sec} Section", 2)
            for _ in range(3):
                d.add_paragraph(LOREM * 2)
        if ch % 3 == 0:
            d.add_picture(io.BytesIO(chart_png()), width=Inches(4))
        d.paragraphs[-1].add_run().add_break(WD_BREAK.PAGE)
    d.save(path)


# --- Excel and PowerPoint ------------------------------------------------------


def excel_budget(path: Path) -> None:
    from openpyxl import Workbook
    from openpyxl.chart import BarChart, Reference
    from openpyxl.formatting.rule import CellIsRule
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

    wb = Workbook()
    ws = wb.active
    ws.title = "Budget"
    months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun"]
    ws.append(["Category", *months, "Total", "Share"])
    categories = {
        "Rent": [1800] * 6,
        "Groceries": [620, 580, 640, 600, 655, 610],
        "Insurance": [390] * 6,
        "Transport": [120, 95, 140, 110, 160, 130],
        "Leisure": [250, 310, 180, 420, 275, 390],
    }
    for name, values in categories.items():
        ws.append([name, *values])
    last = ws.max_row
    for r in range(2, last + 1):
        ws.cell(r, 8, f"=SUM(B{r}:G{r})")
        ws.cell(r, 9, f"=H{r}/H${last + 1}")
    ws.append(["Total", *[f"=SUM({c}2:{c}{last})" for c in "BCDEFGH"]])

    header_fill = PatternFill("solid", fgColor="1F4E79")
    thin = Side(style="thin", color="999999")
    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center")
    for row in ws.iter_rows(min_row=2, max_row=ws.max_row, min_col=2, max_col=8):
        for cell in row:
            cell.number_format = '"CHF" #,##0.00'
            cell.border = Border(top=thin, bottom=thin, left=thin, right=thin)
    for r in range(2, last + 1):
        ws.cell(r, 9).number_format = "0.0%"
    for cell in ws[ws.max_row]:
        cell.font = Font(bold=True)
    ws.column_dimensions["A"].width = 16
    for col in "BCDEFGHI":
        ws.column_dimensions[col].width = 13
    ws.freeze_panes = "B2"
    ws.conditional_formatting.add(
        f"B2:G{last}",
        CellIsRule(
            operator="greaterThan", formula=["400"], fill=PatternFill("solid", fgColor="F8CBAD")
        ),
    )
    chart = BarChart()
    chart.title = "Spending per month"
    chart.add_data(
        Reference(ws, min_col=2, max_col=7, min_row=1, max_row=last), titles_from_data=True
    )
    chart.set_categories(Reference(ws, min_col=1, min_row=2, max_row=last))
    chart.width, chart.height = 18, 9
    ws.add_chart(chart, "B10")

    people = wb.create_sheet("Employees")
    people.append(["Name", "Department", "Start date", "Salary", "Part-time"])
    import datetime as dt

    rows = [
        ("Anna Müller", "Finance", dt.date(2019, 3, 1), 98000, False),
        ("Luca Rossi", "IT", dt.date(2021, 9, 15), 105000, False),
        ("Chloé Dubois", "Marketing", dt.date(2023, 1, 9), 82000, True),
        ("Jörg Schäfer", "IT", dt.date(2018, 6, 1), 112000, False),
        ("Sofia García", "Sales", dt.date(2024, 4, 22), 76000, True),
    ]
    for row in rows:
        people.append(row)
    for r in range(2, len(rows) + 2):
        people.cell(r, 3).number_format = "DD.MM.YYYY"
        people.cell(r, 4).number_format = "#,##0"
    for cell in people[1]:
        cell.font = Font(bold=True)
    for col, w in zip("ABCDE", (18, 14, 12, 12, 10), strict=True):
        people.column_dimensions[col].width = w

    notes = wb.create_sheet("Notes")
    notes["A1"] = "This workbook has 3 sheets, formulas, number formats, a chart,"
    notes["A2"] = "conditional formatting (values over 400 are red) and frozen panes."
    notes["A3"] = UNICODE_LINE
    wb.save(path)


def powerpoint_presentation(path: Path, image: Path) -> None:
    from pptx import Presentation
    from pptx.dml.color import RGBColor as PptColor
    from pptx.enum.shapes import MSO_SHAPE
    from pptx.util import Inches as PInches
    from pptx.util import Pt as PPt

    prs = Presentation()
    prs.slide_width, prs.slide_height = PInches(13.333), PInches(7.5)  # 16:9

    s = prs.slides.add_slide(prs.slide_layouts[0])
    s.shapes.title.text = "File-Converter Test Presentation"
    s.placeholders[1].text = "Five slides with text, bullets, an image, a table and shapes"

    s = prs.slides.add_slide(prs.slide_layouts[1])
    s.shapes.title.text = "Agenda"
    body = s.placeholders[1].text_frame
    body.text = "Why local conversion matters"
    for text, level in [
        ("No uploads", 1),
        ("No tracking", 1),
        ("Supported formats", 0),
        ("Roadmap", 0),
        (UNICODE_LINE, 0),
    ]:
        para = body.add_paragraph()
        para.text = text
        para.level = level

    s = prs.slides.add_slide(prs.slide_layouts[5])
    s.shapes.title.text = "A picture"
    s.shapes.add_picture(str(image), PInches(2.5), PInches(1.6), height=PInches(5.2))

    s = prs.slides.add_slide(prs.slide_layouts[5])
    s.shapes.title.text = "A table"
    rows, cols = 4, 4
    tbl = s.shapes.add_table(rows, cols, PInches(1.5), PInches(2), PInches(10), PInches(3)).table
    data = [
        ("Format", "Pages", "Size", "Status"),
        ("DOCX", "12", "84 KB", "OK"),
        ("PDF", "12", "310 KB", "OK"),
        ("PPTX", "5", "1.2 MB", "Check"),
    ]
    for r in range(rows):
        for c in range(cols):
            tbl.cell(r, c).text = data[r][c]

    s = prs.slides.add_slide(prs.slide_layouts[6])
    colors = [(0x2A, 0x78, 0xD6), (0x1F, 0xA3, 0x7A), (0xE8, 0xA3, 0x3B), (0xD6, 0x45, 0x5D)]
    shapes = [
        MSO_SHAPE.ROUNDED_RECTANGLE,
        MSO_SHAPE.OVAL,
        MSO_SHAPE.RIGHT_ARROW,
        MSO_SHAPE.STAR_5_POINT,
    ]
    for i, (shape, rgb) in enumerate(zip(shapes, colors, strict=True)):
        sh = s.shapes.add_shape(
            shape, PInches(0.8 + i * 3.1), PInches(2.5), PInches(2.6), PInches(2.2)
        )
        sh.fill.solid()
        sh.fill.fore_color.rgb = PptColor(*rgb)
        sh.text_frame.text = f"Shape {i + 1}"
        sh.text_frame.paragraphs[0].runs[0].font.size = PPt(20)
    prs.save(path)


# --- PDF -----------------------------------------------------------------------

INVOICE_HTML = """
<h1 style="color:#1f4e79">INVOICE</h1>
<p><b>Sample Company Ltd.</b><br>Example Street 1, 8000 Zurich</p>
<p>Invoice no. <b>2026-117</b> &middot; Date: 18.11.2026 &middot; Due: 18.12.2026</p>
<p>Bill to: Jane Example, Sample Road 12, 3000 Bern</p>
<table border="1" cellpadding="4" style="border-collapse:collapse; width:100%">
<tr style="background:#d9e2f3"><th>Pos.</th><th>Description</th><th>Qty</th><th>Unit price</th><th>Amount</th></tr>
<tr><td>1</td><td>Office chair, black</td><td>2</td><td>CHF 240.00</td><td>CHF 480.00</td></tr>
<tr><td>2</td><td>Desk lamp LED</td><td>3</td><td>CHF 45.00</td><td>CHF 135.00</td></tr>
<tr><td>3</td><td>Delivery</td><td>1</td><td>CHF 25.00</td><td>CHF 25.00</td></tr>
<tr><td colspan="4"><b>Subtotal</b></td><td>CHF 640.00</td></tr>
<tr><td colspan="4">VAT 8.1 %</td><td>CHF 51.85</td></tr>
<tr><td colspan="4"><b>Total</b></td><td><b>CHF 691.85</b></td></tr>
</table>
<p>Please pay within 30 days. Thank you for your business!</p>
<p style="font-size:9px; color:#666">Bank: Example Bank, IBAN CH00 0000 0000 0000 0000 0 (sample, not real)</p>
"""


def pdf_invoice(path: Path) -> None:
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    css = "th, td {border: 1px solid #8899aa; padding: 4px;} body {font-family: sans-serif;}"
    page.insert_htmlbox(pymupdf.Rect(50, 50, 545, 800), INVOICE_HTML, css=css)
    page.draw_line((50, 790), (545, 790), color=(0.6, 0.6, 0.6))
    doc.save(path, garbage=3, deflate=True)
    doc.close()


def pdf_multipage(path: Path, pages: int = 12) -> None:
    doc = pymupdf.open()
    colors = ["#2a78d6", "#1fa37a", "#e8a33b", "#d6455d"]
    for i in range(1, pages + 1):
        page = doc.new_page(width=595, height=842)
        html = (
            f'<h1 style="color:{colors[i % 4]}; font-size:48px">Page {i}</h1>'
            f"<p>This is page {i} of {pages}. Use this file to test splitting, "
            f"merging and PDF to image conversion.</p><p>{LOREM * 3}</p>"
        )
        page.insert_htmlbox(pymupdf.Rect(50, 50, 545, 800), html)
    doc.save(path, garbage=3, deflate=True)
    doc.close()


def pdf_scanned(path: Path, from_pdf: Path) -> None:
    """Pictures of pages without selectable text, like a scanner produces."""
    src = pymupdf.open(from_pdf)
    out = pymupdf.open()
    for page in src:
        pix = page.get_pixmap(dpi=110, colorspace=pymupdf.csGRAY)
        img = Image.frombytes("L", (pix.width, pix.height), pix.samples).rotate(
            0.7, fillcolor=255, expand=False
        )
        for _ in range(6000):  # scanner dust
            img.putpixel((random.randrange(img.width), random.randrange(img.height)), 170)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=70)
        new = out.new_page(width=page.rect.width, height=page.rect.height)
        new.insert_image(new.rect, stream=buf.getvalue())
    out.save(path, garbage=3, deflate=True)
    out.close()
    src.close()


def pdf_with_password(path: Path, from_pdf: Path) -> None:
    with pymupdf.open(from_pdf) as doc:
        doc.save(
            path, encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="test123", owner_pw="test123"
        )


# --- images --------------------------------------------------------------------


def photo_with_gps(path: Path, photo: Image.Image) -> None:
    """Stored sideways with EXIF orientation 6, like many phone photos, plus GPS data."""
    stored = photo.rotate(90, expand=True)  # viewers rotate it back using the EXIF tag
    exif = Image.Exif()
    exif[0x010F] = "SamplePhone Inc."  # Make
    exif[0x0110] = "SamplePhone 15"  # Model
    exif[0x0132] = "2026:08:14 17:32:05"  # DateTime
    exif[0x0112] = 6  # Orientation: rotate 90° clockwise to display
    gps = exif.get_ifd(0x8825)
    gps[1], gps[2] = "N", (46.0, 33.0, 12.5)  # a made-up spot in the Swiss Alps
    gps[3], gps[4] = "E", (7.0, 58.0, 44.1)
    stored.save(path, quality=88, exif=exif)


def transparent_logo(path: Path) -> None:
    img = Image.new("RGBA", (512, 512), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((16, 16, 496, 496), fill=(31, 78, 121, 255))
    d.ellipse((96, 96, 416, 416), fill=(0, 0, 0, 0))
    d.rectangle((150, 230, 362, 282), fill=(232, 163, 59, 255))
    d.polygon([(330, 190), (400, 256), (330, 322)], fill=(232, 163, 59, 255))
    img.save(path)


def animated_gif(path: Path) -> None:
    frames = []
    for i in range(12):
        f = Image.new("RGB", (240, 160), "white")
        d = ImageDraw.Draw(f)
        x = 20 + i * 16
        y = 80 - int(abs(math.sin(i / 11 * math.pi)) * 55)
        d.ellipse((x, y, x + 40, y + 40), fill=(214, 69, 93))
        d.line((0, 125, 240, 125), fill="black", width=2)
        frames.append(f)
    frames[0].save(path, save_all=True, append_images=frames[1:], duration=80, loop=0)


def multipage_tiff(path: Path, photo: Image.Image) -> None:
    pages = [photo.resize((800, 533)), Image.open(io.BytesIO(chart_png())).convert("RGB")]
    pages[0].save(path, save_all=True, append_images=pages[1:], compression="tiff_lzw")


# --- main ----------------------------------------------------------------------


def main() -> None:
    dirs = {name: ROOT / name for name in ("word", "pdf", "excel", "powerpoint", "images", "other")}
    for d in dirs.values():
        if d.exists():
            shutil.rmtree(d)
        d.mkdir()

    photo = landscape_photo()
    print("Images …")
    photo_with_gps(dirs["images"] / "photo_with_gps_rotated.jpg", photo)
    photo.save(dirs["images"] / "photo.png", optimize=True)
    photo.save(dirs["images"] / "photo.webp", quality=85)
    photo.resize((800, 533)).save(dirs["images"] / "photo.bmp")
    transparent_logo(dirs["images"] / "logo_transparent.png")
    animated_gif(dirs["images"] / "animated.gif")
    multipage_tiff(dirs["images"] / "two_pages.tiff", photo)
    try:
        import pillow_heif

        pillow_heif.register_heif_opener()
        photo.save(dirs["images"] / "iphone_photo.heic", quality=80)
    except ImportError:
        print("  (pillow-heif missing, no HEIC sample)")

    print("Word …")
    word_formatted_report(dirs["word"] / "formatted_report.docx")
    word_letter(dirs["word"] / "business_letter.docx")
    word_long_document(dirs["word"] / "long_document_40_pages.docx")

    print("Excel, PowerPoint …")
    excel_budget(dirs["excel"] / "budget_with_formulas_and_chart.xlsx")
    (dirs["excel"] / "contacts.csv").write_text(
        "Name,Email,City,Phone\n"
        "Anna Müller,anna@example.com,Zürich,+41 44 000 00 01\n"
        "Luca Rossi,luca@example.com,Lugano,+41 91 000 00 02\n"
        'Chloé Dubois,chloe@example.com,Genève,"+41 22 000 00 03"\n'
        '"Smith, John",john@example.com,"Basel, BS",+41 61 000 00 04\n',
        encoding="utf-8",
    )
    powerpoint_presentation(dirs["powerpoint"] / "presentation.pptx", dirs["images"] / "photo.png")

    print("PDF …")
    pdf_invoice(dirs["pdf"] / "invoice.pdf")
    pdf_multipage(dirs["pdf"] / "twelve_pages.pdf")
    pdf_with_password(dirs["pdf"] / "password_protected_test123.pdf", dirs["pdf"] / "invoice.pdf")

    print("Other …")
    (dirs["other"] / "notes_unicode.txt").write_text(
        "Plain text file\n===============\n\n" + LOREM + "\n\n" + UNICODE_LINE + "\n"
        "Emoji: 📄 ➜ 📕  (may not survive every conversion)\n",
        encoding="utf-8",
    )
    (dirs["other"] / "broken_not_really.pdf").write_bytes(
        b"%PDF-1.7\nThis file only pretends to be a PDF. Converters must fail politely.\n"
    )
    shutil.copyfile(
        dirs["images"] / "logo_transparent.png", dirs["other"] / "png_with_wrong_extension.txt"
    )

    if find_soffice() is None:
        print("LibreOffice not found: skipping ODT/RTF/DOC/XLS/ODS/ODP/PPT copies and Word→PDF.")
    else:
        print("Copies in other office formats (LibreOffice) …")
        engine = Engine()
        jobs = [
            (dirs["word"] / "formatted_report.docx", ["odt", "rtf", "doc"]),
            (dirs["excel"] / "budget_with_formulas_and_chart.xlsx", ["ods", "xls"]),
            (dirs["powerpoint"] / "presentation.pptx", ["odp", "ppt"]),
        ]
        for src, targets in jobs:
            for target in targets:
                engine.convert(src, target, src.parent, overwrite=True)
        engine.convert(dirs["word"] / "formatted_report.docx", "pdf", dirs["pdf"], overwrite=True)
        (dirs["pdf"] / "formatted_report.pdf").rename(dirs["pdf"] / "report_made_from_word.pdf")
        engine.convert(dirs["word"] / "business_letter.docx", "pdf", dirs["pdf"], overwrite=True)
        pdf_scanned(dirs["pdf"] / "scanned_letter_no_text.pdf", dirs["pdf"] / "business_letter.pdf")
        (dirs["pdf"] / "business_letter.pdf").rename(dirs["pdf"] / "letter_made_from_word.pdf")

    total = sum(f.stat().st_size for f in ROOT.rglob("*") if f.is_file())
    print(f"Done. {total / 1e6:.1f} MB in {ROOT}")


if __name__ == "__main__":
    main()
