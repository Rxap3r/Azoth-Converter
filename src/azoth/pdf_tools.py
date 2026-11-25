"""PDF tools: merge, split, edit pages (rotate, delete, reorder), compress, passwords.

Merge, split, edit pages and passwords are lossless: pages are copied as they are (text,
pictures, fonts, links, form fields), never rendered or re-compressed. Bookmarks are kept
where their pages are. An owner's restrictions (no printing, no copying, ...) stay on every
copy made from a restricted PDF. Compress only shrinks pictures as far as the chosen level allows
(see ``quality.COMPRESS_LEVELS``).
Results are first saved in a private temporary folder and only then moved to their
place, so a failure never leaves a half-written file. Originals are never changed and
existing files are never overwritten unless asked.
"""

from __future__ import annotations

import re
import secrets
import shutil
import tempfile
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

import pymupdf

from . import quality
from .converters import ConversionError
from .converters.pdf import open_pdf, page_file_name
from .engine import TEMP_PREFIX, unique_path

_ALL_PERMISSIONS = (
    pymupdf.PDF_PERM_PRINT
    | pymupdf.PDF_PERM_MODIFY
    | pymupdf.PDF_PERM_COPY
    | pymupdf.PDF_PERM_ANNOTATE
    | pymupdf.PDF_PERM_FORM
    | pymupdf.PDF_PERM_ACCESSIBILITY
    | pymupdf.PDF_PERM_ASSEMBLE
    | pymupdf.PDF_PERM_PRINT_HQ
)
Progress = Callable[[float, str], None]


@dataclass(frozen=True)
class PageEdit:
    """One page of the result: which page of the original (0-based), turned by how much
    (clockwise, in steps of 90 degrees) on top of its current rotation."""

    index: int
    rotation: int = 0


def _restrictions(doc: pymupdf.Document) -> int | None:
    """What an owner password still allows in this PDF (``PDF_PERM_*`` flags), or None
    if nothing is restricted."""
    if not (doc.metadata or {}).get("encryption"):
        return None
    allowed = doc.permissions & _ALL_PERMISSIONS
    return None if allowed == _ALL_PERMISSIONS else allowed


def _locked_like(allowed: int | None) -> dict:
    """Save options that put the same restrictions on a new PDF. Nobody knows the
    original owner password here, so the copy gets a random one: the restrictions can
    only be lifted on the originals (Password → remove), not on the copy."""
    if allowed is None:
        return {}
    return {
        "encryption": pymupdf.PDF_ENCRYPT_AES_256,
        "owner_pw": secrets.token_urlsafe(24),  # 32 characters; MuPDF takes at most 40
        "user_pw": "",
        "permissions": allowed,
    }


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


def _save(
    doc: pymupdf.Document,
    dst: Path,
    *,
    compact: bool = False,
    smaller_than: int | None = None,
    check: Callable[[Path], None] | None = None,
    **options,
) -> Path:
    """Save via a private temporary folder, then move into place.

    ``compact`` packs the file structure tighter (lossless). With ``smaller_than``
    nothing is saved unless the result is smaller than that many bytes (raises
    :class:`NotSmaller`). ``check`` looks at the finished temporary file before it is
    moved into place and raises ConversionError if something is wrong.
    """
    if compact:
        # garbage=4 also merges duplicate objects; object streams pack the small
        # objects. Both are lossless and understood by every reader since PDF 1.5.
        options = {"garbage": 4, "use_objstms": 1, "deflate_images": True, **options}
    options = {"garbage": 3, "deflate": True, **options}
    dst.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=TEMP_PREFIX) as tmp:
        temp = Path(tmp) / "result.pdf"
        try:
            # deflate only packs streams that were not compressed at all, so pictures
            # are not touched.
            doc.save(temp, **options)
        except Exception as exc:
            raise ConversionError(f"Cannot save the PDF ({exc}).") from exc
        if smaller_than is not None and temp.stat().st_size >= smaller_than:
            raise NotSmaller(
                "Azoth Converter cannot make this PDF smaller. It did not save a file."
            )
        if check is not None:
            check(temp)
        try:
            shutil.move(str(temp), dst)
        except OSError as exc:
            raise ConversionError(f"Cannot save {dst.name} ({exc.strerror or exc}).") from exc
    return dst


class NotSmaller(ConversionError):
    """Compressing would not make the file smaller, so nothing was saved."""


def is_signed(path: Path | str) -> bool:
    """True if the PDF carries a digital signature (a new copy can't keep it valid)."""
    try:
        with pymupdf.open(Path(path), filetype="pdf") as doc:
            return not doc.needs_pass and doc.get_sigflags() > 0
    except Exception:
        return False


