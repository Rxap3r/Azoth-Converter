"""Entry point for ``python -m fileconv`` and the packaged Windows executable.

With no arguments the graphical app starts; with arguments the command-line
interface runs.
"""

import sys


def main() -> int:
    if len(sys.argv) > 1:
        from fileconv.cli import main as cli_main

        return cli_main()
    from fileconv.gui.app import main as gui_main

    return gui_main()


if __name__ == "__main__":
    sys.exit(main())
