"""PDF tools: merge, split and edit pages (rotate, delete, reorder).

All of these are lossless: pages are copied as they are (text, pictures, fonts, links,
form fields), never rendered or re-compressed. Bookmarks are kept where their pages are.
Results are first saved in a private temporary folder and only then moved to their
place, so a failure never leaves a half-written file. Originals are never changed and
existing files are never overwritten unless asked.
"""

from __future__ import annotations

import re
import shutil
import tempfile
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

import pymupdf

from .converters import ConversionError
from .converters.pdf import open_pdf, page_file_name
from .engine import TEMP_PREFIX, unique_path

ROTATIONS = (0, 90, 180, 270)
Progress = Callable[[float, str], None]


@dataclass(frozen=True)
class PageEdit:
    """One page of the result: which page of the original (0-based), turned by how much
    (clockwise, in steps of 90 degrees) on top of its current rotation."""

    index: int
    rotation: int = 0


def page_count(path: Path | str) -> int:
    with open_pdf(Path(path)) as doc:
        return doc.page_count


def _target(path: Path, overwrite: bool, protect: Iterable[Path] = ()) -> Path:
    """``path``, or a free name next to it. Never one of the originals."""
    protected = {p.resolve() for p in protect}
    if not overwrite or path.resolve() in protected:
        path = unique_path(path)
        while path.resolve() in protected:  # pragma: no cover - unique_path avoids them
            path = unique_path(path.with_stem(path.stem + " (1)"))
    return path


