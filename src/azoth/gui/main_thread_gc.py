"""Python's memory clean-up (garbage collection) only on the main thread.

Normally Python cleans up whenever enough objects were made, in whatever thread that
happens. If that is a conversion thread and the clean-up frees a Qt object of the
window, Qt crashes ("access violation"). So the app switches the automatic clean-up off
and runs it from a timer in the main thread instead.
"""

from __future__ import annotations

import gc

from PySide6.QtCore import QObject, QTimer

INTERVAL_MS = 500


class MainThreadGC(QObject):
    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.threshold = gc.get_threshold()
        gc.disable()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.check)
        self.timer.start(INTERVAL_MS)

    def check(self) -> None:
        """Collect like Python would (same thresholds), but here in the main thread."""
        counts = gc.get_count()
        if counts[0] > self.threshold[0]:
            generation = 0
            if counts[1] > self.threshold[1]:
                generation = 2 if counts[2] > self.threshold[2] else 1
            gc.collect(generation)

    def stop(self) -> None:
        self.timer.stop()
        gc.enable()
