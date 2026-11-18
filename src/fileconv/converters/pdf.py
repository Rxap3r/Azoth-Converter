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

RASTER_TARGETS = {"png": "PNG", "jpg": "JPEG", "webp": "WEBP", "bmp": "BMP", "tiff": "TIFF"}


def _open(src: Path) -> pymupdf.Document:
    try:
        doc = pymupdf.open(src, filetype="pdf")
    except Exception as exc:
        raise ConversionError(
            "Could not open the PDF. The file is damaged or isn't a real PDF."
        ) from exc
    if doc.needs_pass:
        doc.close()
        raise ConversionError("This PDF is password-protected. Remove the password first.")
    return doc


def page_file_name(dst: Path, index: int, total: int) -> Path:
    """``report.png`` → ``report_page001.png`` when there are several pages."""
    if total == 1:
        return dst
    width = max(3, len(str(total)))
    return dst.with_name(f"{dst.stem}_page{index + 1:0{width}d}{dst.suffix}")


def is_probably_scanned(src: Path, sample_pages: int = 5) -> bool:
    """True if the first pages contain images but (almost) no selectable text."""
    with _open(src) as doc:
        pages = [doc[i] for i in range(min(sample_pages, doc.page_count))]
        text = sum(len(p.get_text("text").strip()) for p in pages)
        images = sum(len(p.get_images()) for p in pages)
    return text < 20 and images > 0


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
        dpi = int(ctx.option("dpi", 150))
        quality = int(ctx.option("quality", 90))
        outputs: list[Path] = []
        with _open(src) as doc:
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
                kwargs = {"quality": quality} if dst_id in ("jpg", "webp") else {}
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
        parts: list[str] = []
        with _open(src) as doc:
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

        # Check early so the user gets a clear message instead of an empty document.
        if is_probably_scanned(src):
            raise ConversionError(
                "This PDF looks like a scan (pictures of pages, no selectable text). "
                "Converting it to Word needs text recognition (OCR), which is planned "
                "for a later version."
            )
        with _open(src) as doc:
            total = doc.page_count

        # pdf2docx has no progress callback or cancel hook; it logs chatty INFO lines.
        ctx.progress(0.05, f"Rebuilding layout of {total} page(s)")
        logging.disable(logging.WARNING)
        cv = Pdf2Docx(str(src))
        try:
            cv.convert(str(dst))
        except Exception as exc:
            raise ConversionError(f"PDF to Word conversion failed: {exc}") from exc
        finally:
            cv.close()
            logging.disable(logging.NOTSET)
        ctx.check_cancelled()
        return [dst]


# --- PDF tools (not conversions) -------------------------------------------------


def merge_pdfs(sources: list[Path], dst: Path) -> Path:
    """Join several PDFs into one, in the given order."""
    if not sources:
        raise ConversionError("No PDFs to merge")
    out = pymupdf.open()
    try:
        for src in sources:
            with _open(src) as doc:
                out.insert_pdf(doc)
        out.save(dst, garbage=3, deflate=True)
    finally:
        out.close()
    return dst


def split_pdf(src: Path, out_dir: Path) -> list[Path]:
    """Save every page of ``src`` as its own PDF in ``out_dir``."""
    out_dir.mkdir(parents=True, exist_ok=True)
    outputs = []
    with _open(src) as doc:
        total = doc.page_count
        for i in range(total):
            part = pymupdf.open()
            part.insert_pdf(doc, from_page=i, to_page=i)
            path = page_file_name(out_dir / f"{src.stem}.pdf", i, total)
            if total == 1:
                path = out_dir / f"{src.stem}_page001.pdf"
            part.save(path, garbage=3, deflate=True)
            part.close()
            outputs.append(path)
    return outputs
