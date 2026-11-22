"""PyInstaller entry point (absolute import so it works outside the package)."""

import multiprocessing
import sys

# Text recognition runs in a helper process (see azoth.ocr). In the packaged app that
# process starts this program again; freeze_support() lets it run the helper instead.
multiprocessing.freeze_support()

from azoth.__main__ import main  # noqa: E402

sys.exit(main())
