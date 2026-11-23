"""Starts the graphical app."""

from __future__ import annotations

import sys


def main(explorer: tuple[str, list[str]] | None = None) -> int:
    """``explorer``: (target, files) chosen in Explorer's right-click menu."""
    listener = None
    if explorer is not None:
        from .explorer import start
        from .settings import configure_storage

        configure_storage()
        try:
            listener = start(*explorer)
        except RuntimeError:
            listener = None  # no window answered and none could start: open our own
        else:
            if listener is None:
                return 0  # handed over to the window that is already open

    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication

    from ..engine import cleanup_stale_temp_folders
    from . import error_log
    from .main_thread_gc import MainThreadGC
    from .main_window import MainWindow
    from .resources import icon_path
    from .settings import APPLICATION, ORGANIZATION, configure_storage

    if sys.platform == "win32":
        # Show our icon in the taskbar instead of Python's when run from source.
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("AzothConverter.App")

    configure_storage()  # everything in one folder, removed by the uninstaller
    error_log.install()  # problems are written to a file there, never sent anywhere
    cleanup_stale_temp_folders()  # leftovers from a crash or forced shutdown
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName(APPLICATION)
    app.setOrganizationName(ORGANIZATION)
    app.setWindowIcon(QIcon(str(icon_path())))
    collector = MainThreadGC(app)  # memory clean-up never runs in a conversion thread
    window = MainWindow()
    window.show()
    if listener is not None:
        from .explorer import attach

        attach(window, listener).add(*explorer)  # the window keeps it
    elif explorer is not None:
        from pathlib import Path

        window.run_explorer_request(explorer[0], [Path(f) for f in explorer[1]])
    try:
        return app.exec()
    finally:
        collector.stop()


if __name__ == "__main__":
    sys.exit(main())
