"""Changing a picture's size in pixels (smaller, or plainly bigger).

Pictures always keep their proportions: a size is a width, a height, a screen size (a
box the picture fits in, turned for portrait pictures), the longest side, or a
percentage. Pictures get the chosen size, smaller ones too, unless ``enlarge`` is off
("Don't enlarge smaller pictures"). Enlarging is smooth and adds no detail. Nothing
changes unless the user chooses a size.

Option ``resize`` (a :class:`Resize`) is read by the image converter; the command line
writes it as ``50%``, ``2000`` (longest side), ``1920x1080`` (screen size), ``1920x``
(width) or ``x1080`` (height).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace

from PIL import Image

PERCENT = "percent"
LONGEST = "longest"
WIDTH = "width"
HEIGHT = "height"
FIT = "fit"
MODES = (PERCENT, LONGEST, WIDTH, HEIGHT, FIT)

MIN_PERCENT = 1
MAX_PERCENT = 800
MAX_SIDE = 60_000
MAX_PIXELS = 250_000_000
"""Larger results would need many GB of memory (and most programs can't open them)."""


class ResizeError(ValueError):
    """A size the user entered can't be used. The message is shown to the user."""


@dataclass(frozen=True)
class Resize:
    mode: str
    width: int = 0
    """Pixels for WIDTH, LONGEST and FIT."""
    height: int = 0
    """Pixels for HEIGHT and FIT."""
    percent: float = 100
    enlarge: bool = True
    """Make pictures bigger that are smaller than the chosen size. Off: they stay as they
    are. (Not for PERCENT, where the number says whether the picture gets bigger.)"""

    def __post_init__(self) -> None:
        if self.mode not in MODES:
            raise ResizeError(f"Unknown size choice: {self.mode}")
        if self.mode == PERCENT:
            if not MIN_PERCENT <= self.percent <= MAX_PERCENT:
                raise ResizeError(
                    f"Please choose a percentage from {MIN_PERCENT} to {MAX_PERCENT}."
                )
            return
        needed = {LONGEST: ("width",), WIDTH: ("width",), HEIGHT: ("height",)}
        for name in needed.get(self.mode, ("width", "height")):
            if not 1 <= getattr(self, name) <= MAX_SIDE:
                raise ResizeError(f"Please choose a size from 1 to {MAX_SIDE:,} pixels.")

    def describe(self) -> str:
        """Short text for messages, e.g. "longest side 2000 px"."""
        if self.mode == PERCENT:
            return f"{self.percent:g} %"
        text = {
            LONGEST: f"longest side {self.width} px",
            WIDTH: f"{self.width} px wide",
            HEIGHT: f"{self.height} px high",
            FIT: f"screen size {self.width} × {self.height} px",
        }[self.mode]
        return text

    def would_enlarge(self, width: int, height: int) -> bool:
        """True if the picture stays as it is only because ``enlarge`` is off."""
        if self.mode == PERCENT or self.enlarge:
            return False
        return replace(self, enlarge=True).new_size(width, height) != (width, height)

    def new_size(self, width: int, height: int) -> tuple[int, int]:
        """The size a ``width`` × ``height`` picture gets (the same size if it stays)."""
        box_w, box_h = self.width, self.height
        if self.mode == FIT and (height > width) != (box_h > box_w) and width != height:
            box_w, box_h = box_h, box_w  # a screen size turned for portrait pictures
        if self.mode == PERCENT:
            scale = self.percent / 100
        else:
            scale = {
                LONGEST: lambda: self.width / max(width, height),
                WIDTH: lambda: self.width / width,
                HEIGHT: lambda: self.height / height,
                FIT: lambda: min(box_w / width, box_h / height),
            }[self.mode]()
            if scale > 1 and not self.enlarge:
                return width, height
        if self.mode == WIDTH:
            size = (self.width, round(height * scale))
        elif self.mode == HEIGHT:
            size = (round(width * scale), self.height)
        elif self.mode == LONGEST and width >= height:
            size = (self.width, round(height * scale))
        elif self.mode == LONGEST:
            size = (round(width * scale), self.width)
        else:
            size = (round(width * scale), round(height * scale))
        return max(1, size[0]), max(1, size[1])


_SPEC = re.compile(r"^\s*(?:(\d+(?:\.\d+)?)\s*%|(\d+)|(\d*)\s*[x×]\s*(\d*))\s*$", re.IGNORECASE)


def parse(text: str, enlarge: bool = True) -> Resize:
    """Read a size typed on the command line (see the module help for the forms)."""
    match = _SPEC.match(text or "")
    if not match or (match.group(3) == "" and match.group(4) == ""):
        raise ResizeError(
            f'"{text}" is not a size. Examples: 50%, 2000 (longest side), '
            "1920x1080 (fit inside), 1920x (width), x1080 (height)."
        )
    percent, longest, width, height = match.groups()
    if percent is not None:
        return Resize(PERCENT, percent=float(percent))
    if longest is not None:
        return Resize(LONGEST, width=int(longest), enlarge=enlarge)
    if width and height:
        return Resize(FIT, width=int(width), height=int(height), enlarge=enlarge)
    if width:
        return Resize(WIDTH, width=int(width), enlarge=enlarge)
    return Resize(HEIGHT, height=int(height), enlarge=enlarge)


def picture_size(path) -> tuple[int, int] | None:
    """Width × height of a picture as it is shown (turned per its EXIF orientation), or
    None if it can't be read. Only the file's header is read, so this is fast."""
    from .converters import images  # noqa: F401 - registers HEIC/AVIF reading

    try:
        with Image.open(path) as im:
            width, height = im.size
            orientation = im.getexif().get(0x0112, 1)
    except Exception:  # noqa: BLE001 - damaged or unknown files simply show no size
        return None
    return (height, width) if orientation in (5, 6, 7, 8) else (width, height)


# Pillow modes that resize directly; others are converted first. Transparent pictures
# are resized "premultiplied" (RGBa, La), so edges don't get dark fringes.
_PREMULTIPLIED = {"RGBA": "RGBa", "LA": "La"}
_DIRECT = {"RGB", "L", "I", "F", "CMYK", "I;16"}


def apply(img: Image.Image, spec: Resize | None) -> Image.Image:
    """``img`` in its new size (the same picture if the size doesn't change)."""
    if spec is None:
        return img
    size = spec.new_size(*img.size)
    if size == img.size:
        return img
    if size[0] * size[1] > MAX_PIXELS:
        raise ResizeError(
            f"The new size ({size[0]:,} × {size[1]:,} pixels) is too big. "
            "Please choose a smaller size."
        )
    # Lanczos: the sharpest clean result when making smaller. Bicubic for enlarging:
    # smooth, without the halos Lanczos can add around edges.
    smaller = size[0] * size[1] < img.size[0] * img.size[1]
    method = Image.Resampling.LANCZOS if smaller else Image.Resampling.BICUBIC
    info = dict(img.info)
    if img.mode == "P" or "transparency" in info:
        # A transparent colour (or a palette) can't be blended: use a real alpha channel.
        transparent = "transparency" in info or (img.mode == "P" and img.palette.mode == "RGBA")
        info.pop("transparency", None)
        img = img.convert("RGBA" if transparent else "RGB")
    elif img.mode == "1":
        img = img.convert("L")
    elif img.mode not in _DIRECT and img.mode not in _PREMULTIPLIED:
        img = img.convert("RGBA" if "A" in img.getbands() else "RGB")
    mode = img.mode
    if mode in _PREMULTIPLIED:
        resized = img.convert(_PREMULTIPLIED[mode]).resize(size, method).convert(mode)
    else:
        resized = img.resize(size, method)
    resized.info = info
    return resized


# --- ready-made sizes for the app (biggest first) ------------------------------------


@dataclass(frozen=True)
class Preset:
    label: str
    width: int = 0
    height: int = 0
    percent: float = 100


_SIDES = [
    (7680, 4320, "8K"),
    (5120, 2880, "5K"),
    (3840, 2160, "4K UHD"),
    (2560, 1440, "QHD, 1440p"),
    (1920, 1080, "Full HD, 1080p"),
    (1600, 900, "HD+"),
    (1280, 720, "HD, 720p"),
    (1024, 576, "Small"),
    (854, 480, "SD, 480p"),
    (640, 360, "Very small"),
]

PRESETS: dict[str, list[Preset]] = {
    FIT: [Preset(f"{w} × {h} ({name})", w, h) for w, h, name in _SIDES],
    LONGEST: [Preset(f"{w} px ({name})", w, h) for w, h, name in _SIDES],
    WIDTH: [Preset(f"{w} px ({name})", w, h) for w, h, name in _SIDES],
    HEIGHT: [Preset(f"{h} px ({name})", w, h) for w, h, name in _SIDES],
    PERCENT: [Preset(f"{p} %", percent=p) for p in (400, 300, 200, 150, 125, 75, 50, 33, 25, 10)],
}
DEFAULT_PRESET = {FIT: 4, LONGEST: 4, WIDTH: 4, HEIGHT: 4, PERCENT: 6}
"""Position of the preset chosen first: Full HD, or 50 %."""
