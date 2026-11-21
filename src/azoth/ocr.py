"""Text recognition (OCR): read the text in scans and photos, fully offline.

Uses the Tesseract engine built into PyMuPDF with the language files in
``resources/tessdata`` (fetched by ``packaging/fetch_tessdata.py`` and shipped with the app).

A searchable PDF keeps every page exactly as it is: the recognised text is laid on top as
an invisible layer (like the text layer of a scanner's "searchable PDF"), so pictures are
never re-drawn or re-compressed. Pages that already have text are left alone.
"""

from __future__ import annotations

import locale
import re
import threading
from collections.abc import Callable
from pathlib import Path

import pymupdf

from . import quality
from .converters import ConversionCancelled, ConversionError
from .converters.pdf import open_pdf

Progress = Callable[[float, str], None]

TESSDATA = Path(__file__).resolve().parent / "resources" / "tessdata"

# Tesseract code → name shown in the app. Order: as offered in the app.
LANGUAGES = {
    "eng": "English",
    "deu": "German (Deutsch)",
    "fra": "French (Français)",
    "ita": "Italian (Italiano)",
}
_BY_LOCALE = {"en": "eng", "de": "deu", "fr": "fra", "it": "ita"}
_BY_WINDOWS_NAME = {"english": "eng", "german": "deu", "french": "fra", "italian": "ita"}

MIN_TEXT_CHARS = 20
"""A page with fewer characters of real text than this (and with pictures) is a scan."""

_TEXT_OBJECT = re.compile(rb"BT\b.*\bET\b", re.S)

QUALITY_NOTE = (
    "The text is read from the picture (OCR). Check names and numbers: unclear print "
    "or handwriting can be misread."
)


def available_languages() -> list[str]:
    """Language codes whose files are installed, in the order of ``LANGUAGES``."""
    return [code for code in LANGUAGES if (TESSDATA / f"{code}.traineddata").is_file()]


def is_available() -> bool:
    return bool(available_languages())


def default_language(locale_name: str | None = None) -> str:
    """The OCR language matching the computer's language (e.g. "de_CH" → "deu"),
    or English."""
    if locale_name is None:
        try:
            locale_name = locale.getlocale()[0] or ""
        except ValueError:  # pragma: no cover - odd locale settings
            locale_name = ""
    name = locale_name.lower()
    if len(name) == 2 or name[2:3] in ("_", "-", "."):  # "de", "de_CH", "fr-FR"
        code = _BY_LOCALE.get(name[:2])
    else:  # Windows names such as "German_Switzerland"
        code = _BY_WINDOWS_NAME.get(name.split("_")[0])
    available = available_languages()
    if code in available:
        return code
    return "eng" if "eng" in available or not available else available[0]


def check_language(language: str) -> str:
    """Raise a readable error unless ``language`` can be used; returns it."""
    if not is_available():
        raise ConversionError(
            "Text recognition (OCR) isn't installed with this copy of Azoth Converter."
        )
    if language not in available_languages():
        raise ConversionError(f"Text recognition doesn't know the language “{language}”.")
    return language


def page_needs_ocr(page: pymupdf.Page) -> bool:
    """True for a page that shows pictures but has (almost) no selectable text."""
    return len(page.get_text("text").strip()) < MIN_TEXT_CHARS and bool(page.get_images())


def needs_ocr(src: Path) -> bool:
    """True if any page of the PDF is a scan without text."""
    with open_pdf(src) as doc:
        return any(page_needs_ocr(page) for page in doc)


def _text_layer(page: pymupdf.Page, language: str, dpi: int) -> pymupdf.Document:
    """A one-page PDF the size of ``page`` holding only the recognised text (invisible)."""
    pix = page.get_pixmap(dpi=dpi, alpha=False, annots=False)
    if pix.n != 3:  # pragma: no cover - alpha=False gives RGB, keep it that way
        pix = pymupdf.Pixmap(pymupdf.csRGB, pix)
    try:
        data = pix.pdfocr_tobytes(language=language, tessdata=str(TESSDATA))
    except Exception as exc:
        raise ConversionError(f"Text recognition failed: {exc}") from exc
    layer = pymupdf.open("pdf", data)
    lpage = layer[0]
    # MuPDF's OCR page = the rendered picture + invisible text. Keep only the text.
    for xref in lpage.get_contents():
        found = _TEXT_OBJECT.search(layer.xref_stream(xref))
        layer.update_stream(xref, found.group(0) if found else b"")
    layer.xref_set_key(lpage.xref, "Resources/XObject", "<<>>")
    return layer


