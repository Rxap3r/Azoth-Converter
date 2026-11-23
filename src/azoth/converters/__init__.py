"""Converter plugins. Add new plugins to ``all_converters``."""

from .base import ConversionCancelled, ConversionContext, ConversionError, Converter, RetryAlone


def all_converters(*, use_word: bool = True) -> list[Converter]:
    """All converter plugins.

    ``use_word``: use Microsoft Office (Word, Excel, PowerPoint) where it's installed
    (Windows). Without Office, or with ``use_word=False``, LibreOffice does those
    conversions.
    """
    from .image_pdf import ImageToPdfConverter
    from .images import ImageConverter
    from .msword import office_converters
    from .ocr import OcrConverter
    from .office import OfficeConverter
    from .pdf import PdfToImageConverter, PdfToTextConverter, PdfToWordConverter
    from .pdf_excel import PdfToExcelConverter

    office = OfficeConverter()
    return [
        ImageConverter(),
        ImageToPdfConverter(),
        PdfToImageConverter(),
        PdfToTextConverter(),
        PdfToWordConverter(),
        PdfToExcelConverter(),
        OcrConverter(),
        office,
        *office_converters(enabled=use_word, fallback=office),
    ]


__all__ = [
    "ConversionCancelled",
    "ConversionContext",
    "ConversionError",
    "Converter",
    "RetryAlone",
    "all_converters",
]
