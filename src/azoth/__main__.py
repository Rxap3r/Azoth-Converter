"""Entry point for ``python -m azoth`` and the packaged Windows executable.

With no arguments the graphical app starts; with arguments the command-line
interface runs.
"""

import sys


def main() -> int:
    from azoth import portable

    portable.activate()  # portable version: data and temp files stay next to the program
    if len(sys.argv) > 1:
        from azoth.cli import main as cli_main

        return cli_main()
    from azoth.gui.app import main as gui_main

    return gui_main()


if __name__ == "__main__":
    sys.exit(main())
