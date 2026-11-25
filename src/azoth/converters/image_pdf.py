"""Images → PDF without quality loss.

* JPEG photos are embedded as they are (no re-compression). Only the metadata
  block is cut out for privacy, unless the user keeps metadata. EXIF rotation
  is applied by rotating the picture on the page, not by re-encoding it.
* Other formats are stored losslessly (PNG/Flate), including transparency.
* Multi-page TIFFs and animated GIFs become one page per frame.
* With the ``ocr`` option the recognised text is added as an invisible layer, so the
  PDF is searchable; the pictures stay the same.
"""

from __future__ import annotations

import io
from collections.abc import Iterable
from pathlib import Path

import pymupdf
from PIL import Image, ImageOps, ImageSequence

from .base import ConversionContext, ConversionError, Converter
from .images import READABLE
from .jpeg_tools import strip_jpeg_metadata

# EXIF orientation → counter-clockwise rotation for PyMuPDF. Mirrored
# orientations (2, 4, 5, 7) are rare and are handled losslessly via PNG.
_JPEG_ROTATION = {1: 0, 3: 180, 6: 270, 8: 90}


def _page_size(width_px: int, height_px: int, dpi: float) -> tuple[float, float]:
    return width_px / dpi * 72, height_px / dpi * 72


def _image_dpi(im: Image.Image, default: float) -> float:
    dpi = im.info.get("dpi")
    try:
        value = float(dpi[0]) if dpi else 0.0
    except (TypeError, ValueError, IndexError):
        value = 0.0
    return value if 30 <= value <= 2400 else default


class ImageToPdfConverter(Converter):
    id = "image-pdf"
    label = "PyMuPDF"
    priority = 20

    def capabilities(self) -> Iterable[tuple[str, str]]:
        for src in READABLE:
            yield src, "pdf"

    def final_only(self, src: str, dst: str) -> bool:
        return True  # an image-only PDF is a "scan"; don't chain it into Word etc.

    def convert(self, src: Path, dst: Path, ctx: ConversionContext) -> list[Path]:
        keep_metadata = bool(ctx.option("keep_metadata", False))
        # Page size only; the picture keeps all its pixels whatever the page size.
        default_dpi = 150.0
        doc = pymupdf.open()
        try:
            with Image.open(src) as im:
                dpi = _image_dpi(im, default_dpi)
                n_frames = getattr(im, "n_frames", 1)
                orientation = im.getexif().get(0x0112, 1)
                if im.format == "JPEG" and n_frames == 1 and orientation in _JPEG_ROTATION:
                    self._add_jpeg(doc, src, im.size, orientation, dpi, keep_metadata)
                else:
                    for i, frame in enumerate(ImageSequence.Iterator(im)):
                        ctx.check_cancelled()
                        ctx.progress(i / n_frames * 0.9, f"Page {i + 1}/{n_frames}")
                        self._add_lossless(doc, frame.copy(), dpi)
            ctx.check_cancelled()
            if ctx.option("ocr", False):
                from .. import ocr
                from . import ocr as ocr_converter

                ctx.progress(0.5, "Reading the text")
                ocr.add_text_layer(
                    doc,
                    ocr_converter.language(ctx),
                    progress=lambda f, m: ctx.progress(0.5 + f * 0.45, m),
                    cancel=ctx.cancel_event,
                    turn_pages=bool(ctx.option("ocr_turn_pages", True)),
                )
            doc.save(dst, garbage=3, deflate=True)
        except ConversionError:
            raise
        except Exception as exc:
            raise ConversionError(f"Cannot convert the image to PDF ({exc}).") from exc
        finally:
            doc.close()
        return [dst]

    @staticmethod
    def _add_jpeg(doc, src: Path, size, orientation: int, dpi: float, keep: bool) -> None:
        data = src.read_bytes()
        if not keep:
            data = strip_jpeg_metadata(data)
        rotate = _JPEG_ROTATION[orientation]
        width, height = size
        if rotate in (90, 270):
            width, height = height, width
        page = doc.new_page(
            width=_page_size(width, height, dpi)[0], height=_page_size(width, height, dpi)[1]
        )
        page.insert_image(page.rect, stream=data, rotate=rotate)

    @staticmethod
    def _add_lossless(doc, frame: Image.Image, dpi: float) -> None:
        img = ImageOps.exif_transpose(frame)
        has_alpha = "A" in img.getbands() or (img.mode == "P" and "transparency" in img.info)
        if img.mode not in ("RGB", "L") or has_alpha:
            img = img.convert("RGBA" if has_alpha else "RGB")
        buf = io.BytesIO()
        save_args = {}
        icc = frame.info.get("icc_profile")
        if icc:
            save_args["icc_profile"] = icc
        img.save(buf, format="PNG", **save_args)  # lossless; no EXIF is written
        width, height = _page_size(img.width, img.height, dpi)
        page = doc.new_page(width=width, height=height)
        page.insert_image(page.rect, stream=buf.getvalue())