def _same_pages(expected: int) -> Callable[[Path], None]:
    def check(path: Path) -> None:
        try:
            with pymupdf.open(path, filetype="pdf") as doc:
                ok = doc.page_count == expected
        except Exception:
            ok = False
        if not ok:
            raise ConversionError(
                "An error occurred during the save. Azoth Converter did not save a file."
            )

    return check


# --- merge -------------------------------------------------------------------------


def merge(
    sources: list[Path], dst: Path, *, overwrite: bool = False, progress: Progress | None = None
) -> Path:
    """Join several PDFs into one, in the given order. Bookmarks of each file are kept.
    If any of them is restricted, the result allows only what every one of them allows."""
    sources = [Path(s) for s in sources]
    if len(sources) < 2:
        raise ConversionError("Select two or more PDFs to merge.")
    report = progress or (lambda f, m: None)
    out = pymupdf.open()
    toc: list[list] = []
    allowed: int | None = None
    try:
        for i, src in enumerate(sources):
            report(i / len(sources), f"Adding {src.name}")
            with open_pdf(src) as doc:
                limits = _restrictions(doc)
                if limits is not None:
                    allowed = limits if allowed is None else allowed & limits
                offset = out.page_count
                try:
                    out.insert_pdf(doc)
                except Exception as exc:
                    raise ConversionError(f"Cannot add {src.name} ({exc}).") from exc
                for level, title, page, *_ in doc.get_toc(simple=False):
                    toc.append([level, title, page + offset if page > 0 else page])
        if toc:
            try:
                out.set_toc(toc)
            except Exception:  # an odd bookmark tree: keep the pages, drop the bookmarks
                pass
        target = _target(Path(dst), overwrite, sources)
        report(0.95, "Saving")
        return _save(out, target, **_locked_like(allowed))
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
            raise ConversionError(f"“{part.strip()}” is not a page range. Use this format: 1-3, 5.")
        start = int(match.group(1)) if match.group(1) else 1
        if match.group(2):
            end = int(match.group(3)) if match.group(3) else total
        else:
            end = start
        if start < 1 or end > total or start > end:
            raise ConversionError(
                f"“{part.strip()}” is not in the PDF. The PDF has {total} page"
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
        restricted = _restrictions(doc) is not None
        for n, (group, name) in enumerate(zip(groups, names, strict=True)):
            if not group or min(group) < 0 or max(group) >= total:
                raise ConversionError("These pages are not in this PDF.")
            report(n / len(groups), f"Saving {name}")
            target = _target(out_dir / name, overwrite, [src])
            if restricted:
                outputs.append(_split_restricted(src, group, target))
                continue
            part = pymupdf.open()
            try:
                for index in group:
                    part.insert_pdf(doc, from_page=index, to_page=index)
                outputs.append(_save(part, target))
            finally:
                part.close()
    return outputs


def _split_restricted(src: Path, group: list[int], target: Path) -> Path:
    """One part of a restricted PDF: a copy of the whole file reduced to these pages, so it
    keeps the original lock (and the owner's own password still lifts it)."""
    with open_pdf(src) as doc:
        try:
            doc.select(group)
        except Exception as exc:
            raise ConversionError(f"Cannot copy the pages ({exc}).") from exc
        return _save(doc, target, encryption=pymupdf.PDF_ENCRYPT_KEEP)


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
        raise ConversionError("Keep one or more pages.")
    with open_pdf(src) as doc:
        total = doc.page_count
        order = [p.index for p in pages]
        if min(order) < 0 or max(order) >= total:
            raise ConversionError("These pages are not in this PDF.")
        if len(set(order)) != len(order):
            raise ConversionError("Use each page only one time.")
        if any(p.rotation % 90 for p in pages):
            raise ConversionError("Turn pages only in steps of 90 degrees.")
        try:
            doc.select(order)  # keeps the page objects themselves: nothing is re-drawn
            for page, edit in zip(doc, pages, strict=True):
                if edit.rotation % 360:
                    page.set_rotation((page.rotation + edit.rotation) % 360)
        except Exception as exc:
            raise ConversionError(f"Cannot change the pages ({exc}).") from exc
        # keeps an owner's restrictions (and their own password still lifts them)
        return _save(doc, _target(Path(dst), overwrite, [src]), encryption=pymupdf.PDF_ENCRYPT_KEEP)


# --- compress ----------------------------------------------------------------------


def size_text(size: int) -> str:
    """1234567 → "1.2 MB", 45000 → "45 KB"."""
    return f"{size / 1_000_000:.1f} MB" if size >= 100_000 else f"{max(1, round(size / 1000))} KB"


def compressed_path(src: Path, output_dir: Path | None = None) -> Path:
    return (output_dir or src.parent) / f"{src.stem} (compressed).pdf"


def _rewriter_options(level: quality.CompressLevel):
    """MuPDF settings: shrink pictures sharper than the threshold to the level's dpi.

    Black-and-white pictures (scanned text) are never touched: they are tiny already
    and reducing them makes text hard to read.
    """
    mupdf = pymupdf.mupdf
    opts = mupdf.PdfImageRewriterOptions()
    lossless_method = mupdf.FZ_RECOMPRESS_JPEG if level.photos_to_jpeg else mupdf.FZ_RECOMPRESS_SAME
    for colour in ("color", "gray"):
        for kind, method in (("lossy", mupdf.FZ_RECOMPRESS_JPEG), ("lossless", lossless_method)):
            prefix = f"{colour}_{kind}_image_"
            setattr(opts, prefix + "recompress_method", method)
            setattr(opts, prefix + "recompress_quality", str(level.image_quality))
            setattr(opts, prefix + "subsample_method", mupdf.FZ_SUBSAMPLE_AVERAGE)
            setattr(opts, prefix + "subsample_threshold", level.threshold_dpi)
            setattr(opts, prefix + "subsample_to", level.dpi)
    opts.recompress_when = mupdf.FZ_RECOMPRESS_WHEN_SMALLER
    return opts


def _draws(doc: pymupdf.Document) -> list[tuple[int, int, int]]:
    """Every picture drawn on every page, in drawing order: (xref, width, height)."""
    return [
        (info["xref"], info["width"], info["height"])
        for page in doc
        for info in page.get_image_info(xrefs=True)
    ]


def _keep_unshrunk_pictures(doc: pymupdf.Document, before: list, level) -> None:
    """MuPDF also re-saves pictures it did not make smaller in size (width × height). For
    JPG photos that only loses quality, so those get their original data back. Lossless
    pictures turned into JPG on purpose (Strong) stay converted.

    MuPDF writes changed pictures as new objects and keeps the drawing order, so the
    pictures before and after are matched one by one."""
    after = _draws(doc)
    if len(after) != len(before):  # pragma: no cover - MuPDF keeps every picture
        return
    restored = set()
    for (old, *old_size), (new, *new_size) in zip(before, after, strict=True):
        if old == new or new in restored or old <= 0 or new <= 0 or old_size != new_size:
            continue
        if level.photos_to_jpeg and not _is_jpeg(doc, old):
            continue
        doc.update_stream(new, doc.xref_stream_raw(old), compress=False)
        doc.update_object(new, doc.xref_object(old, compressed=True))
        restored.add(new)


def _is_jpeg(doc: pymupdf.Document, xref: int) -> bool:
    return "DCTDecode" in doc.xref_get_key(xref, "Filter")[1]


def compress(
    src: Path,
    dst: Path,
    level: str = quality.DEFAULT_COMPRESS.id,
    *,
    overwrite: bool = False,
) -> Path:
    """Save a smaller copy of ``src``. Text, fonts, links, bookmarks and form fields are
    kept as they are; only pictures are reduced, as far as ``level`` allows. Raises
    :class:`NotSmaller` (and saves nothing) unless the copy is at least 1 % smaller."""
    src = Path(src)
    chosen = quality.COMPRESS_BY_ID.get(level)
    if chosen is None:
        raise ConversionError(f"“{level}” is not a known compression level.")
    size = src.stat().st_size
    with open_pdf(src) as doc:
        if chosen.dpi:
            before = _draws(doc)
            try:
                doc.rewrite_images(options=_rewriter_options(chosen))
                _keep_unshrunk_pictures(doc, before, chosen)
            except ConversionError:
                raise
            except Exception as exc:
                raise ConversionError(
                    f"Cannot make the pictures in this PDF smaller ({exc})."
                ) from exc
        try:
            return _save(
                doc,
                _target(Path(dst), overwrite, [src]),
                compact=True,
                smaller_than=size - max(size // 100, 1),  # at least 1 % smaller
                check=_same_pages(doc.page_count),
                encryption=pymupdf.PDF_ENCRYPT_KEEP,  # an owner's restrictions stay
            )
        except NotSmaller:
            stronger = chosen is not quality.COMPRESS_LEVELS[-1]
            raise NotSmaller(
                "Azoth Converter cannot make this PDF smaller at this level. It did not "
                "save a file." + (" Try a stronger level." if stronger else "")
            ) from None


# --- passwords ---------------------------------------------------------------------

MAX_PASSWORD_BYTES = 127  # the PDF standard only uses the first 127 bytes
GOOD_PASSWORD_LENGTH = 12
UNLOCKED, NEEDS_PASSWORD, RESTRICTED = "unlocked", "needs password", "restricted"


def lock_state(path: Path | str) -> str:
    """UNLOCKED, NEEDS_PASSWORD (can't be opened without one) or RESTRICTED (opens, but an
    owner password limits printing, copying or changes)."""
    try:
        doc = pymupdf.open(Path(path), filetype="pdf")
    except Exception as exc:
        raise ConversionError(
            "Cannot open the PDF. The file is damaged, or it is not a correct PDF."
        ) from exc
    with doc:
        if doc.needs_pass:
            return NEEDS_PASSWORD
        if _restrictions(doc) is not None:
            return RESTRICTED
        return UNLOCKED


def password_problem(password: str) -> str | None:
    """Why this password can't be used, or None."""
    if not password:
        return "Enter a password."
    if len(password.encode("utf-8")) > MAX_PASSWORD_BYTES:
        return "That password is too long for a PDF (at most about 120 characters)."
    if password != password.strip():
        return "The password cannot start or end with a space."
    return None


def password_warning(password: str) -> str | None:
    """A gentle warning for passwords that are easy to guess, or None."""
    if password_problem(password):
        return None
    kinds = sum(
        any(test(c) for c in password)
        for test in (str.islower, str.isupper, str.isdigit, lambda c: not c.isalnum())
    )
    if len(password) < 8 or (len(password) < GOOD_PASSWORD_LENGTH and kinds < 3):
        return (
            "This password is easy to guess. Use at least 12 characters, "
            "or mix letters, numbers and symbols."
        )
    return None


def protected_path(src: Path, output_dir: Path | None = None) -> Path:
    return (output_dir or src.parent) / f"{src.stem} (protected).pdf"


def unlocked_path(src: Path, output_dir: Path | None = None) -> Path:
    return (output_dir or src.parent) / f"{src.stem} (unlocked).pdf"


def add_password(src: Path, dst: Path, password: str, *, overwrite: bool = False) -> Path:
    """Save a copy of ``src`` that needs ``password`` to open (AES-256, the strongest
    encryption in the PDF standard). Nothing else changes: whoever has the password can
    print, copy and edit as before. The password is not stored anywhere."""
    src = Path(src)
    problem = password_problem(password)
    if problem:
        raise ConversionError(problem)
    if lock_state(src) != UNLOCKED:
        raise ConversionError("This PDF has a password. Remove that password first.")
    with open_pdf(src) as doc:
        pages = doc.page_count

        def check(path: Path) -> None:
            _same_pages(pages)(path)
            with pymupdf.open(path, filetype="pdf") as locked:
                ok = locked.needs_pass and locked.authenticate(password) and not locked.is_encrypted
            if not ok:
                raise ConversionError(
                    "An error occurred during the save. Azoth Converter did not save a file."
                )

        return _save(
            doc,
            _target(Path(dst), overwrite, [src]),
            check=check,
            encryption=pymupdf.PDF_ENCRYPT_AES_256,
            user_pw=password,
            owner_pw=password,
            permissions=-1,  # everything allowed once it's open
        )


def remove_password(src: Path, dst: Path, password: str, *, overwrite: bool = False) -> Path:
    """Save an unlocked copy of ``src``. Needs the PDF's own password: this is not a tool
    for opening other people's files. The original stays locked."""
    src = Path(src)
    state = lock_state(src)
    if state == UNLOCKED:
        raise ConversionError("This PDF has no password.")
    if not password:
        raise ConversionError("Enter the password of the PDF.")
    doc = pymupdf.open(src, filetype="pdf")
    try:
        result = doc.authenticate(password)
        full_access = result & 4 or doc.permissions & _ALL_PERMISSIONS == _ALL_PERMISSIONS
        if not result or (state == RESTRICTED and not result & 4):
            raise ConversionError(
                "The password is not correct. Azoth Converter did not save a file."
            )
        if not full_access:
            raise ConversionError(
                "This password opens the PDF. But a second password (the owner password) "
                "limits printing or copying. Enter the owner password to remove the two "
                "passwords."
            )
        pages = doc.page_count

        def check(path: Path) -> None:
            _same_pages(pages)(path)
            if lock_state(path) != UNLOCKED:  # pragma: no cover - MuPDF always decrypts
                raise ConversionError(
                    "An error occurred during the save. Azoth Converter did not save a file."
                )

        return _save(
            doc,
            _target(Path(dst), overwrite, [src]),
            check=check,
            encryption=pymupdf.PDF_ENCRYPT_NONE,
        )
    finally:
        doc.close()


def thumbnails(src: Path, width: int = 120):
    """Small pictures of every page (for the page grid): yields ``(index, png_bytes)``.

    Shown with the page's current rotation, like a PDF viewer shows it.
    """
    with open_pdf(Path(src)) as doc:
        for page in doc:
            zoom = width / max(page.rect.width, 1)
            pixmap = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
            yield page.number, pixmap.tobytes("png")
