"""Download FFmpeg for Windows into src/azoth/resources/ffmpeg (video and audio).

Gyan Doshi's "full" build (GPL-3.0, https://www.gyan.dev/ffmpeg/builds/), from the
GitHub release of one version, checked against its SHA-256 so every build ships the
same program. Only ffmpeg.exe and its licence are kept (not ffplay or ffprobe). It
isn't stored in git (211 MB). On Linux and macOS the system's ffmpeg is used, so
nothing is downloaded there. The app itself never downloads anything: this runs only
on a developer's machine and in the automatic build (called by fetch_tessdata.py).

    python packaging/fetch_ffmpeg.py
"""

from __future__ import annotations

import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetch_tessdata import _download, _sha256  # noqa: E402

VERSION = "8.0.1"
URL = f"https://github.com/GyanD/codexffmpeg/releases/download/{VERSION}/ffmpeg-{VERSION}-full_build.zip"
SHA256 = "467cde100a47ed4b03a897988aeb4a296890c1e2b2d2864204657d002bc5fb90"
TARGET = Path(__file__).resolve().parent.parent / "src" / "azoth" / "resources" / "ffmpeg"
EXE = TARGET / "ffmpeg.exe"
KEEP = {"bin/ffmpeg.exe": "ffmpeg.exe", "LICENSE": "LICENSE.txt"}
STAMP = TARGET / "version.txt"  # which download the files came from


def main(force: bool = False) -> int:
    if sys.platform != "win32" and not force:
        print("FFmpeg: not needed here (the system's ffmpeg is used)")
        return 0
    if EXE.is_file() and STAMP.is_file() and STAMP.read_text().strip() == SHA256:
        print("FFmpeg: already there")
        return 0
    TARGET.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        archive = Path(tmp) / "ffmpeg.zip"
        print(f"FFmpeg {VERSION}: downloading (about 230 MB)")
        _download(URL, archive)
        actual = _sha256(archive)
        if actual != SHA256:
            print(f"FFmpeg: wrong checksum {actual}, expected {SHA256}", file=sys.stderr)
            return 1
        with zipfile.ZipFile(archive) as zf:
            for member in zf.namelist():
                inner = member.split("/", 1)[-1]  # without "ffmpeg-8.0.1-full_build/"
                if inner in KEEP:
                    with zf.open(member) as src, (TARGET / KEEP[inner]).open("wb") as dst:
                        shutil.copyfileobj(src, dst)
    if not EXE.is_file():
        print("FFmpeg: ffmpeg.exe not found in the download", file=sys.stderr)
        return 1
    STAMP.write_text(SHA256 + "\n")
    print("FFmpeg: saved")
    return 0


if __name__ == "__main__":
    sys.exit(main(force="--force" in sys.argv))
