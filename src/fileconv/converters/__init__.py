"""Converter plugins. Add new plugins to ``all_converters``."""

from .base import ConversionCancelled, ConversionContext, ConversionError, Converter


def all_converters(*, use_word: bool = True) -> list[Converter]:
    """All converter plugins.

    ``use_word``: use Microsoft Word for Word → PDF when it's installed (Windows).
    Without Word, or with ``use_word=False``, LibreOffice does those conversions.
    """
    from .image_pdf import ImageToPdfConverter
    from .images import ImageConverter
    from .msword import WordConverter
    from .office import OfficeConverter
    from .pdf import PdfToImageConverter, PdfToTextConverter, PdfToWordConverter

    office = OfficeConverter()
    return [
        ImageConverter(),
        ImageToPdfConverter(),
        PdfToImageConverter(),
        PdfToTextConverter(),
        PdfToWordConverter(),
        office,
        WordConverter(enabled=use_word, fallback=office),
    ]


__all__ = [
    "ConversionCancelled",
    "ConversionContext",
    "ConversionError",
    "Converter",
    "all_converters",
]
