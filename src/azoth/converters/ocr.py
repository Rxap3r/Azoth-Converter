"""Scans and photos → text or Word, by text recognition (OCR, see ``azoth.ocr``).

Also used by the PDF converters: a scanned PDF turned into Word or text is recognised
first, because it has no text of its own.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

import pymupdf

from .base import ConversionContext, ConversionError, Converter
from .images import READABLE

TEXT_ONLY = "Only the text is kept; pictures and layout are dropped."


def language(ctx: ConversionContext) -> str:
    from .. import ocr

    return str(ctx.option("ocr_language", ocr.default_language()))


def recognise(doc: pymupdf.Document, ctx: ConversionContext) -> list[list[str]]:
    """Paragraphs of every page; scanned pages are read by OCR."""
    from .. import ocr

    return ocr.page_texts(
        doc, language(ctx), progress=lambda f, m: ctx.progress(f * 0.9, m), cancel=ctx.cancel_event
    )


def write_text(pages: list[list[str]], dst: Path) -> None:
    """Pages separated by a form feed (like PDF → text), paragraphs by a blank line."""
    dst.write_text("\f".join("\n\n".join(p) + "\n" for p in pages), encoding="utf-8")


def write_docx(pages: list[list[str]], dst: Path) -> None:
    """A plain Word document: one paragraph per text block, a page break between pages."""
    import docx
    from docx.enum.text import WD_BREAK

    document = docx.Document()
    for i, paragraphs in enumerate(pages):
        if i:
            document.add_paragraph().add_run().add_break(WD_BREAK.PAGE)
        for text in paragraphs:
            document.add_paragraph(text)
    try:
        document.save(str(dst))
    except OSError as exc:
        raise ConversionError(f"Could not save {dst.name}: {exc.strerror or exc}") from exc


def check_found(pages: list[list[str]]) -> None:
    if not any(pages):
        raise ConversionError(
            "No text was found. If the picture is sideways or upside down, turn it "
            "the right way up first; very blurry or tiny print can't be read."
        )


class OcrConverter(Converter):
    """Photo or scan (JPG, PNG, TIFF …) → text or Word."""

    id = "ocr"
    label = "Tesseract (OCR)"
    priority = 10

    def is_available(self) -> bool:
        from .. import ocr

        return ocr.is_available()

    def unavailable_reason(self) -> str:
        return (
            "Text recognition (OCR) is missing its language files, so scans and photos "
            "can't be turned into text. Reinstall Azoth Converter to fix this."
        )

    def capabilities(self) -> Iterable[tuple[str, str]]:
        for src in READABLE:
            yield src, "txt"
            yield src, "docx"

    def final_only(self, src: str, dst: str) -> bool:
        return True

    def first_only(self, src: str, dst: str) -> bool:
        return True

    def quality_note(self, src: str, dst: str) -> str | None:
        from .. import ocr

        return f"{ocr.QUALITY_NOTE} {TEXT_ONLY}"

    def convert(self, src: Path, dst: Path, ctx: ConversionContext) -> list[Path]:
        from .image_pdf import ImageToPdfConverter

        # The picture as PDF pages (upright, one page per TIFF page) in the job folder.
        pdf = ctx.work_dir / "ocr-pages.pdf"
        ImageToPdfConverter().convert(src, pdf, ConversionContext(ctx.work_dir))
        with pymupdf.open(pdf) as doc:
            pages = recognise(doc, ctx)
        check_found(pages)
        ctx.check_cancelled()
        if dst.suffix.lower() == ".txt":
            write_text(pages, dst)
        else:
            write_docx(pages, dst)
        return [dst]
