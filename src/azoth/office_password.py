"""Passwords on Word, Excel and PowerPoint files: add one, remove one, and open protected
files for converting.

Uses msoffcrypto-tool (MIT), which works offline and needs neither Microsoft Office nor
LibreOffice. New passwords use the same encryption as current Office (AES-256 with
SHA-512, "agile encryption"), so Word, Excel and PowerPoint open the files as usual.
Passwords can be added to DOCX, XLSX and PPTX; they can be removed from those and from
the older DOC, XLS and PPT.

Removing a password needs the file's own password: this is not a tool for opening other
people's files. Passwords are never stored; decrypted copies only ever exist in a job's
private temporary folder (or where the user saves the unlocked copy).
"""

from __future__ import annotations

import io
import shutil
import tempfile
from pathlib import Path

from . import formats
from .converters.base import ConversionError
from .engine import TEMP_PREFIX
from .pdf_tools import NEEDS_PASSWORD, UNLOCKED, _target, password_warning  # noqa: F401

CAN_LOCK = ("docx", "xlsx", "pptx")
CAN_UNLOCK = CAN_LOCK + ("doc", "xls", "ppt")
MAX_PASSWORD_CHARS = 255  # Office's limit


class PasswordNeeded(ConversionError):
    """A protected file was given without its password (or with a wrong one)."""


def file_kind(path: Path | str) -> str | None:
    """The format id (docx, xlsx …) if ``path`` is a Word, Excel or PowerPoint file this
    module can work with, else None."""
    fmt = formats.detect(Path(path))
    return fmt.id if fmt is not None and fmt.id in CAN_UNLOCK else None


def is_protected(path: Path | str) -> bool:
    """True if the Word, Excel or PowerPoint file needs a password to open."""
    if file_kind(path) is None:
        return False
    try:
        import msoffcrypto

        with open(path, "rb") as fh:
            return bool(msoffcrypto.OfficeFile(fh).is_encrypted())
    except Exception:  # noqa: BLE001 - not an Office file it understands: not protected
        return False


def lock_state(path: Path | str) -> str:
    return NEEDS_PASSWORD if is_protected(path) else UNLOCKED


def password_problem(password: str) -> str | None:
    """Why this password can't be used, or None."""
    if not password:
        return "Enter a password."
    if len(password) > MAX_PASSWORD_CHARS:
        return f"That password is too long (at most {MAX_PASSWORD_CHARS} characters)."
    if password != password.strip():
        return "The password cannot start or end with a space."
    return None


def protected_path(src: Path, output_dir: Path | None = None) -> Path:
    return (output_dir or src.parent) / f"{src.stem} (protected){src.suffix}"


def unlocked_path(src: Path, output_dir: Path | None = None) -> Path:
    return (output_dir or src.parent) / f"{src.stem} (unlocked){src.suffix}"


def decrypt(src: Path, password: str) -> bytes:
    """The unlocked file's bytes. Raises PasswordNeeded for a wrong password."""
    import msoffcrypto
    from msoffcrypto import exceptions

    if not password:
        raise PasswordNeeded(
            f"{Path(src).name} has a password. Enter the password to use the file."
        )
    out = io.BytesIO()
    try:
        with open(src, "rb") as fh:
            office = msoffcrypto.OfficeFile(fh)
            try:
                office.load_key(password=password, verify_password=True)
            except TypeError:  # formats whose key check is always on
                office.load_key(password=password)
            office.decrypt(out)
    except (exceptions.InvalidKeyError, exceptions.DecryptionError) as exc:
        raise PasswordNeeded(f"The password for {Path(src).name} is not correct.") from exc
    except exceptions.FileFormatError as exc:
        raise ConversionError(
            f"{Path(src).name} uses a type of password protection that Azoth Converter "
            "cannot open. Remove the password in Office first."
        ) from exc
    except OSError as exc:
        raise ConversionError(f"Cannot read {Path(src).name} ({exc}).") from exc
    except Exception as exc:  # noqa: BLE001 - damaged files raise many kinds of errors
        raise ConversionError(
            f"Cannot unlock {Path(src).name}. Possibly, the file is damaged."
        ) from exc
    data = out.getvalue()
    if not data:
        raise PasswordNeeded(f"The password for {Path(src).name} is not correct.")
    return data


def unlock_into(src: Path, folder: Path, password: str) -> Path:
    """Write an unlocked copy of ``src`` into ``folder`` (a job's private temporary
    folder) and return it. Used when converting protected files."""
    kind = file_kind(src)
    copy = folder / f"unlocked.{kind}"
    copy.write_bytes(decrypt(src, password))
    return copy


def add_password(src: Path, dst: Path, password: str, *, overwrite: bool = False) -> Path:
    """Save a copy of ``src`` that needs ``password`` to open. Nothing else changes."""
    import msoffcrypto
    from msoffcrypto.format.ooxml import OOXMLFile

    src = Path(src)
    problem = password_problem(password)
    if problem:
        raise ConversionError(problem)
    kind = file_kind(src)
    if kind not in CAN_LOCK:
        raise ConversionError(
            "You can add a password only to DOCX, XLSX and PPTX files. Convert DOC, "
            "XLS or PPT files to these formats first."
        )
    if is_protected(src):
        raise ConversionError("This file has a password. Remove that password first.")
    original = src.read_bytes()
    out = io.BytesIO()
    try:
        OOXMLFile(io.BytesIO(original)).encrypt(password, out)
    except Exception as exc:  # noqa: BLE001
        raise ConversionError(
            f"Cannot add a password to {src.name}. Possibly, the file is damaged."
        ) from exc
    locked = out.getvalue()
    # Check before saving: the copy must need the password and give back the exact file.
    check = msoffcrypto.OfficeFile(io.BytesIO(locked))
    if not check.is_encrypted():  # pragma: no cover - the library always encrypts
        raise ConversionError(
            "An error occurred during the save. Azoth Converter did not save a file."
        )
    unlocked = io.BytesIO()
    check.load_key(password=password, verify_password=True)
    check.decrypt(unlocked)
    if unlocked.getvalue() != original:  # pragma: no cover
        raise ConversionError(
            "An error occurred during the save. Azoth Converter did not save a file."
        )
    return _write(locked, _target(Path(dst), overwrite, [src]))


def remove_password(src: Path, dst: Path, password: str, *, overwrite: bool = False) -> Path:
    """Save an unlocked copy of ``src``. Needs the file's own password. The original
    stays locked."""
    src = Path(src)
    if file_kind(src) is None:
        raise ConversionError("This is not a Word, Excel or PowerPoint file.")
    if not is_protected(src):
        raise ConversionError("This file has no password.")
    if not password:
        raise ConversionError("Enter the password of the file.")
    data = decrypt(src, password)
    return _write(data, _target(Path(dst), overwrite, [src]))


def _write(data: bytes, dst: Path) -> Path:
    """Write via a private temporary file, then move into place (no half-written files)."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=TEMP_PREFIX) as tmp:
        temp = Path(tmp) / "result"
        temp.write_bytes(data)
        try:
            shutil.move(str(temp), dst)
        except OSError as exc:
            raise ConversionError(f"Cannot save {dst.name} ({exc.strerror or exc}).") from exc
    return dst
