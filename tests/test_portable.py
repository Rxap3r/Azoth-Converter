"""Portable version: with portable.txt next to the program, everything stays in its folder."""

import os
import tempfile

import pytest

from azoth import portable
from azoth.engine import Engine


@pytest.fixture
def program(tmp_path, monkeypatch):
    """A fake program folder; restores the temp settings that activate() changes."""
    folder = tmp_path / "USB stick" / "AzothConverter"
    folder.mkdir(parents=True)
    monkeypatch.setenv("AZOTH_PROGRAM_DIR", str(folder))
    monkeypatch.setattr(tempfile, "tempdir", tempfile.tempdir)
    for name in ("TMP", "TEMP", "TMPDIR"):
        if name in os.environ:
            monkeypatch.setenv(name, os.environ[name])
        else:
            monkeypatch.delenv(name, raising=False)
    return folder


def test_not_portable_without_the_marker(program):
    assert portable.data_dir() is None and not portable.is_portable()
    assert portable.activate() is None
    assert not (program / "data").exists()


def test_not_portable_when_run_from_source(monkeypatch):
    monkeypatch.delenv("AZOTH_PROGRAM_DIR", raising=False)
    assert portable.program_dir() is None and portable.data_dir() is None


def test_portable_keeps_data_and_temp_files_next_to_the_program(program, sample_png):
    (program / portable.MARKER).write_text("portable")
    data = portable.activate()
    assert data == program / "data"
    temp = data / "temp"
    assert tempfile.gettempdir() == str(temp)
    assert os.environ["TEMP"] == os.environ["TMP"] == str(temp)  # helper programs too

    # A conversion uses the portable temp folder and cleans it up again.
    result = Engine().convert(sample_png, "jpg", program / "out")
    assert result.outputs[0].exists()
    assert temp.is_dir() and list(temp.iterdir()) == []


def test_portable_settings_and_error_log_stay_in_the_data_folder(program):
    from azoth.gui import error_log, settings

    (program / portable.MARKER).write_text("portable")
    assert settings.default_storage_dir() == program / "data"
    settings.configure_storage()
    try:
        prefs = settings.Preferences()
        assert not prefs.notify  # Windows would remember the app's notifications
        prefs.save_notify(True)
        assert prefs.notify
        assert (program / "data" / "settings.ini").is_file()
        assert error_log.log_path().parent == program / "data"
    finally:
        settings.configure_storage(program.parent / "test-settings")


def test_read_only_stick_still_converts(program, monkeypatch, sample_png):
    (program / portable.MARKER).write_text("portable")
    before = tempfile.gettempdir()

    def refuse(*args, **kwargs):
        raise PermissionError("read-only")

    monkeypatch.setattr(type(program), "mkdir", refuse)
    assert portable.activate() == program / "data"
    assert tempfile.gettempdir() == before  # the PC's temp folder, so it still works


def test_settings_page_in_portable_mode(program, qtbot):
    pytest.importorskip("pytestqt")
    from PySide6.QtWidgets import QLabel

    from azoth.gui.settings_page import SettingsPage

    (program / portable.MARKER).write_text("portable")
    page = SettingsPage(word_installed=False, use_word=False, theme_choice="system")
    qtbot.addWidget(page)
    texts = " ".join(label.text() for label in page.findChildren(QLabel))
    tips = " ".join(label.toolTip() for label in page.findChildren(QLabel))
    assert "portable" in texts and str(program / "data") in tips  # the folder on hover
    assert "Uninstall" not in texts  # nothing to uninstall: delete the folder
