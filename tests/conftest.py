from __future__ import annotations

import os
import socket
from pathlib import Path

import pymupdf
import pytest
from PIL import Image

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class NetworkAccessError(AssertionError):
    pass


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Fail any test whose code (in this Python process) tries to open a connection.

    This is how we verify the privacy promise: conversions never touch the network.
    """

    def guard(*args, **kwargs):
        raise NetworkAccessError(f"Network access attempted: {args!r}")

    monkeypatch.setattr(socket.socket, "connect", guard)
    monkeypatch.setattr(socket.socket, "connect_ex", guard)
    monkeypatch.setattr(socket, "create_connection", guard)
    monkeypatch.setattr(socket, "getaddrinfo", guard)


_real_connect = socket.socket.connect


@pytest.fixture
def local_sockets(monkeypatch):
    """Allow Unix sockets (a file on this computer, not the network) for tests of the
    Explorer menu's hand-over between programs (gui/explorer.py); network stays blocked."""

    def connect(sock, address):
        if sock.family != getattr(socket, "AF_UNIX", None):
            raise NetworkAccessError(f"Network access attempted: {address!r}")
        return _real_connect(sock, address)

    monkeypatch.setattr(socket.socket, "connect", connect)


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path_factory):
    """Keep the app's saved preferences in a temporary folder during tests."""
    try:
        from PySide6.QtCore import QSettings
    except ImportError:  # pragma: no cover
        yield
        return
    from azoth.gui.settings import configure_storage

    assert QSettings is not None
    configure_storage(tmp_path_factory.mktemp("settings"))
    yield


@pytest.fixture
def private_tmp(tmp_path, monkeypatch):
    """Point Python's temp folder somewhere we can inspect after a conversion."""
    import tempfile

    tdir = tmp_path / "system-temp"
    tdir.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(tdir))
    return tdir


def make_pdf(path: Path, pages: list[str]) -> Path:
    doc = pymupdf.open()
    for text in pages:
        page = doc.new_page()
        page.insert_text((72, 72), text, fontsize=14)
    doc.save(path)
    doc.close()
    return path


def make_scanned_pdf(path: Path, image: Path) -> Path:
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_image(page.rect, filename=str(image))
    doc.save(path)
    doc.close()
    return path


def make_docx(path: Path, title: str = "Quarterly Report") -> Path:
    import docx

    d = docx.Document()
    d.add_heading(title, 0)
    d.add_paragraph("Revenue grew steadily over the last quarter. " * 5)
    table = d.add_table(rows=2, cols=2)
    table.style = "Table Grid"
    for r in range(2):
        for c in range(2):
            table.cell(r, c).text = f"cell {r}{c}"
    d.save(path)
    return path


@pytest.fixture
def ocr_ready() -> None:
    """Text recognition tests need the language files (python packaging/fetch_tessdata.py).
    Skipped on a developer's machine without them, but they must run in the automatic
    build, so there a missing file is a failure."""
    from azoth import ocr

    if not set(ocr.LANGUAGES) <= set(ocr.available_languages()):
        message = "OCR language files missing: run python packaging/fetch_tessdata.py"
        if os.environ.get("CI"):
            pytest.fail(message)
        pytest.skip(message)


@pytest.fixture
def upscale_ready() -> None:
    """AI enlarging tests need the model (python packaging/fetch_tessdata.py fetches it
    too). Skipped on a developer's machine without it; a failure in the automatic build."""
    from azoth import upscale

    if not upscale.available():
        message = "AI model missing: run python packaging/fetch_tessdata.py"
        if os.environ.get("CI"):
            pytest.fail(message)
        pytest.skip(message)


def make_text_scan(path: Path, lines: list[str], *, dpi: int = 300) -> Path:
    """A picture of printed text, like a scan or a photo of a letter (PNG)."""
    doc = pymupdf.open()
    page = doc.new_page(width=500, height=300)
    for i, line in enumerate(lines):
        page.insert_text((40, 60 + 34 * i), line, fontsize=18)
    page.get_pixmap(dpi=dpi, colorspace=pymupdf.csGRAY).save(path)
    doc.close()
    return path


@pytest.fixture
def sample_png(tmp_path) -> Path:
    path = tmp_path / "logo.png"
    img = Image.new("RGBA", (120, 80), (0, 128, 255, 255))
    for x in range(40):
        for y in range(40):
            img.putpixel((x, y), (255, 0, 0, 0))  # transparent corner
    img.save(path)
    return path


@pytest.fixture
def sample_pdf(tmp_path) -> Path:
    return make_pdf(tmp_path / "letter.pdf", ["First page text", "Second page", "Third page"])


@pytest.fixture
def sample_docx(tmp_path) -> Path:
    return make_docx(tmp_path / "report.docx")