def _run_pages(
    doc: pymupdf.Document,
    language: str,
    each: Callable[[pymupdf.Page, pymupdf.Document], None],
    progress: Progress | None,
    cancel: threading.Event | None,
    only_scans: bool,
) -> int:
    check_language(language)
    report = progress or (lambda f, m: None)
    total = doc.page_count
    done = 0
    for i, page in enumerate(doc):
        if cancel is not None and cancel.is_set():
            raise ConversionCancelled()
        if only_scans and not page_needs_ocr(page):
            continue
        report(i / max(total, 1), f"Reading text on page {i + 1}/{total}")
        with _text_layer(page, language, quality.OCR_DPI) as layer:
            each(page, layer)
        done += 1
    return done


def add_text_layer(
    doc: pymupdf.Document,
    language: str,
    *,
    progress: Progress | None = None,
    cancel: threading.Event | None = None,
) -> int:
    """Add invisible recognised text to every scanned page of ``doc`` (in memory).
    Returns how many pages were recognised."""

    def overlay(page: pymupdf.Page, layer: pymupdf.Document) -> None:
        # show_pdf_page fits the layer to the visible page and takes care of rotation.
        page.show_pdf_page(page.rect, layer, 0, overlay=True)

    return _run_pages(doc, language, overlay, progress, cancel, only_scans=True)


def page_texts(
    doc: pymupdf.Document,
    language: str,
    *,
    progress: Progress | None = None,
    cancel: threading.Event | None = None,
) -> list[list[str]]:
    """The text of every page as paragraphs. Scanned pages are recognised, the others
    keep their real text."""
    result: list[list[str]] = [[] for _ in range(doc.page_count)]
    scanned: dict[int, list[str]] = {}

    def collect(page: pymupdf.Page, layer: pymupdf.Document) -> None:
        scanned[page.number] = _paragraphs(layer[0])

    if any(page_needs_ocr(page) for page in doc):
        _run_pages(doc, language, collect, progress, cancel, only_scans=True)
    for page in doc:
        result[page.number] = scanned.get(page.number) or _paragraphs(page)
    return result


def _paragraphs(page: pymupdf.Page) -> list[str]:
    """Text blocks of a page, top to bottom, each block's lines joined into one paragraph."""
    paragraphs = []
    for block in page.get_text("blocks", sort=True):
        if block[6] != 0:  # 1 = picture block
            continue
        text = " ".join(line.strip() for line in block[4].splitlines() if line.strip())
        if text:
            paragraphs.append(text)
    return paragraphs


def searchable_path(src: Path, output_dir: Path | None = None) -> Path:
    return (output_dir or src.parent) / f"{src.stem} (searchable).pdf"


def make_searchable(
    src: Path,
    dst: Path,
    language: str,
    *,
    overwrite: bool = False,
    progress: Progress | None = None,
    cancel: threading.Event | None = None,
) -> Path:
    """Save a copy of the PDF ``src`` whose scanned pages have selectable, searchable text.
    The pages themselves stay exactly as they are."""
    from .pdf_tools import _same_pages, _save, _target

    src = Path(src)
    check_language(language)
    with open_pdf(src) as doc:
        if not any(page_needs_ocr(page) for page in doc):
            raise ConversionError(
                "This PDF already has selectable text, so there is nothing to recognise."
            )
        add_text_layer(doc, language, progress=progress, cancel=cancel)
        if progress:
            progress(0.97, "Saving")
        return _save(
            doc,
            _target(Path(dst), overwrite, [src]),
            check=_same_pages(doc.page_count),
            encryption=pymupdf.PDF_ENCRYPT_KEEP,
        )
