"""The interface every converter plugin implements."""

from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from collections.abc import Callable, Hashable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ProgressCallback = Callable[[float, str], None]


class ConversionError(Exception):
    """A conversion failed. The message is shown to the user, so keep it readable."""


class ConversionCancelled(ConversionError):
    def __init__(self) -> None:
        super().__init__("Conversion cancelled")


class RetryAlone(ConversionError):
    """A file of a batch that didn't get converted and should be tried on its own."""

    def __init__(self) -> None:
        super().__init__("Not converted in the batch")


@dataclass
class ConversionContext:
    """Everything a converter may use while it runs."""

    work_dir: Path
    """Private temporary folder for this job. It is deleted when the job ends."""
    options: dict[str, Any] = field(default_factory=dict)
    progress: ProgressCallback = lambda fraction, message: None
    cancel_event: threading.Event = field(default_factory=threading.Event)
    warnings: list[str] = field(default_factory=list)
    """Things the user should know about this file's result (e.g. a fallback engine was
    used). Shown on the file and written to the local error log."""

    def check_cancelled(self) -> None:
        if self.cancel_event.is_set():
            raise ConversionCancelled()

    def option(self, name: str, default: Any) -> Any:
        value = self.options.get(name)
        return default if value is None else value


class Converter(ABC):
    id: str = ""
    label: str = ""
    priority: int = 0
    optional: bool = False
    """Optional engines (e.g. Microsoft Word) don't trigger "missing engine" warnings."""
    """When two converters offer the same conversion, the higher priority wins."""
    download_url: str = ""
    """Official download page of a missing engine (the app offers a button that opens it
    in the browser, only when clicked)."""
    parallel_safe: bool = False
    """True if several files may be converted at the same time in different threads
    (never for PyMuPDF, which isn't thread-safe, or for external programs)."""

    def is_available(self) -> bool:
        """False when a required engine (e.g. LibreOffice) is missing."""
        return True

    def unavailable_reason(self) -> str:
        return ""

    @abstractmethod
    def capabilities(self) -> Iterable[tuple[str, str]]:
        """(source format id, target format id) pairs this converter handles."""

    def final_only(self, src: str, dst: str) -> bool:
        """True if this step may only be the last step of a conversion route.

        Used for conversions that may create several files (one image per PDF
        page) or whose result makes no sense to convert further (a photo
        wrapped in a PDF can't become an editable Word document).
        """
        return False

    def first_only(self, src: str, dst: str) -> bool:
        """True if this step only accepts the user's original file, never an
        intermediate result. Example: PDF → Word works well on real PDFs, but
        Excel → PDF → Word would produce a poor Word file.
        """
        return False

    def quality_note(self, src: str, dst: str) -> str | None:
        """A short warning shown to the user when a conversion may lose information."""
        return None

    def batch_key(self, src: str, dst: str) -> Hashable | None:
        """Files with the same key can be converted together by :meth:`convert_batch`
        (faster: the engine program starts once for all of them). None: one by one."""
        return None

    def convert_batch(
        self, jobs: list[tuple[Path, Path]], ctx: ConversionContext
    ) -> list[ConversionError | None]:
        """Convert several (src, dst) pairs with the same :meth:`batch_key` at once.

        Returns one entry per job: None if ``dst`` was created, a ConversionError if that
        file failed for sure, or ConversionError subclass :class:`RetryAlone` if it
        should be tried again on its own (e.g. another file in the batch crashed the
        engine). Raises ConversionCancelled when cancelled.
        """
        return [RetryAlone() for _ in jobs]

    @abstractmethod
    def convert(self, src: Path, dst: Path, ctx: ConversionContext) -> list[Path]:
        """Convert ``src`` into ``dst`` and return the files that were created.

        Converters that produce several files name them after ``dst``
        (e.g. ``report_page001.png``) in the same folder.
        """
