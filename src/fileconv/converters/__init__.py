"""Converter plugins. Add new plugins to ``all_converters``."""

from .base import ConversionCancelled, ConversionContext, ConversionError, Converter


def all_converters() -> list[Converter]:
    from .images import ImageConverter
    from .office import OfficeConverter
    from .pdf import PdfToImageConverter, PdfToTextConverter, PdfToWordConverter

    return [
        ImageConverter(),
        PdfToImageConverter(),
        PdfToTextConverter(),
        PdfToWordConverter(),
        OfficeConverter(),
    ]


__all__ = [
    "ConversionCancelled",
    "ConversionContext",
    "ConversionError",
    "Converter",
    "all_converters",
]
