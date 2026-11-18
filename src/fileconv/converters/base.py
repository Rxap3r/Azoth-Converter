"""The interface every converter plugin implements."""

from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ProgressCallback = Callable[[float, str], None]


class ConversionError(Exception):
    """A conversion failed. The message is shown to the user, so keep it readable."""


class ConversionCancelled(ConversionError):
    def __init__(self) -> None:
        super().__init__("Conversion cancelled")


@dataclass
class ConversionContext:
    """Everything a converter may use while it runs."""

    work_dir: Path
    """Private temporary folder for this job. It is deleted when the job ends."""
    options: dict[str, Any] = field(default_factory=dict)
    progress: ProgressCallback = lambda fraction, message: None
    cancel_event: threading.Event = field(default_factory=threading.Event)

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
    """When two converters offer the same conversion, the higher priority wins."""

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

    def quality_note(self, src: str, dst: str) -> str | None:
        """A short warning shown to the user when a conversion may lose information."""
        return None

    @abstractmethod
    def convert(self, src: Path, dst: Path, ctx: ConversionContext) -> list[Path]:
        """Convert ``src`` into ``dst`` and return the files that were created.

        Converters that produce several files name them after ``dst``
        (e.g. ``report_page001.png``) in the same folder.
        """
