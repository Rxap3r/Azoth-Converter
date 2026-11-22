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

from .base import ConversionCancelled, ConversionContext, ConversionError, Converter, RetryAlone

WORD_SOURCES = ["docx", "doc", "odt", "rtf", "txt"]
DEFAULT_TIMEOUT = 180  # seconds per document

# Paths arrive in environment variables, never inside the script text, so file
# names with quotes or other special characters can't break or inject code.
POWERSHELL_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$word = $null
$saved = $null
$missing = [System.Reflection.Missing]::Value
# One line per finished document ("ok 3" or "failed 3 <reason>"), so the app can show
# progress and knows which results are complete.
function Report([string]$line) {
    [System.IO.File]::AppendAllText($env:AZOTH_STATUS, $line + "`n")
}
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
    $count = [int]$env:AZOTH_COUNT
    for ($i = 0; $i -lt $count; $i++) {
        $doc = $null
        try {
            $src = [Environment]::GetEnvironmentVariable("AZOTH_SRC_$i")
            $dst = [Environment]::GetEnvironmentVariable("AZOTH_DST_$i")
            # Open(FileName, ConfirmConversions, ReadOnly, AddToRecentFiles,
            #      PasswordDocument, PasswordTemplate, Revert, WritePasswordDocument,
            #      WritePasswordTemplate, Format, Encoding, Visible, OpenAndRepair,
            #      DocumentDirection, NoEncodingDialog)
            # A dummy password makes protected documents fail instead of prompting.
            $doc = $word.Documents.Open($src, $false, $true, $false,
                'azoth-no-password', $missing, $false, $missing, $missing, $missing,
                $missing, $false, $false, $missing, $true)
            $doc.ExportAsFixedFormat($dst, 17)   # wdExportFormatPDF
            $doc.Close(0)                        # wdDoNotSaveChanges
            $doc = $null
            Report "ok $i"
        }
        catch {
            Report ("failed $i " + ($_.Exception.Message -replace '[\r\n]+', ' '))
        }
        finally {
            if ($doc -ne $null) { try { $doc.Close(0) } catch {} }
        }
    }
}
catch {
    [Console]::Error.WriteLine($_.Exception.Message)
    exit 1
}
finally {
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
                produced = self.fallback.convert(src, dst, ctx)
            except ConversionError as fallback_exc:
                raise ConversionError(f"{exc} LibreOffice also failed: {fallback_exc}") from exc
            ctx.warnings.append(
                f"Word failed, LibreOffice was used (the layout may differ slightly). {exc}"
            )
            return produced

    def batch_key(self, src: str, dst: str) -> tuple[str, str] | None:
        return ("word", dst) if src in WORD_SOURCES and dst == "pdf" else None

    def convert_batch(
        self, jobs: list[tuple[Path, Path]], ctx: ConversionContext
    ) -> list[ConversionError | None]:
        """One Word start for all ``jobs``. Files Word didn't finish are handed back to be
        tried on their own (and then with LibreOffice if Word fails again)."""
        done, _, _ = self._run_word(jobs, ctx)
        results: list[ConversionError | None] = []
        for n, (_, dst) in enumerate(jobs):
            local = ctx.work_dir / f"word-out{n}.pdf"
            if done.get(n) == "ok" and local.exists():
                shutil.move(local, dst)
                results.append(None)
            else:
                results.append(RetryAlone())
        return results

    def _convert_with_word(self, src: Path, dst: Path, ctx: ConversionContext) -> list[Path]:
        done, returncode, stderr = self._run_word([(src, dst)], ctx)
        local = ctx.work_dir / "word-out0.pdf"
        if done.get(0) != "ok" or not local.exists():
            if done.get(0, "ok") != "ok":
                detail = done[0]
            else:
                lines = [ln.strip() for ln in stderr.decode(errors="replace").splitlines()]
                detail = " ".join(ln for ln in lines if ln)[:400]
                if not detail and returncode:
                    detail = f"PowerShell stopped with exit code {returncode}"
            detail = f": {detail}" if detail else ""
            raise ConversionError(f"Microsoft Word could not convert the file{detail}")
        shutil.move(local, dst)
        return [dst]

    def _run_word(
        self, jobs: list[tuple[Path, Path]], ctx: ConversionContext
    ) -> tuple[dict[int, str], int | None, bytes]:
        """Run the script for ``jobs``. Returns {file number: "ok" or the reason it
        failed}, PowerShell's exit code and its error output. Results are
        ``work_dir/word-out<n>.pdf``."""
        powershell = find_powershell()
        if powershell is None:
            raise ConversionError("PowerShell is missing, so Word can't be used.")

        # Word gets private copies with plain names; the originals are never opened.
        # Paths only travel in environment variables, never inside the script text.
        in_dir = ctx.work_dir / "word-in"
        in_dir.mkdir(parents=True, exist_ok=True)
        status = ctx.work_dir / "word-status.txt"
        env = dict(os.environ)
        env["AZOTH_COUNT"] = str(len(jobs))
        env["AZOTH_STATUS"] = str(status.resolve())
        for n, (src, _) in enumerate(jobs):
            local_src = in_dir / f"input{n}{src.suffix.lower()}"
            shutil.copyfile(src, local_src)
            env[f"AZOTH_SRC_{n}"] = str(local_src.resolve())
            env[f"AZOTH_DST_{n}"] = str((ctx.work_dir / f"word-out{n}.pdf").resolve())
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
                        raise ConversionError(f"Word didn't finish within {int(timeout)} s.")
                    break
                part = len(done) + min(0.9, (now - started) / 30 if len(jobs) == 1 else 0.5)
                ctx.progress(0.1 + 0.8 * part / len(jobs), "Converting with Microsoft Word")
                time.sleep(0.2)
        finally:
            if proc.poll() is None:
                proc.kill()
            _, stderr = proc.communicate()
        return _read_status(status), proc.returncode, stderr


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
