"""Office files with Microsoft Word, Excel and PowerPoint, when they're installed
(Windows only): to PDF and between their own formats (e.g. DOC → DOCX, XLS → XLSX).

Office's own export gives an exact match of the layout and fonts. Office is controlled
through PowerShell (built into Windows), so no extra library is needed and Office runs in
a separate process that can be stopped if it hangs.

Safety, in the hidden Office program used for the conversion:

* macros are force-disabled (``AutomationSecurity = 3``),
* no dialogs are shown (``DisplayAlerts``); password-protected files are refused before
  Office sees them, and Word and Excel get a dummy password so they fail instead of asking,
* links and fields aren't updated, so nothing is fetched from elsewhere. Where these are
  saved preferences, the user's own values are restored afterwards,
* the file is opened read-only from a private copy and closed without saving,
* PowerPoint is a single program for all windows: if the user already has it open, it is
  left open (only the converted file is closed).

Nothing is uploaded: Office converts the file locally. If Office fails, the conversion
falls back to LibreOffice when it's installed.
"""

from __future__ import annotations

import base64
import os
import shutil
import subprocess
import sys
import time
import zipfile
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from .base import ConversionCancelled, ConversionContext, ConversionError, Converter, RetryAlone


@dataclass(frozen=True)
class OfficeApp:
    key: str
    """The name the script knows the program by."""
    prog_id: str
    label: str
    short: str
    sources: tuple[str, ...]
    save_codes: dict[str, int]
    """Target format → the program's own number for "save as" (PDF is exported)."""


WORD = OfficeApp(
    "word", "Word.Application", "Microsoft Word", "Word",
    ("docx", "doc", "odt", "rtf", "txt"),
    # wdFormatXMLDocument, wdFormatDocument, wdFormatOpenDocumentText, wdFormatRTF,
    # wdFormatEncodedText (saved as UTF-8)
    {"docx": 16, "doc": 0, "odt": 23, "rtf": 6, "txt": 7},
)  # fmt: skip
EXCEL = OfficeApp(
    "excel", "Excel.Application", "Microsoft Excel", "Excel",
    ("xlsx", "xls", "ods", "csv"),
    # xlOpenXMLWorkbook, xlExcel8, xlOpenDocumentSpreadsheet, xlCSVUTF8 (first sheet)
    {"xlsx": 51, "xls": 56, "ods": 60, "csv": 62},
)  # fmt: skip
POWERPOINT = OfficeApp(
    "powerpoint", "PowerPoint.Application", "Microsoft PowerPoint", "PowerPoint",
    ("pptx", "ppt", "odp"),
    # ppSaveAsOpenXMLPresentation, ppSaveAsPresentation, ppSaveAsOpenDocumentPresentation
    {"pptx": 24, "ppt": 1, "odp": 35},
)  # fmt: skip
APPS = (WORD, EXCEL, POWERPOINT)

DEFAULT_TIMEOUT = 180  # seconds per document

