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
OCR_DPI = 300  # pages are read (not saved) at this sharpness; less makes small print unreadable

# Video and audio (converters/media.py). Streams are copied unchanged whenever the
# target can hold them; these settings only apply when something must be re-encoded.
VIDEO_CRF = 18  # H.264: "visually lossless"; higher numbers mean lower quality
MAX_VIDEO_CRF = 23  # never worse than H.264's own default
VP9_CRF = 24  # WebM (VP9), roughly the same look as VIDEO_CRF
AAC_KBPS = 256  # M4A/MP4 sound from lossy sources (lossless sources become ALAC)
OPUS_KBPS = 192
VORBIS_QUALITY = 6  # Ogg Vorbis, about 192 kbit/s
MP3_VBR = 0  # LAME's best VBR setting (V0, about 245 kbit/s)
AVI_MP3_KBPS = 320  # old players expect constant-bitrate MP3 in AVI
MIN_AUDIO_KBPS = 192  # lossy sound is never encoded below this
GIF_MAX_FPS = 15  # video → GIF: more frames make huge files for no visible gain

# "Make smaller" for videos (the user asks for a smaller, lossy copy): H.264 + AAC in MP4,
# which every phone, messenger and e-mail program plays. Level → (shorter side in pixels,
# H.264 CRF). Smaller videos are never enlarged; sound is copied if it's already AAC.
SHRINK_LEVELS = {
    "1080": (1080, 24),  # Full HD: still sharp on a big screen
    "720": (720, 26),  # HD: for e-mail and messengers, about a tenth of a phone video
    "480": (480, 28),  # smallest that still looks fine on a phone
}
SHRINK_DEFAULT = "720"
MAX_SHRINK_CRF = 28  # beyond this, blocks and smearing become obvious
SHRINK_MAX_FPS = 30  # 60 fps phone videos: half the frames, about half the size


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


# --- Compress PDF ------------------------------------------------------------------


@dataclass(frozen=True)
class CompressLevel:
    """How strongly "Compress PDF" shrinks a file.

    ``dpi`` 0 means pictures stay exactly as they are (only the file structure is
    tidied up). Otherwise pictures sharper than ``1.5 × dpi`` are reduced to about
    ``dpi`` (never below it, never enlarged) and saved with ``image_quality``.
    ``photos_to_jpeg`` also turns lossless pictures (PNG-like) into JPG.
    """

    id: str
    label: str
    description: str
    dpi: int
    image_quality: int
    photos_to_jpeg: bool

    @property
    def threshold_dpi(self) -> int:
        return self.dpi * 3 // 2


COMPRESS_LEVELS = [
    CompressLevel(
        "light",
        "Light: no quality loss",
        "Tidies up the file. Text and pictures stay exactly as they are. Saves less.",
        0,
        0,
        False,
    ),
    CompressLevel(
        "balanced",
        "Balanced (recommended)",
        "Very sharp pictures are reduced to 200 dpi: still sharp on screen and in print. "
        "Text stays exactly as it is.",
        200,
        85,
        False,
    ),
    CompressLevel(
        "strong",
        "Strong: smallest file",
        "Smallest file, good for e-mail. Pictures are reduced to 150 dpi and saved as JPG; "
        "fine details and screenshots may soften. Text stays sharp.",
        MIN_DPI,
        MIN_IMAGE_QUALITY,
        True,
    ),
]
COMPRESS_BY_ID = {level.id: level for level in COMPRESS_LEVELS}
DEFAULT_COMPRESS = COMPRESS_BY_ID["balanced"]
