"""Write context_menu.iss: the Explorer right-click menu entries for the installer.

Run after changing conversions: ``python packaging/make_context_menu.py``.
A test (tests/test_context_menu.py) fails if the file is out of date.
"""

from pathlib import Path

from azoth.context_menu import iss_text

OUT = Path(__file__).with_name("context_menu.iss")

if __name__ == "__main__":
    OUT.write_text(iss_text(), encoding="utf-8", newline="\r\n")
    print(f"Wrote {OUT}")
