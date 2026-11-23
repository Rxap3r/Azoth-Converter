"""Download the text recognition (OCR) language files into src/azoth/resources/tessdata.

The files are the "best" models of the Tesseract project (Apache-2.0), pinned to one
commit and checked against their SHA-256, so every build ships exactly the same data.
They are not stored in git (37 MB). The app itself never downloads anything: this script
only runs on a developer's machine and in the automatic build, before tests and packaging.

    python packaging/fetch_tessdata.py
"""

from __future__ import annotations

import hashlib
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

COMMIT = "e12c65a915945e4c28e237a9b52bc4a8f39a0cec"  # tesseract-ocr/tessdata_best
URL = "https://raw.githubusercontent.com/tesseract-ocr/tessdata_best/{commit}/{name}"
FILES = {
    "eng.traineddata": "8280aed0782fe27257a68ea10fe7ef324ca0f8d85bd2fd145d1c2b560bcb66ba",
    "deu.traineddata": "8407331d6aa0229dc927685c01a7938fc5a641d1a9524f74838cdac599f0d06e",
    "fra.traineddata": "907743d98915c91a3906dfbf6e48b97598346698fe53aaa797e1a064ffcac913",
    "ita.traineddata": "8df9c89176fb93f56bf4b2d4ede04c01c1f31d4b7697fbd76cc336df700f3f38",
}
TARGET = Path(__file__).resolve().parent.parent / "src" / "azoth" / "resources" / "tessdata"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


ATTEMPTS = 5  # the download server sometimes answers "busy" (503) for a moment


def _download(url: str, path: Path) -> None:
    for attempt in range(1, ATTEMPTS + 1):
        try:
            urllib.request.urlretrieve(url, path)  # noqa: S310
            return
        except (urllib.error.URLError, OSError) as exc:
            if attempt == ATTEMPTS:
                raise
            wait = 5 * attempt
            print(f"  failed ({exc}), trying again in {wait} s")
            time.sleep(wait)


def main() -> int:
    TARGET.mkdir(parents=True, exist_ok=True)
    for name, expected in FILES.items():
        path = TARGET / name
        if path.exists() and _sha256(path) == expected:
            print(f"{name}: already there")
            continue
        temp = path.with_suffix(".part")
        print(f"{name}: downloading")
        _download(URL.format(commit=COMMIT, name=name), temp)
        actual = _sha256(temp)
        if actual != expected:
            temp.unlink()
            print(f"{name}: wrong checksum {actual}, expected {expected}", file=sys.stderr)
            return 1
        temp.replace(path)
    # The AI enlarging model is fetched here too, so the automatic build needs one step.
    import fetch_upscale_model

    return fetch_upscale_model.main()


if __name__ == "__main__":
    sys.exit(main())
