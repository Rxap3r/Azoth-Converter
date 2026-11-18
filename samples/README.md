# Sample files for testing

Made-up files for trying out File-Converter by hand, and for the automated tests.
Every name, address and number in them is fictional.

To recreate them (needs `pip install -e ".[dev]"`, plus LibreOffice for the
ODT/RTF/DOC/XLS/ODS/ODP/PPT copies and the PDFs made from Word):

```bash
python samples/generate.py
```

## What's here and what to check

### `word/`
| File | Contents | Check after converting |
|------|----------|------------------------|
| `formatted_report.docx` | Title and headings; bold, italic, underline, colour, highlight, strikethrough, sub/superscript, different fonts and sizes; umlauts and special characters; a hyperlink; bullet and numbered lists; a quote; a table with a merged, shaded header; a chart image with caption; page break; header and footer with "Page X of Y"; a two-column section; a landscape page with a wide table | → PDF: does it look the same as in Word? Page numbers right? Landscape page landscape? |
| `formatted_report.odt` / `.rtf` / `.doc` | The same report in other formats | → PDF or → DOCX |
| `business_letter.docx` | A typical letter in Arial with a small table | → PDF |
| `long_document_40_pages.docx` | About 40 pages with headings and charts | Speed, page count |

### `pdf/`
| File | Contents | Check |
|------|----------|-------|
| `report_made_from_word.pdf` | The formatted report as PDF | → Word: text, tables and chart image should be editable |
| `letter_made_from_word.pdf` | The letter as PDF | → Word |
| `invoice.pdf` | Invoice with a table (not made from Word) | → Word, → JPG |
| `twelve_pages.pdf` | 12 numbered pages | → PNG gives 12 files; split/merge (`fileconv pdf split`) |
| `scanned_letter_no_text.pdf` | A "scan": pictures of pages, no selectable text | → Word should show a clear "this looks like a scan" message |
| `password_protected_test123.pdf` | Password `test123` | Should show a clear "password-protected" message |

### `excel/`
| File | Contents | Check |
|------|----------|-------|
| `budget_with_formulas_and_chart.xlsx` | 3 sheets, formulas, CHF/percent/date formats, colours, conditional formatting, frozen panes, a chart (also as `.ods` and `.xls`) | → PDF: are formulas calculated, chart present? → ODS/XLS and back |
| `contacts.csv` | UTF-8 with umlauts, commas inside quotes | → XLSX: umlauts and "Smith, John" in one cell |

### `powerpoint/`
| File | Contents | Check |
|------|----------|-------|
| `presentation.pptx` | 16:9 slides with title, bullets, a photo, a table and coloured shapes (also as `.odp` and `.ppt`) | → PDF, → PNG (one image per slide) |

### `images/`
| File | Contents | Check |
|------|----------|-------|
| `photo_with_gps_rotated.jpg` | Phone-style photo stored sideways with an EXIF "rotate" flag, camera model, date and **GPS location** | → PNG/WebP: picture upright, GPS and camera data **gone** (unless "Keep photo metadata" is on) |
| `iphone_photo.heic` | HEIC like an iPhone photo | → JPG |
| `logo_transparent.png` | Transparent background | → JPG: background turns white; → WebP/ICO keep transparency |
| `animated.gif` | 12-frame animation | → WebP stays animated |
| `two_pages.tiff` | Multi-page TIFF | → PDF |
| `photo.png`, `photo.webp`, `photo.bmp` | Same photo in other formats | Any image format |

### `other/`
| File | Contents | Check |
|------|----------|-------|
| `notes_unicode.txt` | Plain text with special characters and emoji | → PDF, → DOCX |
| `png_with_wrong_extension.txt` | Actually a PNG image named `.txt` | Should be recognised as PNG (detection by content) |
| `broken_not_really.pdf` | Pretends to be a PDF | Should fail with a friendly message, not crash |