# Paths arrive in environment variables, never inside the script text, so file
# names with quotes or other special characters can't break or inject code.
POWERSHELL_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$kind = $env:AZOTH_APP
$app = $null
$saved = $null
$leaveOpen = $false
# One line per finished document ("ok 3" or "failed 3 <reason>"), so the app can show
# progress and knows which results are complete.
function Report([string]$line) {
    [System.IO.File]::AppendAllText($env:AZOTH_STATUS, $line + "`n")
}
# Calls a method with named options through COM's own call mechanism: PowerShell can't
# pass $true/$false to Office's "by reference" parameters directly (error: "True" of
# type "bool" can't be converted to "Object").
function Invoke-Named($target, [string]$method, [string[]]$names, [object[]]$values) {
    # The leading comma returns the object as it is (PowerShell would unpack collections).
    return ,$target.GetType().InvokeMember($method,
        [System.Reflection.BindingFlags]::InvokeMethod, $null, $target, $values,
        $null, $null, $names)
}
try {
    if ($kind -eq 'word') {
        $app = New-Object -ComObject Word.Application
        $app.Visible = $false
        $app.DisplayAlerts = 0          # wdAlertsNone: never show a dialog
        $app.AutomationSecurity = 3     # msoAutomationSecurityForceDisable: no macros
        $opts = $app.Options
        $saved = @($opts.UpdateLinksAtOpen, $opts.UpdateFieldsAtPrint, $opts.UpdateLinksAtPrint)
        $opts.UpdateLinksAtOpen = $false
        $opts.UpdateFieldsAtPrint = $false
        $opts.UpdateLinksAtPrint = $false
    } elseif ($kind -eq 'excel') {
        $app = New-Object -ComObject Excel.Application
        $app.Visible = $false
        $app.DisplayAlerts = $false
        $app.AutomationSecurity = 3
        $app.EnableEvents = $false
        $saved = @($app.AskToUpdateLinks)
        $app.AskToUpdateLinks = $false
    } elseif ($kind -eq 'powerpoint') {
        # One PowerPoint for all windows: if the user has it open, leave it open.
        $leaveOpen = $null -ne (Get-Process POWERPNT -ErrorAction SilentlyContinue)
        $app = New-Object -ComObject PowerPoint.Application
        $saved = @($app.DisplayAlerts, $app.AutomationSecurity)
        $app.DisplayAlerts = 1          # ppAlertsNone
        $app.AutomationSecurity = 3
    } else {
        throw "unknown program $kind"
    }
    $count = [int]$env:AZOTH_COUNT
    for ($i = 0; $i -lt $count; $i++) {
        $doc = $null
        try {
            $src = [Environment]::GetEnvironmentVariable("AZOTH_SRC_$i")
            $dst = [Environment]::GetEnvironmentVariable("AZOTH_DST_$i")
            $fmt = [Environment]::GetEnvironmentVariable("AZOTH_FMT_$i")
            if ($kind -eq 'word') {
                # A dummy password makes protected documents fail instead of prompting.
                $doc = Invoke-Named $app.Documents 'Open' @('FileName', 'ConfirmConversions',
                    'ReadOnly', 'AddToRecentFiles', 'PasswordDocument', 'Revert', 'Visible',
                    'OpenAndRepair', 'NoEncodingDialog') @($src, $false, $true, $false,
                    'azoth-no-password', $false, $false, $false, $true)
                if ($fmt -eq 'pdf') {
                    $doc.ExportAsFixedFormat($dst, 17)   # wdExportFormatPDF
                } else {
                    # Encoding 65001 = UTF-8 (used for plain text)
                    [void](Invoke-Named $doc 'SaveAs2' @('FileName', 'FileFormat', 'Encoding',
                        'AddToRecentFiles') @($dst, [int]$fmt, 65001, $false))
                }
                $doc.Close(0)                            # wdDoNotSaveChanges
            } elseif ($kind -eq 'excel') {
                # UpdateLinks 0: never; Local $false: CSV with commas, as everywhere else
                $doc = Invoke-Named $app.Workbooks 'Open' @('Filename', 'UpdateLinks',
                    'ReadOnly', 'Password', 'IgnoreReadOnlyRecommended', 'Notify',
                    'AddToMru', 'Local') @($src, 0, $true, 'azoth-no-password', $true,
                    $false, $false, $false)
                if ($fmt -eq 'pdf') {
                    $doc.ExportAsFixedFormat(0, $dst)    # xlTypePDF
                } else {
                    [void](Invoke-Named $doc 'SaveAs' @('Filename', 'FileFormat',
                        'AddToMru', 'Local') @($dst, [int]$fmt, $false, $false))
                }
                $doc.Close($false)
            } else {
                # ReadOnly, not Untitled, no window (msoTrue = -1, msoFalse = 0)
                $doc = $app.Presentations.Open($src, -1, 0, 0)
                if ($fmt -eq 'pdf') { $doc.SaveAs($dst, 32) }   # ppSaveAsPDF
                else { $doc.SaveAs($dst, [int]$fmt) }
                $doc.Close()
            }
            $doc = $null
            Report "ok $i"
        }
        catch {
            Report ("failed $i " + ($_.Exception.Message -replace '[\r\n]+', ' '))
        }
        finally {
            if ($doc -ne $null) {
                try {
                    if ($kind -eq 'word') { $doc.Close(0) }
                    elseif ($kind -eq 'excel') { $doc.Close($false) }
                    else { $doc.Close() }
                } catch {}
            }
        }
    }
}
catch {
    [Console]::Error.WriteLine($_.Exception.Message)
    exit 1
}
finally {
    if ($app -ne $null) {
        if ($kind -eq 'word') {
            if ($saved -ne $null) {
                $app.Options.UpdateLinksAtOpen = $saved[0]
                $app.Options.UpdateFieldsAtPrint = $saved[1]
                $app.Options.UpdateLinksAtPrint = $saved[2]
            }
            $app.Quit(0)
        } elseif ($kind -eq 'excel') {
            if ($saved -ne $null) { $app.AskToUpdateLinks = $saved[0] }
            $app.Quit()
        } else {
            if ($saved -ne $null) {
                $app.DisplayAlerts = $saved[0]
                $app.AutomationSecurity = $saved[1]
            }
            if (-not $leaveOpen -and $app.Presentations.Count -eq 0) { $app.Quit() }
        }
        [void][System.Runtime.InteropServices.Marshal]::ReleaseComObject($app)
    }
}
exit 0
"""


def encoded_script() -> str:
    """The script in the form ``powershell -EncodedCommand`` expects (UTF-16LE, base64)."""
    return base64.b64encode(POWERSHELL_SCRIPT.encode("utf-16-le")).decode("ascii")


def app_installed(app: OfficeApp) -> bool:
    """True if this Office program is registered on this Windows computer."""
    if sys.platform != "win32":
        return False
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, app.prog_id + r"\CLSID"):
            return True
    except OSError:
        return False


def word_installed() -> bool:
    return app_installed(WORD)


def office_installed() -> list[OfficeApp]:
    """The Office programs on this computer (Word, Excel, PowerPoint)."""
    return [app for app in APPS if app_installed(app)]


def password_protected(path: Path) -> bool:
    """True for a password-protected Word, Excel or PowerPoint file (DOCX, XLSX, PPTX …):
    those are not zip files but an encrypted container. Office would ask for the password
    in a window, so such files are refused before Office sees them."""
    try:
        with path.open("rb") as fh:
            head = fh.read(8)
            if head != b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" or zipfile.is_zipfile(path):
                return False
            fh.seek(0)
            data = fh.read(1 << 20)
    except OSError:
        return False
    # The encrypted container has a stream named "EncryptionInfo" (stored as UTF-16).
    return "EncryptionInfo".encode("utf-16-le") in data and path.suffix.lower() in (
        ".docx",
        ".xlsx",
        ".pptx",
    )


def _start_process(cmd: list[str], env: dict[str, str]) -> subprocess.Popen:
    """Start PowerShell hidden. A separate function so tests can replace it."""
    return subprocess.Popen(
        cmd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def find_powershell() -> str | None:
    root = os.environ.get("SystemRoot", r"C:\Windows")
    builtin = Path(root) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    if builtin.is_file():
        return str(builtin)
    return shutil.which("powershell") or shutil.which("pwsh")


class MsOfficeConverter(Converter):
    """One Office program (Word, Excel or PowerPoint) as a converter engine."""

    priority = 30  # preferred over LibreOffice for these conversions when enabled
    optional = True  # LibreOffice covers the same conversions

    def __init__(self, app: OfficeApp, enabled: bool = True, fallback: Converter | None = None):
        self.app = app
        self.id = "ms" + app.key
        self.label = app.label
        self.enabled = enabled
        self.fallback = fallback
        self._installed: bool | None = None

    def is_available(self) -> bool:
        if not self.enabled:
            return False
        if self._installed is None:
            self._installed = app_installed(self.app) and find_powershell() is not None
        return self._installed

    def unavailable_reason(self) -> str:
        return f"{self.app.label} is not installed. It is optional: it gives accurate results."

    def capabilities(self) -> Iterable[tuple[str, str]]:
        for src in self.app.sources:
            yield src, "pdf"
            for dst in self.app.save_codes:
                if dst != src:
                    yield src, dst

    def convert(self, src: Path, dst: Path, ctx: ConversionContext) -> list[Path]:
        try:
            return self._convert_one(src, dst, ctx)
        except ConversionCancelled:
            raise
        except ConversionError as exc:
            if getattr(exc, "final", False):
                raise
            if self.fallback is None or not self.fallback.is_available():
                raise
            short = self.app.short
            ctx.progress(0.5, f"{short} failed, using LibreOffice instead")
            try:
                produced = self.fallback.convert(src, dst, ctx)
            except ConversionError as fallback_exc:
                raise ConversionError(
                    f"{exc} LibreOffice also cannot convert the file. {fallback_exc}"
                ) from exc
            ctx.warnings.append(
                f"{short} failed, LibreOffice was used (the layout may differ slightly). {exc}"
            )
            return produced

    def batch_key(self, src: str, dst: str) -> tuple[str, str] | None:
        if src in self.app.sources and (dst == "pdf" or dst in self.app.save_codes):
            return (self.app.key, dst)
        return None

    def convert_batch(
        self, jobs: list[tuple[Path, Path]], ctx: ConversionContext
    ) -> list[ConversionError | None]:
        """One Office start for all ``jobs``. Files Office didn't finish are handed back to
        be tried on their own (and then with LibreOffice if Office fails again)."""
        ready = [(src, dst) for src, dst in jobs if not password_protected(src)]
        done, _, _ = self._run(ready, ctx) if ready else ({}, 0, b"")
        results: list[ConversionError | None] = []
        n = 0
        for src, dst in jobs:
            if password_protected(src):
                results.append(RetryAlone())  # alone, it gets the clear message
                continue
            local = self._local_out(ctx, n, dst)
            if done.get(n) == "ok" and local.exists():
                shutil.move(local, dst)
                results.append(None)
            else:
                results.append(RetryAlone())
            n += 1
        return results

    @staticmethod
    def _local_out(ctx: ConversionContext, n: int, dst: Path) -> Path:
        return ctx.work_dir / f"office-out{n}{dst.suffix.lower()}"

    def _convert_one(self, src: Path, dst: Path, ctx: ConversionContext) -> list[Path]:
        if password_protected(src):
            error = ConversionError(
                "This file has a password. Remove the password first in "
                f"{self.app.short} (File → Info → Protect). Then convert the file."
            )
            error.final = True  # LibreOffice can't open it either
            raise error
        done, returncode, stderr = self._run([(src, dst)], ctx)
        local = self._local_out(ctx, 0, dst)
        if done.get(0) != "ok" or not local.exists():
            if done.get(0, "ok") != "ok":
                detail = done[0]
            else:
                lines = [ln.strip() for ln in stderr.decode(errors="replace").splitlines()]
                detail = " ".join(ln for ln in lines if ln)[:400]
                if not detail and returncode:
                    detail = f"PowerShell stopped with exit code {returncode}"
            detail = f": {detail}" if detail else ""
            raise ConversionError(f"{self.app.label} cannot convert the file{detail}")
        shutil.move(local, dst)
        return [dst]

    def _run(
        self, jobs: list[tuple[Path, Path]], ctx: ConversionContext
    ) -> tuple[dict[int, str], int | None, bytes]:
        """Run the script for ``jobs``. Returns {file number: "ok" or the reason it
        failed}, PowerShell's exit code and its error output. Results are
        ``work_dir/office-out<n>.<ext>``."""
        powershell = find_powershell()
        if powershell is None:
            raise ConversionError(
                f"PowerShell is missing. Azoth Converter cannot use {self.app.short} without it."
            )

        # Office gets private copies with plain names; the originals are never opened.
        # Paths only travel in environment variables, never inside the script text.
        in_dir = ctx.work_dir / "office-in"
        in_dir.mkdir(parents=True, exist_ok=True)
        status = ctx.work_dir / "office-status.txt"
        env = dict(os.environ)
        env["AZOTH_APP"] = self.app.key
        env["AZOTH_COUNT"] = str(len(jobs))
        env["AZOTH_STATUS"] = str(status.resolve())
        for n, (src, dst) in enumerate(jobs):
            local_src = in_dir / f"input{n}{src.suffix.lower()}"
            shutil.copyfile(src, local_src)
            target = dst.suffix.lower().lstrip(".")
            target = {"jpeg": "jpg", "tif": "tiff"}.get(target, target)
            env[f"AZOTH_SRC_{n}"] = str(local_src.resolve())
            env[f"AZOTH_DST_{n}"] = str(self._local_out(ctx, n, dst).resolve())
            env[f"AZOTH_FMT_{n}"] = "pdf" if target == "pdf" else str(self.app.save_codes[target])
        cmd = [
            powershell,
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-EncodedCommand",
            encoded_script(),
        ]
        ctx.progress(0.1, f"Starting {self.app.label}")
        proc = _start_process(cmd, env)
        # The time limit is per document: it starts again whenever one is finished.
        timeout = float(ctx.option("timeout", DEFAULT_TIMEOUT))
        started = last_done = time.monotonic()
        done: dict[int, str] = {}
        try:
            while proc.poll() is None:
                if ctx.cancel_event.is_set():
                    proc.kill()
                    raise ConversionCancelled()
                now = time.monotonic()
                count = len(done)
                done = _read_status(status)
                if len(done) != count:
                    last_done = now
                if now - last_done > timeout:
                    proc.kill()
                    if len(jobs) == 1:
                        raise ConversionError(
                            f"{self.app.short} did not finish in {int(timeout)} seconds."
                        )
                    break
                part = len(done) + min(0.9, (now - started) / 30 if len(jobs) == 1 else 0.5)
                ctx.progress(0.1 + 0.8 * part / len(jobs), f"Converting with {self.app.label}")
                time.sleep(0.2)
        finally:
            if proc.poll() is None:
                proc.kill()
            _, stderr = proc.communicate()
        return _read_status(status), proc.returncode, stderr


class WordConverter(MsOfficeConverter):
    def __init__(self, enabled: bool = True, fallback: Converter | None = None) -> None:
        super().__init__(WORD, enabled, fallback)


def office_converters(enabled: bool, fallback: Converter | None) -> list[MsOfficeConverter]:
    """Word, Excel and PowerPoint as converters (each only used where it is installed)."""
    return [MsOfficeConverter(app, enabled, fallback) for app in APPS]


def _read_status(path: Path) -> dict[int, str]:
    """The script's status lines: {file number: "ok" or the reason it failed}."""
    try:
        lines = path.read_text(encoding="utf-8-sig", errors="replace").splitlines()
    except OSError:
        return {}
    done = {}
    for line in lines:
        word, _, rest = line.partition(" ")
        number, _, reason = rest.partition(" ")
        if word in ("ok", "failed") and number.isdigit():
            done[int(number)] = "ok" if word == "ok" else (reason.strip() or "unknown error")
    return done
