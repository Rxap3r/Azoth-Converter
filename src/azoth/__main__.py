"""Entry point for ``python -m azoth`` and the packaged Windows programs.

With arguments the command-line interface runs. Without arguments the graphical app
starts, except in ``azoth-terminal.exe`` (the command-line program): there a short note
explains how to use it, so double-clicking it doesn't look like a second app.
"""

import sys
from pathlib import Path

TERMINAL_PROGRAM = "azoth-terminal"

TERMINAL_NOTE = """\
Azoth Converter - terminal version

This program is for typing commands, for example:

  azoth-terminal convert photo.jpg --to png
  azoth-terminal convert *.heic --to jpg --resize 1920x1080
  azoth-terminal --help        (everything it can do)

To use the normal app, open AzothConverter.exe instead.
"""


def is_terminal_program() -> bool:
    return getattr(sys, "frozen", False) and Path(sys.executable).stem.lower() == TERMINAL_PROGRAM


def _own_console_window() -> bool:
    """True if Windows opened a console window just for this program (double-click),
    rather than it being typed in an existing terminal."""
    if sys.platform != "win32":
        return False
    import ctypes

    processes = (ctypes.c_uint32 * 2)()
    return ctypes.windll.kernel32.GetConsoleProcessList(processes, 2) == 1


def show_terminal_note() -> int:
    print(TERMINAL_NOTE)
    if _own_console_window():  # else the window would close before it can be read
        input("Press Enter to close this window.")
    return 0


def main() -> int:
    from azoth import portable

    portable.activate()  # portable version: data and temp files stay next to the program
    if len(sys.argv) > 1:
        from azoth.cli import main as cli_main

        return cli_main()
    if is_terminal_program():
        return show_terminal_note()
    from azoth.gui.app import main as gui_main

    return gui_main()


if __name__ == "__main__":
    sys.exit(main())
