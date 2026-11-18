"""Starts the graphical app."""

from __future__ import annotations

import sys


def main() -> int:
    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication

    from .main_window import MainWindow
    from .resources import icon_path
    from .settings import APPLICATION, ORGANIZATION

    if sys.platform == "win32":
        # Show our icon in the taskbar instead of Python's when run from source.
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("FileConverter.App")

    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName(APPLICATION)
    app.setOrganizationName(ORGANIZATION)
    app.setWindowIcon(QIcon(str(icon_path())))
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
