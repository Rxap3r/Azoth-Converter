"""PyInstaller entry point (absolute import so it works outside the package)."""

import sys

from azoth.__main__ import main

sys.exit(main())
