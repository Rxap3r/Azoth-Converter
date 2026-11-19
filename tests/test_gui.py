import pytest

pytest.importorskip("pytestqt")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QLabel  # noqa: E402

from azoth.gui.main_window import MainWindow  # noqa: E402


@pytest.fixture
def window(qtbot):
    w = MainWindow()
    qtbot.addWidget(w)
    return w


def test_convert_files_from_window(window, qtbot, sample_png, sample_pdf, tmp_path):
    window.add_files([sample_png, sample_pdf])
    assert window.file_list.count() == 2

    # Only targets that work for both a PNG and a PDF are offered.
    targets = window.target_picker.ids()
    assert "jpg" in targets and "pdf" in targets
    assert "docx" not in targets  # PNG can't become Word

    window.output_dir = tmp_path / "out"
    window.set_quality_level("compact")
    assert window.target_picker.select("jpg")
    window.start_conversion()
    qtbot.waitUntil(lambda: window._thread is None, timeout=30000)

    produced = sorted(p.name for p in (tmp_path / "out").iterdir())
    assert produced == [
        "letter_page001.jpg",
        "letter_page002.jpg",
        "letter_page003.jpg",
        "logo.jpg",
    ]
    assert window.file_list.status(0).startswith("✓")
    assert window.file_list.status(1) == "✓ 3 files"


def test_files_already_in_target_format_are_skipped(
    window, qtbot, sample_pdf, sample_png, tmp_path
):
    window.add_files([sample_png, sample_pdf])
    window.output_dir = tmp_path / "out"
    assert window.target_picker.select("pdf")
    window.start_conversion()
    qtbot.waitUntil(lambda: window._thread is None, timeout=30000)
    assert window.file_list.status(1) == "Skipped: already this format"
    assert (tmp_path / "out" / "logo.pdf").exists()


def test_duplicates_ignored(window, sample_png):
    window.add_files([sample_png, sample_png])
    assert window.file_list.count() == 1


def test_sidebar_pages(window, qtbot):
    assert window.current_page() == "convert"
    qtbot.mouseClick(window.nav_buttons["formats"], Qt.MouseButton.LeftButton)
    assert window.current_page() == "formats"
    assert window.nav_buttons["formats"].isChecked()
    qtbot.mouseClick(window.nav_buttons["settings"], Qt.MouseButton.LeftButton)
    assert window.current_page() == "settings"
    window.show_page("convert")
    assert window.nav_buttons["convert"].isChecked()


def test_supported_formats_page(window):
    window.show_page("formats")
    panel = window.formats_panel
    shown = panel.visible_formats()
    assert {"pdf", "docx", "jpg", "heic", "xlsx", "pptx"} <= set(shown)

    panel.search.setText("heic")  # formats that are HEIC or convert to HEIC
    shown = panel.visible_formats()
    assert "heic" in shown and "jpg" in shown
    assert "docx" not in shown

    panel.search.setText(".docx")
    assert "pdf" in panel.visible_formats()  # PDF converts to DOCX

    panel.search.setText("")
    panel.filter_buttons["image"].click()  # only photos and images
    shown = panel.visible_formats()
    assert "jpg" in shown and "pdf" not in shown and "docx" not in shown
    panel.search.setText("zzz")
    assert panel.visible_formats() == [] and not panel.no_match.isHidden()
    panel.search.setText("")
    panel.filter_buttons[None].click()  # All
    assert len(panel.visible_formats()) == len(panel.rows)


def test_photo_rows_offer_remove_metadata(window):
    rows = {r.format_id: r for r in window.formats_panel.rows}

    def chips(fmt):
        return [c.text() for c in rows[fmt].findChildren(QLabel) if c.property("role") == "chip"]

    assert "Remove metadata" in chips("jpg")
    assert "Remove metadata" not in chips("pdf")


def test_theme_setting(window):
    from azoth.gui import theme

    assert window.settings_page.theme_choice() == "system"  # follows Windows by default
    window.settings_page.theme_buttons["dark"].click()
    assert window.theme.colors.mode == "dark"
    assert window.prefs.theme == "dark"  # remembered
    window.settings_page.theme_buttons["light"].click()
    assert window.theme.colors.mode == "light"
    window.settings_page.theme_buttons["system"].click()
    assert window.theme.choice == "system"
    assert window.theme.colors.mode == window.theme.system_mode()
    assert theme.manager() is window.theme  # one theme for the whole app


def test_word_option_hidden_without_word(window):
    assert not window.engine.uses_word()
    assert window.settings_page.word_check.isHidden()


def test_preferences_are_remembered(qtbot, tmp_path, sample_png):
    first = MainWindow()
    qtbot.addWidget(first)
    first.add_files([sample_png])
    assert first.target_picker.select("webp")
    first.set_quality_level("high")
    first.settings_page.metadata_check.setChecked(True)
    first.output_dir = tmp_path / "out"
    first.start_conversion()  # remembers WebP as the choice for images
    qtbot.waitUntil(lambda: first._thread is None, timeout=30000)

    second = MainWindow()
    qtbot.addWidget(second)
    assert second.quality.level() == "high"
    assert second.settings_page.metadata_check.isChecked()
    assert second.output_dir == tmp_path / "out"
    second.add_files([sample_png])
    assert second.target_picker.current() == "webp"