def _save(doc: pymupdf.Document, dst: Path) -> Path:
    """Save via a private temporary folder, then move into place."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=TEMP_PREFIX) as tmp:
        temp = Path(tmp) / "result.pdf"
        try:
            # garbage=3 drops unused objects; deflate only packs streams that were not
            # compressed at all, so pictures are not touched.
            doc.save(temp, garbage=3, deflate=True)
        except Exception as exc:
            raise ConversionError(f"Could not save the PDF: {exc}") from exc
        try:
            shutil.move(str(temp), dst)
        except OSError as exc:
            raise ConversionError(f"Could not save {dst.name}: {exc.strerror or exc}") from exc
    return dst


# --- merge -------------------------------------------------------------------------


def merge(
    sources: list[Path], dst: Path, *, overwrite: bool = False, progress: Progress | None = None
) -> Path:
    """Join several PDFs into one, in the given order. Bookmarks of each file are kept."""
    sources = [Path(s) for s in sources]
    if len(sources) < 2:
        raise ConversionError("Choose at least two PDFs to merge.")
    report = progress or (lambda f, m: None)
    out = pymupdf.open()
    toc: list[list] = []
    try:
        for i, src in enumerate(sources):
            report(i / len(sources), f"Adding {src.name}")
            with open_pdf(src) as doc:
                offset = out.page_count
                try:
                    out.insert_pdf(doc)
                except Exception as exc:
                    raise ConversionError(f"Could not add {src.name}: {exc}") from exc
                for level, title, page, *_ in doc.get_toc(simple=False):
                    toc.append([level, title, page + offset if page > 0 else page])
        if toc:
            try:
                out.set_toc(toc)
            except Exception:  # an odd bookmark tree: keep the pages, drop the bookmarks
                pass
        target = _target(Path(dst), overwrite, sources)
        report(0.95, "Saving")
        return _save(out, target)
    finally:
        out.close()


# --- split -------------------------------------------------------------------------

_RANGE = re.compile(r"^\s*(\d*)\s*(?:(-|–)\s*(\d*))?\s*$")


def parse_ranges(text: str, total: int) -> list[list[int]]:
    """Turn "1-3, 5, 8-" into page groups (0-based). Each comma part becomes one file.

    "8-" means "page 8 to the end", "-3" means "pages 1 to 3".
    """
    groups: list[list[int]] = []
    parts = [p for p in re.split(r"[,;]", text) if p.strip()]
    if not parts:
        raise ConversionError("Enter the pages to keep together, for example 1-3, 5.")
    for part in parts:
        match = _RANGE.match(part)
        if not match or not (match.group(1) or match.group(3)):
            raise ConversionError(f"“{part.strip()}” isn't a page range. Use for example 1-3, 5.")
        start = int(match.group(1)) if match.group(1) else 1
        if match.group(2):
            end = int(match.group(3)) if match.group(3) else total
        else:
            end = start
        if start < 1 or end > total or start > end:
            raise ConversionError(
                f"“{part.strip()}” doesn't fit: the PDF has {total} page"
                f"{'s' if total != 1 else ''}."
            )
        groups.append(list(range(start - 1, end)))
    return groups


def _group_name(stem: str, group: list[int]) -> str:
    first, last = group[0] + 1, group[-1] + 1
    return f"{stem} (page {first}).pdf" if first == last else f"{stem} (pages {first}-{last}).pdf"


def split_folder(src: Path, output_dir: Path | None = None) -> Path:
    """Where split pages go: a folder "<name>_pages" next to the PDF (or in output_dir)."""
    return (output_dir or src.parent) / f"{src.stem}_pages"


def split(
    src: Path,
    out_dir: Path,
    groups: list[list[int]] | None = None,
    *,
    overwrite: bool = False,
    progress: Progress | None = None,
) -> list[Path]:
    """Save parts of ``src`` as separate PDFs in ``out_dir``: one per page (``groups``
    None) or one per page group from :func:`parse_ranges`."""
    src = Path(src)
    report = progress or (lambda f, m: None)
    outputs = []
    with open_pdf(src) as doc:
        total = doc.page_count
        if groups is None:
            groups = [[i] for i in range(total)]
            names = [
                page_file_name(Path(f"{src.stem}.pdf"), i, max(total, 2)).name for i in range(total)
            ]
        else:
            names = [_group_name(src.stem, g) for g in groups]
        for n, (group, name) in enumerate(zip(groups, names, strict=True)):
            if not group or min(group) < 0 or max(group) >= total:
                raise ConversionError("Those pages aren't in this PDF.")
            report(n / len(groups), f"Saving {name}")
            part = pymupdf.open()
            try:
                for index in group:
                    part.insert_pdf(doc, from_page=index, to_page=index)
                outputs.append(_save(part, _target(out_dir / name, overwrite, [src])))
            finally:
                part.close()
    return outputs


# --- edit pages --------------------------------------------------------------------


def edited_path(src: Path, output_dir: Path | None = None) -> Path:
    return (output_dir or src.parent) / f"{src.stem} (edited).pdf"


def edit_pages(
    src: Path,
    dst: Path,
    pages: list[PageEdit],
    *,
    overwrite: bool = False,
) -> Path:
    """Save a copy of ``src`` with the pages in this order and rotation. Pages left out are
    deleted from the copy. The original stays as it is."""
    src = Path(src)
    if not pages:
        raise ConversionError("Keep at least one page.")
    with open_pdf(src) as doc:
        total = doc.page_count
        order = [p.index for p in pages]
        if min(order) < 0 or max(order) >= total:
            raise ConversionError("Those pages aren't in this PDF.")
        if len(set(order)) != len(order):
            raise ConversionError("A page can only appear once.")
        if any(p.rotation % 90 for p in pages):
            raise ConversionError("Pages can only be turned in steps of 90 degrees.")
        try:
            doc.select(order)  # keeps the page objects themselves: nothing is re-drawn
            for page, edit in zip(doc, pages, strict=True):
                if edit.rotation % 360:
                    page.set_rotation((page.rotation + edit.rotation) % 360)
        except Exception as exc:
            raise ConversionError(f"Could not change the pages: {exc}") from exc
        return _save(doc, _target(Path(dst), overwrite, [src]))


def thumbnails(src: Path, width: int = 120):
    """Small pictures of every page (for the page grid): yields ``(index, png_bytes)``.

    Shown with the page's current rotation, like a PDF viewer shows it.
    """
    with open_pdf(Path(src)) as doc:
        for page in doc:
            zoom = width / max(page.rect.width, 1)
            pixmap = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
            yield page.number, pixmap.tobytes("png")
