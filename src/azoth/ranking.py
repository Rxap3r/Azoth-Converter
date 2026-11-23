"""Which target formats to show first: the most common and useful conversions.

The first target in a list is also the default choice in the app. Old formats
(DOC, XLS, PPT) always come last: they're only needed for very old software.
"""

from __future__ import annotations

from collections.abc import Iterable

from . import formats

# Most useful targets first, per kind of source file. Formats not listed here
# follow afterwards in a stable order.
TARGET_ORDER: dict[str, list[str]] = {
    formats.PDF: ["docx", "xlsx", "jpg", "png", "txt", "odt", "rtf", "webp", "tiff", "bmp", "doc"],
    formats.DOCUMENT: [
        "pdf", "docx", "odt", "txt", "jpg", "png", "rtf", "webp", "tiff", "bmp", "doc",
    ],
    formats.SPREADSHEET: [
        "pdf", "xlsx", "csv", "ods", "png", "jpg", "webp", "tiff", "bmp", "xls",
    ],
    formats.PRESENTATION: ["pdf", "pptx", "png", "jpg", "odp", "webp", "tiff", "bmp", "ppt"],
    formats.IMAGE: ["jpg", "png", "pdf", "webp", "heic", "avif", "tiff", "gif", "bmp", "ico"],
}  # fmt: skip

# Used when files of different kinds are converted together.
MIXED_ORDER = [
    "pdf", "docx", "jpg", "png", "xlsx", "pptx", "webp", "txt", "csv", "odt", "ods", "odp",
    "heic", "avif", "tiff", "gif", "rtf", "bmp", "ico", "doc", "xls", "ppt",
]  # fmt: skip


def _order_for(source_categories: Iterable[str]) -> list[str]:
    categories = set(source_categories)
    if len(categories) == 1:
        return TARGET_ORDER.get(categories.pop(), MIXED_ORDER)
    return MIXED_ORDER


def rank(
    targets: Iterable[formats.Format], source_categories: Iterable[str]
) -> list[formats.Format]:
    """Sort ``targets`` so the most useful conversion comes first."""
    order = _order_for(source_categories)
    position = {fmt_id: i for i, fmt_id in enumerate(order)}
    fallback = {fmt_id: i for i, fmt_id in enumerate(MIXED_ORDER)}
    return sorted(
        targets,
        key=lambda f: (position.get(f.id, len(order)), fallback.get(f.id, len(MIXED_ORDER)), f.id),
    )
