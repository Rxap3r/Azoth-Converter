"""Quality levels and the limits that keep conversions from getting too low.

Lossless conversions (office → PDF, image → PDF, PNG → WebP, …) always keep
full quality; the level only affects lossy formats (JPG, WebP from photos,
HEIC, AVIF) and the resolution of PDF pages turned into images.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

MIN_IMAGE_QUALITY = 75  # below this, compression artefacts become clearly visible
MAX_IMAGE_QUALITY = 100
MIN_DPI = 150  # below this, text in PDF page images gets blurry
MAX_DPI = 600


@dataclass(frozen=True)
class QualityLevel:
    id: str
    label: str
    description: str
    image_quality: int
    dpi: int


LEVELS = [
    QualityLevel(
        "maximum",
        "Maximum (recommended)",
        "Looks the same as the original. Biggest files. Best for keeping and printing.",
        95,
        300,
    ),
    QualityLevel(
        "high",
        "High",
        "Looks almost the same (only visible when zoomed in a lot). Clearly smaller files.",
        90,
        200,
    ),
    QualityLevel(
        "compact",
        "Smaller files",
        "Good for screens, e-mail and sharing. Smallest files; fine details may soften.",
        82,
        150,
    ),
]
BY_ID = {level.id: level for level in LEVELS}
DEFAULT = BY_ID["maximum"]


def _clamp(value: Any, low: int, high: int) -> int:
    return max(low, min(high, int(value)))


def resolve_options(options: dict[str, Any] | None) -> dict[str, Any]:
    """Fill in quality settings from the chosen level and enforce the limits.

    Explicit ``quality`` / ``dpi`` values win over the level but are kept within
    the allowed range.
    """
    result = dict(options or {})
    level = BY_ID.get(str(result.get("level") or DEFAULT.id), DEFAULT)
    quality = result.get("quality")
    dpi = result.get("dpi")
    result["quality"] = _clamp(
        level.image_quality if quality is None else quality, MIN_IMAGE_QUALITY, MAX_IMAGE_QUALITY
    )
    result["dpi"] = _clamp(level.dpi if dpi is None else dpi, MIN_DPI, MAX_DPI)
    result["level"] = level.id
    return result
