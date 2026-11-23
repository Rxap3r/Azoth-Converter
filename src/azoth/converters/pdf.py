"""PDF conversions: PDF to images, text and Word, plus merge and split helpers.

Uses PyMuPDF for rendering and text, and pdf2docx to rebuild an editable Word
document from the PDF layout.
"""

from __future__ import annotations

import logging
import warnings
from collections.abc import Iterable
from pathlib import Path

import pymupdf
from PIL import Image

from .base import ConversionContext, ConversionError, Converter

DEFAULT_DPI = 300  # print quality: text and lines stay sharp when zooming in
RASTER_TARGETS = {"png": "PNG", "jpg": "JPEG", "webp": "WEBP", "bmp": "BMP", "tiff": "TIFF"}


def open_pdf(src: Path) -> pymupdf.Document:
    try:
        doc = pymupdf.open(src, filetype="pdf")
    except Exception as exc:
        raise ConversionError(
            "Could not open the PDF. The file is damaged or isn't a real PDF."
        ) from exc
    if doc.needs_pass:
        doc.close()
        raise ConversionError(
            "This PDF is password-protected. Remove the password first (Password page)."
        )
    return doc


def page_file_name(dst: Path, index: int, total: int) -> Path:
    """``report.png`` → ``report_page001.png`` when there are several pages."""
    if total == 1:
        return dst
    width = max(3, len(str(total)))
    return dst.with_name(f"{dst.stem}_page{index + 1:0{width}d}{dst.suffix}")


def is_probably_scanned(src: Path, sample_pages: int = 5) -> bool:
    """True if the first pages contain images but (almost) no selectable text."""
    with open_pdf(src) as doc:
        pages = [doc[i] for i in range(min(sample_pages, doc.page_count))]
        text = sum(len(p.get_text("text").strip()) for p in pages)
        images = sum(len(p.get_images()) for p in pages)
    return text < 20 and images > 0


def is_searchable_scan(src: Path, sample_pages: int = 5) -> bool:
    """True for a scan with an invisible text layer (made by text recognition): the pages
    are pictures and all their text is hidden. pdf2docx can't see hidden text."""
    with open_pdf(src) as doc:
        pages = [doc[i] for i in range(min(sample_pages, doc.page_count))]
        spans = [span for p in pages for span in p.get_texttrace()]
        images = sum(len(p.get_images()) for p in pages)
    return bool(spans) and images > 0 and all(span["type"] == 3 for span in spans)


class PdfToImageConverter(Converter):
    id = "pdf-images"
    label = "PyMuPDF"
    priority = 10

    def capabilities(self) -> Iterable[tuple[str, str]]:
        for dst in RASTER_TARGETS:
            yield "pdf", dst

    def final_only(self, src: str, dst: str) -> bool:
        # One image per page (TIFF: several pages in one file), so never use
        # this as an in-between step, e.g. PDF → TIFF → GIF.
        return True

    def convert(self, src: Path, dst: Path, ctx: ConversionContext) -> list[Path]:
        dst_id = dst.suffix.lower().lstrip(".")
        dst_id = {"jpeg": "jpg", "tif": "tiff"}.get(dst_id, dst_id)
        dpi = int(ctx.option("dpi", DEFAULT_DPI))
        quality = int(ctx.option("quality", 95))
        outputs: list[Path] = []
        with open_pdf(src) as doc:
            total = doc.page_count
            if total == 0:
                raise ConversionError("The PDF has no pages")
            images: list[Image.Image] = []
            for i, page in enumerate(doc):
                ctx.check_cancelled()
                ctx.progress(i / total, f"Page {i + 1}/{total}")
                pix = page.get_pixmap(dpi=dpi, alpha=False)
                img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
                if dst_id == "tiff":
                    images.append(img)
                    continue
                out = page_file_name(dst, i, total)
                kwargs = {}
                if dst_id == "jpg":
                    kwargs = {"quality": quality, "subsampling": 0}
                elif dst_id == "webp":
                    kwargs = {"lossless": True}  # rendered pages: crisp text, no artefacts
                img.save(out, format=RASTER_TARGETS[dst_id], dpi=(dpi, dpi), **kwargs)
                outputs.append(out)
            if dst_id == "tiff":
                images[0].save(
                    dst,
                    format="TIFF",
                    compression="tiff_lzw",
                    dpi=(dpi, dpi),
                    save_all=True,
                    append_images=images[1:],
                )
                outputs.append(dst)
        return outputs


