"""Image conversions with Pillow (plus pillow-heif for iPhone HEIC photos).

Privacy: EXIF, GPS and XMP metadata are removed by default. Pass the option
``keep_metadata=True`` to keep EXIF data.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from PIL import Image, ImageOps, ImageSequence, features

from .. import resize
from .base import ConversionContext, ConversionError, Converter

try:
    import pillow_heif

    pillow_heif.register_heif_opener()
    HEIF_SUPPORTED = True
except ImportError:  # pragma: no cover - optional dependency
    HEIF_SUPPORTED = False

AVIF_SUPPORTED = bool(features.check("avif"))
# Load all of Pillow's format readers now (at start-up, one thread), not lazily while
# several photos are opened at once in parallel threads.
Image.init()

# Format id -> Pillow format name used when saving.
PIL_SAVE_FORMATS = {
    "jpg": "JPEG",
    "png": "PNG",
    "webp": "WEBP",
    "bmp": "BMP",
    "tiff": "TIFF",
    "gif": "GIF",
    "ico": "ICO",
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
MULTI_FRAME = {"gif", "webp", "tiff"}
# Sources without compression loss: converting them to WebP stays lossless too.
LOSSLESS_SOURCES = {"png", "bmp", "gif", "tiff", "ico"}
DEFAULT_QUALITY = 95  # high by default: the goal is conversions as close to 1:1 as possible
# Formats that cannot store transparency.
NO_ALPHA = {"jpg", "bmp"}
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


ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)  # the sizes Windows uses
ICO_MAX = 256


def _square(img: Image.Image) -> Image.Image:
    """Put the picture in the centre of a transparent square. Icons are square: without
    this, a wide picture gets only small, distorted icon sizes. Nothing is cut off."""
    if img.width == img.height:
        return img
    side = max(img.size)
    rgba = img.convert("RGBA")
    canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    canvas.paste(rgba, ((side - img.width) // 2, (side - img.height) // 2))
    return canvas


def _largest_first(path: Path) -> None:
    """Put the largest picture first in the icon's list. Windows selects the correct size
    itself, but many viewers show only the first one (Pillow writes 16 × 16 first)."""
    data = bytearray(path.read_bytes())
    count = int.from_bytes(data[4:6], "little")
    entries = [bytes(data[6 + 16 * i : 22 + 16 * i]) for i in range(count)]
    entries.sort(key=lambda e: e[0] or 256, reverse=True)  # width 0 means 256
    data[6 : 6 + 16 * count] = b"".join(entries)
    path.write_bytes(bytes(data))


class ImageConverter(Converter):
    id = "images"
    label = "Pillow"
    priority = 10
    parallel_safe = True  # Pillow and pillow-heif work in parallel threads

    def capabilities(self) -> Iterable[tuple[str, str]]:
        for src in READABLE:
            for dst in PIL_SAVE_FORMATS:
                if src != dst:
                    yield src, dst

    def supports_resize(self, src: str, dst: str) -> bool:
        return src in READABLE and dst in PIL_SAVE_FORMATS

    def quality_note(self, src: str, dst: str) -> str | None:
        if src == dst and dst in ("jpg", "webp", "heic", "avif"):
            return (
                f"{dst.upper()} is a lossy format: Azoth Converter saves the picture again "
                "with the selected quality."
            )
        if dst == "gif":
            return "GIF has only 256 colours. Thus, photos can look grainy."
        if dst == "ico":
            return (
                "Icons are square and 256 × 256 pixels or smaller. Azoth Converter makes "
                "larger pictures smaller and adds a transparent border to pictures that "
                "are not square."
            )
        if dst == "jpg" and src in ("png", "gif", "webp", "ico", "tiff"):
            return "JPEG has no transparency. Transparent areas become white."
        return None

    def convert(self, src: Path, dst: Path, ctx: ConversionContext) -> list[Path]:
        dst_id = dst.suffix.lower().lstrip(".")
        dst_id = {"jpeg": "jpg", "tif": "tiff", "heif": "heic"}.get(dst_id, dst_id)
        pil_format = PIL_SAVE_FORMATS.get(dst_id)
        if pil_format is None:
            raise ConversionError(f"Azoth Converter cannot write {dst_id.upper()} images.")

        quality = int(ctx.option("quality", DEFAULT_QUALITY))
        src_id = {"jpeg": "jpg", "tif": "tiff", "heif": "heic"}.get(
            src.suffix.lower().lstrip("."), src.suffix.lower().lstrip(".")
        )
        keep_metadata = bool(ctx.option("keep_metadata", False))
        size: resize.Resize | None = ctx.option("resize", None)

        def prepare(frame: Image.Image, done: float = 0.0, share: float = 0.85) -> Image.Image:
            # The size is applied after turning the picture upright (in _prepare_frame),
            # so "width" means the width the user sees.
            frame = _prepare_frame(frame, dst_id)
            if size is None:
                return frame
            ai = resize.uses_ai(size, *frame.size)
            if ai and not used_ai:
                used_ai.append(True)
                ctx.progress(done, "Enhancing with AI")
            resized = resize.apply(
                frame,
                size,
                progress=lambda f: ctx.progress(done + f * share, "Enhancing with AI"),
                cancelled=ctx.check_cancelled,
            )
            if resized.size != frame.size and not changed:
                changed.append(
                    f"New size: {resized.width} × {resized.height} px "
                    f"(was {frame.width} × {frame.height} px)."
                )
            if resized.size == frame.size and size.would_enlarge(*frame.size) and not kept:
                kept.append(
                    f"Kept the original size ({frame.width} × {frame.height} px): the picture "
                    "is already smaller and “Don't enlarge smaller pictures” is on."
                )
            return resized

        kept: list[str] = []
        changed: list[str] = []
        used_ai: list[bool] = []

        try:
            with Image.open(src) as im:
                exif = im.getexif() if keep_metadata else None
                icc_profile = im.info.get("icc_profile")
                n_frames = getattr(im, "n_frames", 1)
                if dst_id in MULTI_FRAME and n_frames > 1:
                    frames = []
                    for i, frame in enumerate(ImageSequence.Iterator(im)):
                        ctx.check_cancelled()
                        frames.append(prepare(frame.copy(), i / n_frames * 0.8, 0.8 / n_frames))
                        ctx.progress((i + 1) / n_frames * 0.8, f"Frame {i + 1}/{n_frames}")
                    durations = im.info.get("duration")
                else:
                    frames = [prepare(im)]
                    durations = None
        except ConversionError:
            raise
        except resize.ResizeError as exc:
            raise ConversionError(str(exc)) from exc
        except Exception as exc:  # Pillow raises many exception types for bad files
            raise ConversionError(f"Cannot read the image ({exc}).") from exc

        ctx.warnings.extend(kept)
        ctx.notes.extend(changed)
        if used_ai:
            ctx.notes.append(
                "Enhanced with AI: the added detail is invented by the AI, so it isn't "
                "fully true to the original."
            )
        ctx.check_cancelled()
        first = frames[0]
        for frame in frames:
            for key in PRIVATE_INFO_KEYS:
                frame.info.pop(key, None)

        save_args: dict = {}
        if icc_profile and dst_id in ("jpg", "png", "webp", "tiff", "heic", "avif"):
            save_args["icc_profile"] = icc_profile  # colour profile, not personal data
        if exif is not None and dst_id in ("jpg", "png", "webp", "tiff", "heic", "avif"):
            exif[0x0112] = 1  # orientation is already applied to the pixels
            if size is not None:  # the old pixel size would be wrong now
                exif.get_ifd(0x8769).pop(0xA002, None)
                exif.get_ifd(0x8769).pop(0xA003, None)
            save_args["exif"] = exif.tobytes()
        if dst_id == "webp" and src_id in LOSSLESS_SOURCES:
            save_args["lossless"] = True  # pixel-perfect copy of a lossless original
        elif dst_id in ("jpg", "webp", "heic", "avif"):
            save_args["quality"] = quality
        if dst_id == "jpg":
            save_args["optimize"] = True
            save_args["subsampling"] = 0  # full colour resolution (4:4:4), sharper edges
        if dst_id == "png":
            save_args["optimize"] = True
        if dst_id == "tiff":
            save_args["compression"] = "tiff_lzw"
        if dst_id == "ico":
            first = _square(first)
            side = min(ICO_MAX, first.width)
            save_args["sizes"] = sorted({(s, s) for s in ICO_SIZES if s <= side} | {(side, side)})
            if side < ICO_MAX:
                ctx.notes.append(
                    f"The icon is {side} × {side} px. To make a larger icon, "
                    "select a larger “Picture size”."
                )
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
            if dst_id == "ico":
                _largest_first(dst)
        except Exception as exc:
            raise ConversionError(f"Cannot save the {dst_id.upper()} file ({exc}).") from exc
        return [dst]
