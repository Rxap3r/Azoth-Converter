"""Word documents → PDF with Microsoft Word, when it's installed (Windows only).

Word's own PDF export gives an exact match of the layout and fonts. Word is
controlled through PowerShell (built into Windows), so no extra library is
needed and Word runs in a separate process that can be stopped if it hangs.

Safety, in the hidden Word instance used for the conversion:

* macros are force-disabled (``AutomationSecurity = 3``),
* no dialogs are shown (``DisplayAlerts = 0``); password-protected documents
  fail instead of asking for a password,
* links and fields aren't updated, so nothing is fetched from elsewhere.
  These are Word preferences; the user's own values are restored afterwards,
* the document is opened read-only from a private copy and closed without saving.

Nothing is uploaded: Word converts the file locally. If Word fails, the
conversion falls back to LibreOffice when it's installed.
"""

from __future__ import annotations

import base64
import os
import shutil
import subprocess
import sys
import time
from collections.abc import Iterable
from pathlib import Path

from .base import ConversionCancelled, ConversionContext, ConversionError, Converter

WORD_SOURCES = ["docx", "doc", "odt", "rtf", "txt"]
DEFAULT_TIMEOUT = 180  # seconds per document

# Paths arrive in environment variables, never inside the script text, so file
# names with quotes or other special characters can't break or inject code.
POWERSHELL_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$word = $null
$doc = $null
$saved = $null
$missing = [System.Reflection.Missing]::Value
try {
    $word = New-Object -ComObject Word.Application
    $word.Visible = $false
    $word.DisplayAlerts = 0          # wdAlertsNone: never show a dialog
    $word.AutomationSecurity = 3     # msoAutomationSecurityForceDisable: no macros
    $opts = $word.Options
    $saved = @($opts.UpdateLinksAtOpen, $opts.UpdateFieldsAtPrint, $opts.UpdateLinksAtPrint)
    $opts.UpdateLinksAtOpen = $false
    $opts.UpdateFieldsAtPrint = $false
    $opts.UpdateLinksAtPrint = $false
    # Open(FileName, ConfirmConversions, ReadOnly, AddToRecentFiles, PasswordDocument,
    #      PasswordTemplate, Revert, WritePasswordDocument, WritePasswordTemplate, Format,
    #      Encoding, Visible, OpenAndRepair, DocumentDirection, NoEncodingDialog)
    # A dummy password makes protected documents fail instead of prompting.
    $doc = $word.Documents.Open($env:FILECONV_SRC, $false, $true, $false,
        'fileconv-no-password', $missing, $false, $missing, $missing, $missing,
        $missing, $false, $false, $missing, $true)
    $doc.ExportAsFixedFormat($env:FILECONV_DST, 17)   # wdExportFormatPDF
}
catch {
    [Console]::Error.WriteLine($_.Exception.Message)
    exit 1
}
finally {
    if ($doc -ne $null) { $doc.Close(0) }             # wdDoNotSaveChanges
    if ($word -ne $null) {
        if ($saved -ne $null) {
            $word.Options.UpdateLinksAtOpen = $saved[0]
            $word.Options.UpdateFieldsAtPrint = $saved[1]
            $word.Options.UpdateLinksAtPrint = $saved[2]
        }
        $word.Quit(0)
        [void][System.Runtime.InteropServices.Marshal]::ReleaseComObject($word)
    }
}
exit 0
"""


def encoded_script() -> str:
    """The script in the form ``powershell -EncodedCommand`` expects (UTF-16LE, base64)."""
    return base64.b64encode(POWERSHELL_SCRIPT.encode("utf-16-le")).decode("ascii")


def word_installed() -> bool:
    """True if Microsoft Word is registered on this Windows computer."""
    if sys.platform != "win32":
        return False
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, r"Word.Application\CLSID"):
            return True
    except OSError:
        return False


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


class WordConverter(Converter):
    id = "msword"
    label = "Microsoft Word"
    priority = 30  # preferred over LibreOffice for these conversions when enabled
    optional = True  # LibreOffice covers the same conversions

    def __init__(self, enabled: bool = True, fallback: Converter | None = None) -> None:
        self.enabled = enabled
        self.fallback = fallback
        self._installed: bool | None = None

    def is_available(self) -> bool:
        if not self.enabled:
            return False
        if self._installed is None:
            self._installed = word_installed() and find_powershell() is not None
        return self._installed

    def unavailable_reason(self) -> str:
        return "Microsoft Word isn't installed (optional: used for exact Word → PDF results)."

    def capabilities(self) -> Iterable[tuple[str, str]]:
        for src in WORD_SOURCES:
            yield src, "pdf"

    def convert(self, src: Path, dst: Path, ctx: ConversionContext) -> list[Path]:
        try:
            return self._convert_with_word(src, dst, ctx)
        except ConversionCancelled:
            raise
        except ConversionError as exc:
            if self.fallback is None or not self.fallback.is_available():
                raise
            ctx.progress(0.5, "Word failed, using LibreOffice instead")
            try:
                return self.fallback.convert(src, dst, ctx)
            except ConversionError as fallback_exc:
                raise ConversionError(f"{exc} LibreOffice also failed: {fallback_exc}") from exc

    def _convert_with_word(self, src: Path, dst: Path, ctx: ConversionContext) -> list[Path]:
        powershell = find_powershell()
        if powershell is None:
            raise ConversionError("PowerShell is missing, so Word can't be used.")

        # Word gets a private copy with a plain name; the original is never opened.
        in_dir = ctx.work_dir / "word-in"
        in_dir.mkdir(parents=True, exist_ok=True)
        local_src = in_dir / f"input{src.suffix.lower()}"
        shutil.copyfile(src, local_src)
        local_dst = ctx.work_dir / "word-out.pdf"

        env = dict(os.environ)
        env["FILECONV_SRC"] = str(local_src.resolve())
        env["FILECONV_DST"] = str(local_dst.resolve())
        cmd = [
            powershell,
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-EncodedCommand",
            encoded_script(),
        ]
        ctx.progress(0.1, "Starting Microsoft Word")
        proc = _start_process(cmd, env)
        timeout = float(ctx.option("timeout", DEFAULT_TIMEOUT))
        started = time.monotonic()
        try:
            while proc.poll() is None:
                if ctx.cancel_event.is_set():
                    proc.kill()
                    raise ConversionCancelled()
                if time.monotonic() - started > timeout:
                    proc.kill()
                    raise ConversionError(f"Word didn't finish within {int(timeout)} s.")
                elapsed = time.monotonic() - started
                ctx.progress(min(0.9, 0.1 + elapsed / 30), "Converting with Microsoft Word")
                time.sleep(0.2)
        finally:
            if proc.poll() is None:
                proc.kill()
            _, stderr = proc.communicate()

        if proc.returncode != 0 or not local_dst.exists():
            lines = stderr.decode(errors="replace").strip().splitlines()
            detail = f": {lines[0]}" if lines else ""
            raise ConversionError(f"Microsoft Word could not convert the file{detail}")
        shutil.move(local_dst, dst)
        return [dst]
