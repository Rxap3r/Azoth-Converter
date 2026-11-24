"""Entry point for ``python -m azoth`` and the packaged Windows programs.

With arguments the command-line interface runs, except ``--explorer <target> <files>``
(from the Explorer right-click menu), which opens the app. Without arguments the app
starts, except in ``azoth-terminal.exe`` (the command-line program): there a short note
explains how to use it, so double-clicking it doesn't look like a second app. When it was
double-clicked, a Command Prompt then opens in the same window, so commands can be typed.
"""

import os
import sys
from pathlib import Path

TERMINAL_PROGRAM = "azoth-terminal"
EXPLORER_FLAG = "--explorer"  # see gui/explorer.py and context_menu.py

TERMINAL_NOTE = """\
Azoth Converter - terminal version

This window is for commands, for example:

  azoth-terminal convert photo.jpg --to png
  azoth-terminal convert *.heic --to jpg --resize 1920x1080
  azoth-terminal --help        (help for all commands)

To use the usual app, open AzothConverter.exe.
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


TYPE_HERE_NOTE = """\
Type your commands below and press Enter. Type exit to close this window.
To type the full name of a file, drag the file into this window.
To go to a folder first, type cd and the name of the folder, for example: cd Downloads
"""


def _open_command_prompt() -> bool:
    """Turn the double-clicked window into a Command Prompt where ``azoth-terminal`` works:
    in the user's own folder (not the program folder, where nothing can be saved), with the
    program folder on PATH. Returns False if the Command Prompt could not be started."""
    import signal
    import subprocess

    program_dir = str(Path(sys.executable).parent)
    env = dict(os.environ)
    env["PATH"] = program_dir + os.pathsep + env.get("PATH", "")
    cmd = os.path.join(env.get("SystemRoot", r"C:\Windows"), "System32", "cmd.exe")
    # Ctrl+C is meant for the command running in the prompt, not for this waiting program
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    try:
        subprocess.call([cmd, "/k"], env=env, cwd=Path.home())
    except OSError:
        return False
    return True


def show_terminal_note() -> int:
    print(TERMINAL_NOTE)
    if _own_console_window():  # double-clicked: else the window closes at once
        print(TYPE_HERE_NOTE)
        if not _open_command_prompt():
            input("Press Enter to close this window.")
    return 0


def main() -> int:
    from azoth import portable

    portable.activate()  # portable version: data and temp files stay next to the program
    if len(sys.argv) > 2 and sys.argv[1] == EXPLORER_FLAG:
        from azoth.gui.app import main as gui_main

        return gui_main(explorer=(sys.argv[2], sys.argv[3:]))
    if len(sys.argv) > 1:
        from azoth.cli import main as cli_main

        return cli_main()
    if is_terminal_program():
        return show_terminal_note()
    from azoth.gui.app import main as gui_main

    return gui_main()


if __name__ == "__main__":
    sys.exit(main())