class PdfToTextConverter(Converter):
    id = "pdf-text"
    label = "PyMuPDF"
    priority = 10

    def final_only(self, src: str, dst: str) -> bool:
        return True  # plain text loses all formatting; never convert it further

    def first_only(self, src: str, dst: str) -> bool:
        return True  # no Excel → PDF → Word chains

    def capabilities(self) -> Iterable[tuple[str, str]]:
        yield "pdf", "txt"

    def quality_note(self, src: str, dst: str) -> str | None:
        return "Only the text is kept; images and layout are dropped."

    def convert(self, src: Path, dst: Path, ctx: ConversionContext) -> list[Path]:
        from .. import ocr

        if ocr.is_available() and ocr.needs_ocr(src):
            from .ocr import check_found, recognise, write_text

            with open_pdf(src) as doc:
                pages = recognise(doc, ctx)  # scanned pages are read, the others kept
            check_found(pages)
            write_text(pages, dst)
            return [dst]
        parts: list[str] = []
        with open_pdf(src) as doc:
            total = doc.page_count
            for i, page in enumerate(doc):
                ctx.check_cancelled()
                ctx.progress(i / max(total, 1), f"Page {i + 1}/{total}")
                parts.append(page.get_text("text", sort=True))
        dst.write_text("\f".join(parts), encoding="utf-8")
        return [dst]


class PdfToWordConverter(Converter):
    id = "pdf-docx"
    label = "pdf2docx"
    priority = 20

    def first_only(self, src: str, dst: str) -> bool:
        return True  # no Excel → PDF → Word chains

    def capabilities(self) -> Iterable[tuple[str, str]]:
        yield "pdf", "docx"

    def quality_note(self, src: str, dst: str) -> str | None:
        return (
            "The Word layout is rebuilt from the PDF. Simple documents convert well; "
            "complex layouts may need touching up."
        )

    def convert(self, src: Path, dst: Path, ctx: ConversionContext) -> list[Path]:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", FutureWarning)  # pdf2docx imports old "fitz" name
            from pdf2docx import Converter as Pdf2Docx

        # A scan has no text for pdf2docx to work with (it would give an empty
        # document), so its text is recognised (OCR) instead. A searchable scan already
        # has its text, but hidden, which pdf2docx ignores: that text is used.
        if is_probably_scanned(src) or is_searchable_scan(src):
            from .. import ocr
            from .ocr import check_found, recognise, write_docx

            if not ocr.is_available() and is_probably_scanned(src):
                raise ConversionError(
                    "This PDF looks like a scan (pictures of pages, no selectable text). "
                    "Converting it to Word needs text recognition (OCR), which isn't "
                    "installed with this copy of Azoth Converter."
                )
            with open_pdf(src) as doc:
                pages = recognise(doc, ctx)
            check_found(pages)
            write_docx(pages, dst)
            return [dst]
        with open_pdf(src) as doc:
            total = doc.page_count

        logging.disable(logging.WARNING)  # pdf2docx logs chatty INFO lines
        try:
            _rebuild_docx(Pdf2Docx, src, dst, total, ctx)
        finally:
            logging.disable(logging.NOTSET)
        return [dst]


def _rebuild_docx(pdf2docx_class, src: Path, dst: Path, total: int, ctx: ConversionContext):
    """Run pdf2docx's four steps one page at a time, so a large PDF shows progress
    and can be cancelled between pages. Same steps and settings as
    ``pdf2docx.Converter.convert()``: a page that fails is left out, as there."""
    from docx import Document

    ctx.progress(0.02, f"Analysing {total} page(s)")
    cv = pdf2docx_class(str(src))
    try:
        settings = cv.default_settings
        cv.load_pages()
        ctx.check_cancelled()
        cv.parse_document(**settings)
        pages = [page for page in cv.pages if not page.skip_parsing]
        count = max(len(pages), 1)
        for i, page in enumerate(pages):
            ctx.check_cancelled()
            ctx.progress(0.1 + 0.75 * i / count, f"Reading page {i + 1}/{count}")
            try:
                page.parse(**settings)
            except Exception:  # noqa: BLE001 - like pdf2docx's ignore_page_error
                logging.getLogger(__name__).debug("page %d skipped", page.id + 1)
        parsed = [page for page in cv.pages if page.finalized]
        if not parsed:
            raise ConversionError("PDF to Word conversion failed: no page could be read.")
        document = Document()
        for i, page in enumerate(parsed):
            ctx.check_cancelled()
            ctx.progress(0.85 + 0.13 * i / len(parsed), f"Writing page {i + 1}/{len(parsed)}")
            try:
                page.make_docx(document)
            except Exception:  # noqa: BLE001 - like pdf2docx's ignore_page_error
                logging.getLogger(__name__).debug("page %d not written", page.id + 1)
        ctx.check_cancelled()
        document.save(str(dst))
    except ConversionError:  # includes ConversionCancelled
        raise
    except Exception as exc:
        raise ConversionError(f"PDF to Word conversion failed: {exc}") from exc
    finally:
        cv.close()


# --- PDF tools (not conversions) -------------------------------------------------


def merge_pdfs(sources: list[Path], dst: Path) -> Path:
    """Join several PDFs into one, in the given order (see ``pdf_tools.merge``)."""
    from ..pdf_tools import merge

    return merge(sources, dst, overwrite=True)


def split_pdf(src: Path, out_dir: Path) -> list[Path]:
    """Save every page of ``src`` as its own PDF in ``out_dir`` (see ``pdf_tools.split``)."""
    from ..pdf_tools import split

    return split(src, out_dir)
