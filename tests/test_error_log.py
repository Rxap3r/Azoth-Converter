"""Error log: details of unexpected errors go to a local file, and the app keeps running."""

from __future__ import annotations

import faulthandler
import sys
import threading
from pathlib import Path

import pytest

pytest.importorskip("pytestqt")

from azoth.gui import error_log  # noqa: E402


@pytest.fixture
def log(monkeypatch, tmp_path):
    monkeypatch.setattr(error_log, "log_path", lambda: tmp_path / error_log.FILE_NAME)
    monkeypatch.setattr(error_log, "_show_message", lambda path: shown.append(path))
    shown = []
    yield tmp_path / error_log.FILE_NAME, shown
    # Back to pytest's own crash report, so a hard crash in a later test still shows where.
    faulthandler.enable(file=sys.__stderr__, all_threads=True)
    if error_log._crash_file is not None:
        error_log._crash_file.close()
        error_log._crash_file = None


def test_unexpected_error_is_logged_and_user_is_told(log, monkeypatch):
    path, shown = log
    monkeypatch.setattr(sys, "excepthook", sys.excepthook)
    monkeypatch.setattr(threading, "excepthook", threading.excepthook)
    error_log.install()
    assert sys.excepthook is error_log._excepthook
    assert faulthandler.is_enabled()  # hard crashes are written to the same file
    try:
        raise ValueError("broken picture")
    except ValueError:
        sys.excepthook(*sys.exc_info())
    text = path.read_text(encoding="utf-8")
    assert "Unexpected error" in text and "ValueError: broken picture" in text
    assert "Azoth Converter" in text
    assert shown == [path]


def test_errors_in_threads_are_logged(log, monkeypatch):
    path, _ = log
    monkeypatch.setattr(threading, "excepthook", error_log._thread_excepthook)
    t = threading.Thread(target=lambda: 1 / 0, name="worker")
    t.start()
    t.join()
    assert "ZeroDivisionError" in path.read_text(encoding="utf-8")


def test_log_stays_small(log, monkeypatch):
    path, _ = log
    monkeypatch.setattr(error_log, "MAX_BYTES", 2000)
    monkeypatch.setattr(error_log, "KEEP_BYTES", 1000)
    for i in range(50):
        error_log.write("Test", f"entry {i}")
    assert path.stat().st_size < 2500
    assert "entry 49" in path.read_text(encoding="utf-8")


def test_settings_button_opens_the_log(qtbot, log, monkeypatch):
    from azoth.gui import settings_page
    from azoth.gui.main_window import MainWindow

    path, _ = log
    window = MainWindow()
    qtbot.addWidget(window)
    page = window.settings_page
    page.update_log_button()
    assert not page.log_btn.isEnabled()  # no errors yet
    error_log.write("Test", "details")
    page.update_log_button()
    opened = []
    monkeypatch.setattr(settings_page.QDesktopServices, "openUrl", opened.append)
    page.log_btn.click()
    assert [Path(u.toLocalFile()) for u in opened] == [path]


def test_failed_conversion_is_logged(log, sample_png, monkeypatch):
    from azoth.engine import Engine
    from azoth.gui.worker import ConversionWorker

    path, _ = log

    def boom(*args, **kwargs):
        raise RuntimeError("decoder crashed")

    engine = Engine()
    monkeypatch.setattr(engine, "_run", boom)  # the step that converts each file
    worker = ConversionWorker(engine, [(0, sample_png, "jpg")], "jpg", None, {}, threading.Event())
    failed = []
    worker.file_failed.connect(lambda row, msg: failed.append(msg))
    worker.run()
    assert failed == ["Unexpected error: decoder crashed"]
    text = path.read_text(encoding="utf-8")
    assert "Converting a .png to jpg failed" in text and "RuntimeError: decoder crashed" in text
