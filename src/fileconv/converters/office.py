"""Office documents (Word, Excel, PowerPoint, OpenDocument) via LibreOffice.

LibreOffice runs headless as a separate process, with a throwaway user profile
for every job. The profile is hardened before LibreOffice starts:

* macros are disabled completely,
* links to external content are never updated when a document is loaded,
* untrusted remote images are blocked,
* the online update check is off.

So a document can't run code or contact a server while it's being converted.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from collections.abc import Iterable
from pathlib import Path

from .base import ConversionContext, ConversionError, Converter

TEXT_DOCS = ["docx", "doc", "odt", "rtf", "txt"]
SHEETS = ["xlsx", "xls", "ods", "csv"]
SLIDES = ["pptx", "ppt", "odp"]

# Maximum quality for PDF export: no downscaling or re-compression of images, so
# photos in a document end up in the PDF byte-for-byte unchanged.
PDF_QUALITY = (
    '{"ReduceImageResolution":{"type":"boolean","value":"false"},'
    '"UseLosslessCompression":{"type":"boolean","value":"true"},'
    '"Quality":{"type":"long","value":"100"}}'
)

# Targets per family, with the LibreOffice export filter to use.
FILTERS = {
    "text": {
        "pdf": f"pdf:writer_pdf_Export:{PDF_QUALITY}",
        "docx": "docx:MS Word 2007 XML",
        "odt": "odt:writer8",
        "rtf": "rtf:Rich Text Format",
        "txt": "txt:Text (encoded):UTF8",
        "doc": "doc:MS Word 97",
    },
    "sheet": {
        "pdf": f"pdf:calc_pdf_Export:{PDF_QUALITY}",
        "xlsx": "xlsx:Calc MS Excel 2007 XML",
        "ods": "ods:calc8",
        # 44 = comma separator, 34 = double quote, 76 = UTF-8
        "csv": "csv:Text - txt - csv (StarCalc):44,34,76",
        "xls": "xls:MS Excel 97",
    },
    "slides": {
        "pdf": f"pdf:impress_pdf_Export:{PDF_QUALITY}",
        "pptx": "pptx:Impress MS PowerPoint 2007 XML",
        "odp": "odp:impress8",
        "ppt": "ppt:MS PowerPoint 97",
    },
}
FAMILY = {
    **dict.fromkeys(TEXT_DOCS, "text"),
    **dict.fromkeys(SHEETS, "sheet"),
    **dict.fromkeys(SLIDES, "slides"),
}

DEFAULT_TIMEOUT = 300  # seconds per document

_UPDATE_CHECK = "/org.openoffice.Office.Jobs/Jobs/org.openoffice.Office.Jobs:Job['UpdateCheck']"
HARDENED_SETTINGS = [
    # (configuration path, property, value)
    ("/org.openoffice.Office.Common/Security/Scripting", "DisableMacrosExecution", "true"),
    ("/org.openoffice.Office.Common/Security/Scripting", "MacroSecurityLevel", "3"),
    ("/org.openoffice.Office.Common/Security/Scripting", "BlockUntrustedRefererLinks", "true"),
    ("/org.openoffice.Office.Writer/Content/Update", "Link", "0"),  # Writer: 0 = never
    ("/org.openoffice.Office.Calc/Content/Update", "Link", "1"),  # Calc: 1 = never
    (_UPDATE_CHECK + "/Arguments", "AutoCheckEnabled", "false"),
]


def hardened_profile_xml() -> str:
    items = "\n".join(
        f'<item oor:path="{path}"><prop oor:name="{name}" oor:op="fuse">'
        f"<value>{value}</value></prop></item>"
        for path, name, value in HARDENED_SETTINGS
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<oor:items xmlns:oor="http://openoffice.org/2001/registry" '
        'xmlns:xs="http://www.w3.org/2001/XMLSchema" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">\n'
        f"{items}\n</oor:items>\n"
    )


def _candidate_paths() -> list[Path]:
    candidates: list[Path] = []
    env = os.environ.get("FILECONV_SOFFICE")
    if env:
        candidates.append(Path(env))
    # A LibreOffice copy shipped next to the app (planned "Office pack").
    app_dir = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
    candidates.append(app_dir / "engines" / "libreoffice" / "program" / "soffice.exe")
    if sys.platform == "win32":
        for var in ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432"):
            base = os.environ.get(var)
            if base:
                candidates.append(Path(base) / "LibreOffice" / "program" / "soffice.exe")
    elif sys.platform == "darwin":
        candidates.append(Path("/Applications/LibreOffice.app/Contents/MacOS/soffice"))
    for name in ("soffice", "libreoffice"):
        found = shutil.which(name)
        if found:
            candidates.append(Path(found))
    return candidates


def find_soffice() -> Path | None:
    for path in _candidate_paths():
        if path.is_file():
            return path
    return None


class OfficeConverter(Converter):
    id = "libreoffice"
    label = "LibreOffice"
    priority = 10

    def __init__(self) -> None:
        self._soffice: Path | None = None
        self._looked = False

    @property
    def soffice(self) -> Path | None:
        if not self._looked:
            self._soffice = find_soffice()
            self._looked = True
        return self._soffice

    def is_available(self) -> bool:
        return self.soffice is not None

    def unavailable_reason(self) -> str:
        return (
            "Office conversions need LibreOffice (free). Install it from "
            "libreoffice.org, then restart File-Converter."
        )

    def capabilities(self) -> Iterable[tuple[str, str]]:
        for src, family in FAMILY.items():
            for dst in FILTERS[family]:
                if dst != src:
                    yield src, dst

    def final_only(self, src: str, dst: str) -> bool:
        # Text-only results lose the formatting, so never use them as a stepping stone.
        return dst in ("txt", "csv")

    def quality_note(self, src: str, dst: str) -> str | None:
        if dst == "txt":
            return "Only the text is kept; formatting and images are dropped."
        if dst == "csv":
            return "CSV keeps only the first sheet and no formatting."
        if src in ("docx", "doc", "xlsx", "xls", "pptx", "ppt") and dst in ("odt", "ods", "odp"):
            return "Complex Microsoft Office layouts may shift slightly."
        return None

    def convert(self, src: Path, dst: Path, ctx: ConversionContext) -> list[Path]:
        soffice = self.soffice
        if soffice is None:
            raise ConversionError(self.unavailable_reason())

        src_id = src.suffix.lower().lstrip(".")
        dst_id = dst.suffix.lower().lstrip(".")
        family = FAMILY.get(src_id)
        if family is None or dst_id not in FILTERS[family]:
            raise ConversionError(f"LibreOffice cannot convert {src_id} to {dst_id}")

        # Work on a copy with a plain name: avoids problems with unusual
        # characters and with files that are open in another program.
        in_dir = ctx.work_dir / "lo-in"
        out_dir = ctx.work_dir / "lo-out"
        profile = ctx.work_dir / "lo-profile"
        for d in (in_dir, out_dir, profile / "user"):
            d.mkdir(parents=True, exist_ok=True)
        (profile / "user" / "registrymodifications.xcu").write_text(
            hardened_profile_xml(), encoding="utf-8"
        )
        local_src = in_dir / f"input.{src_id}"
        shutil.copyfile(src, local_src)

        cmd = [
            str(soffice),
            f"-env:UserInstallation={profile.resolve().as_uri()}",
            "--headless",
            "--invisible",
            "--nologo",
            "--norestore",
            "--nolockcheck",
            "--nodefault",
            "--nofirststartwizard",
            "--convert-to",
            FILTERS[family][dst_id],
            "--outdir",
            str(out_dir),
            str(local_src),
        ]
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        ctx.progress(0.1, "Starting LibreOffice")
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            creationflags=creationflags,
        )
        timeout = float(ctx.option("timeout", DEFAULT_TIMEOUT))
        started = time.monotonic()
        try:
            while proc.poll() is None:
                if ctx.cancel_event.is_set():
                    proc.kill()
                    ctx.check_cancelled()
                if time.monotonic() - started > timeout:
                    proc.kill()
                    raise ConversionError(
                        f"LibreOffice took longer than {int(timeout)} s and was stopped"
                    )
                elapsed = time.monotonic() - started
                ctx.progress(min(0.9, 0.1 + elapsed / 60), "Converting with LibreOffice")
                time.sleep(0.2)
        finally:
            if proc.poll() is None:
                proc.kill()
            _, stderr = proc.communicate()

        produced = out_dir / f"input.{dst_id}"
        if proc.returncode != 0 or not produced.exists():
            detail = stderr.decode(errors="replace").strip().splitlines()
            hint = f": {detail[-1]}" if detail else ""
            raise ConversionError(f"LibreOffice could not convert the file{hint}")
        shutil.move(produced, dst)
        return [dst]
