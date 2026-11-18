"""Image conversions with Pillow (plus pillow-heif for iPhone HEIC photos).

Privacy: EXIF, GPS and XMP metadata are removed by default. Pass the option
``keep_metadata=True`` to keep EXIF data.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from PIL import Image, ImageOps, ImageSequence, features

from .base import ConversionContext, ConversionError, Converter

try:
    import pillow_heif

    pillow_heif.register_heif_opener()
    HEIF_SUPPORTED = True
except ImportError:  # pragma: no cover - optional dependency
    HEIF_SUPPORTED = False

AVIF_SUPPORTED = bool(features.check("avif"))

# Format id -> Pillow format name used when saving.
PIL_SAVE_FORMATS = {
    "jpg": "JPEG",
    "png": "PNG",
    "webp": "WEBP",
    "bmp": "BMP",
    "tiff": "TIFF",
    "gif": "GIF",
    "ico": "ICO",
    "pdf": "PDF",
}
if HEIF_SUPPORTED:
    PIL_SAVE_FORMATS["heic"] = "HEIF"
if AVIF_SUPPORTED:
    PIL_SAVE_FORMATS["avif"] = "AVIF"

READABLE = ["jpg", "png", "webp", "bmp", "tiff", "gif", "ico"]
if HEIF_SUPPORTED:
    READABLE.append("heic")
if AVIF_SUPPORTED:
    READABLE.append("avif")

# Formats that can hold several frames/pages in one file.
MULTI_FRAME = {"gif", "webp", "tiff", "pdf"}
# Formats that cannot store transparency.
NO_ALPHA = {"jpg", "bmp", "pdf"}
# Metadata keys Pillow may carry over from the source image.
PRIVATE_INFO_KEYS = ("exif", "xmp", "XML:com.adobe.xmp", "comment", "photoshop", "iptc")


def _flatten(img: Image.Image, background=(255, 255, 255)) -> Image.Image:
    """Put a transparent image on a white background and return an RGB image."""
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        rgba = img.convert("RGBA")
        canvas = Image.new("RGB", rgba.size, background)
        canvas.paste(rgba, mask=rgba.getchannel("A"))
        return canvas
    return img.convert("RGB")


def _prepare_frame(img: Image.Image, dst: str) -> Image.Image:
    # Rotate according to the EXIF orientation first, because the orientation
    # tag may be removed together with the rest of the metadata.
    img = ImageOps.exif_transpose(img)  # always returns a copy without file-specific tags
    if dst in NO_ALPHA:
        return _flatten(img)
    if dst == "gif":
        return img.convert("RGBA") if img.mode in ("RGBA", "LA", "P") else img.convert("RGB")
    if img.mode not in ("RGB", "RGBA", "L", "LA", "1", "P", "I;16", "I"):
        return img.convert("RGBA" if "A" in img.getbands() else "RGB")
    if dst in ("webp", "heic", "avif", "ico") and img.mode not in ("RGB", "RGBA"):
        return img.convert("RGBA" if "A" in img.getbands() or img.mode == "P" else "RGB")
    return img


class ImageConverter(Converter):
    id = "images"
    label = "Pillow"
    priority = 10

    def capabilities(self) -> Iterable[tuple[str, str]]:
        for src in READABLE:
            for dst in PIL_SAVE_FORMATS:
                if src != dst:
                    yield src, dst

    def final_only(self, src: str, dst: str) -> bool:
        return dst == "pdf"  # an image-only PDF is a "scan"; don't chain it into Word etc.

    def quality_note(self, src: str, dst: str) -> str | None:
        if dst == "gif":
            return "GIF supports only 256 colours, so photos may look grainy."
        if dst == "ico":
            return "Icons are limited to 256×256 pixels; larger images are scaled down."
        if dst == "jpg" and src in ("png", "gif", "webp", "ico", "tiff"):
            return "JPEG has no transparency; transparent areas become white."
        return None

    def convert(self, src: Path, dst: Path, ctx: ConversionContext) -> list[Path]:
        dst_id = dst.suffix.lower().lstrip(".")
        dst_id = {"jpeg": "jpg", "tif": "tiff", "heif": "heic"}.get(dst_id, dst_id)
        pil_format = PIL_SAVE_FORMATS.get(dst_id)
        if pil_format is None:
            raise ConversionError(f"Cannot write {dst_id.upper()} images")

        quality = int(ctx.option("quality", 90))
        keep_metadata = bool(ctx.option("keep_metadata", False))

        try:
            with Image.open(src) as im:
                exif = im.getexif() if keep_metadata else None
                icc_profile = im.info.get("icc_profile")
                n_frames = getattr(im, "n_frames", 1)
                if dst_id in MULTI_FRAME and n_frames > 1:
                    frames = []
                    for i, frame in enumerate(ImageSequence.Iterator(im)):
                        ctx.check_cancelled()
                        frames.append(_prepare_frame(frame.copy(), dst_id))
                        ctx.progress((i + 1) / n_frames * 0.8, f"Frame {i + 1}/{n_frames}")
                    durations = im.info.get("duration")
                else:
                    frames = [_prepare_frame(im, dst_id)]
                    durations = None
        except ConversionError:
            raise
        except Exception as exc:  # Pillow raises many exception types for bad files
            raise ConversionError(f"Could not read image: {exc}") from exc

        ctx.check_cancelled()
        first = frames[0]
        for frame in frames:
            for key in PRIVATE_INFO_KEYS:
                frame.info.pop(key, None)

        save_args: dict = {}
        if icc_profile and dst_id in ("jpg", "png", "webp", "tiff", "heic", "avif", "pdf"):
            save_args["icc_profile"] = icc_profile  # colour profile, not personal data
        if exif is not None and dst_id in ("jpg", "png", "webp", "tiff", "heic", "avif"):
            exif[0x0112] = 1  # orientation is already applied to the pixels
            save_args["exif"] = exif.tobytes()
        if dst_id in ("jpg", "webp", "heic", "avif"):
            save_args["quality"] = quality
        if dst_id == "jpg":
            save_args["optimize"] = True
        if dst_id == "png":
            save_args["optimize"] = True
        if dst_id == "tiff":
            save_args["compression"] = "tiff_lzw"
        if dst_id == "pdf":
            save_args["resolution"] = float(ctx.option("dpi", 150))
        if dst_id == "ico":
            largest = min(256, max(first.size))
            save_args["sizes"] = [(s, s) for s in (16, 24, 32, 48, 64, 128, 256) if s <= largest]
        if len(frames) > 1:
            save_args["save_all"] = True
            save_args["append_images"] = frames[1:]
            if dst_id in ("gif", "webp"):
                save_args["loop"] = 0
                if durations:
                    save_args["duration"] = durations

        ctx.progress(0.9, "Saving")
        try:
            first.save(dst, format=pil_format, **save_args)
        except Exception as exc:
            raise ConversionError(f"Could not save {dst_id.upper()}: {exc}") from exc
        return [dst]