def test_remembered_target_is_per_kind_of_file(qtbot, tmp_path, sample_png, sample_pdf):
    first = MainWindow()
    qtbot.addWidget(first)
    first.add_files([sample_png])
    assert first.target_picker.select("pdf")
    first.output_dir = tmp_path / "out"
    first.start_conversion()
    qtbot.waitUntil(lambda: first._thread is None, timeout=30000)

    second = MainWindow()
    qtbot.addWidget(second)
    second.add_files([sample_pdf])
    # The image choice (PDF) doesn't apply to PDFs; they start with Word.
    assert second.target_picker.current() == "docx"


def test_missing_output_folder_is_not_restored(qtbot, tmp_path):
    gone = tmp_path / "deleted-folder"
    gone.mkdir()
    first = MainWindow()
    qtbot.addWidget(first)
    first.output_dir = gone
    first.save_preferences()
    gone.rmdir()
    second = MainWindow()
    qtbot.addWidget(second)
    assert second.output_dir is None


def test_about_dialog(window):
    from azoth.gui.about import AboutDialog

    dialog = AboutDialog(window)
    names = [
        dialog.components.topLevelItem(i).text(0)
        for i in range(dialog.components.topLevelItemCount())
    ]
    assert "PyMuPDF / MuPDF" in names and "LibreOffice" in names
    assert "LibreOffice" in dialog.engines_label.text()
    dialog.close()


def test_everything_is_stored_in_one_folder(window, tmp_path):
    from PySide6.QtCore import QSettings

    from azoth.gui.settings import forget_file_dialog_history, storage_dir

    window.save_preferences()
    assert (storage_dir() / "settings.ini").exists()

    # Qt's file dialog remembers folders; that history goes to our folder and is erased.
    qt = QSettings(QSettings.Format.IniFormat, QSettings.Scope.UserScope, "QtProject")
    qt.setValue("FileDialog/lastVisited", "file:///C:/Users/someone/Secret")
    qt.setValue("FileDialog/history", ["file:///C:/Users/someone/Secret"])
    qt.sync()
    from pathlib import Path

    # Compare as paths: Qt writes "/" on Windows, Python "\\".
    assert Path(qt.fileName()).resolve().parent == storage_dir().resolve()
    forget_file_dialog_history()
    qt = QSettings(QSettings.Format.IniFormat, QSettings.Scope.UserScope, "QtProject")
    assert qt.value("FileDialog/lastVisited") is None
    assert qt.value("FileDialog/history") is None


def _photo_with_location(path):
    from PIL import Image

    exif = Image.Exif()
    exif[0x010F] = "SecretCamera"
    exif.get_ifd(0x8825).update({1: "N", 2: (47.0, 22.0, 10.0), 3: "E", 4: (8.0, 32.0, 0.0)})
    Image.new("RGB", (40, 30), "red").save(path, exif=exif)
    return path


def _targets(window):
    return window.target_picker.ids()


def test_remove_metadata_option(window, qtbot, sample_png, tmp_path):
    from azoth.gui.targets import CLEAN_TARGET

    photo = _photo_with_location(tmp_path / "holiday.jpg")
    window.add_files([photo, sample_png])
    targets = _targets(window)
    assert targets[-1] == CLEAN_TARGET  # offered last, after the real formats
    assert targets[0] != CLEAN_TARGET  # never the default

    assert window.target_picker.select(CLEAN_TARGET)
    assert (
        not window.settings_page.metadata_check.isEnabled()
    )  # "keep metadata" makes no sense here
    assert "stays exactly the same" in window.notes_label.text()

    window.start_conversion()
    qtbot.waitUntil(lambda: window._thread is None, timeout=30000)
    assert (tmp_path / "holiday (clean).jpg").exists()
    assert (tmp_path / "logo (clean).png").exists()
    assert window.file_list.status(0) == "✓ holiday (clean).jpg"
    assert "Location (GPS)" in window.file_list.status_tooltip(0)
    assert b"SecretCamera" not in (tmp_path / "holiday (clean).jpg").read_bytes()


def test_remove_metadata_not_offered_for_documents(window, sample_png, sample_pdf):
    from azoth.gui.targets import CLEAN_TARGET

    window.add_files([sample_png, sample_pdf])
    assert CLEAN_TARGET not in _targets(window)


def test_show_metadata_text(window, sample_pdf, tmp_path):
    photo = _photo_with_location(tmp_path / "holiday.jpg")
    window.add_files([photo, sample_pdf])
    text = window.file_list.metadata_text(0)
    assert "Location (GPS): 47.36944° N, 8.53333° E" in text
    assert "Camera: SecretCamera" in text
    assert "photos and images" in window.file_list.metadata_text(1)
