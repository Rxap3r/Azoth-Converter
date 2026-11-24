import pytest

pytest.importorskip("pytestqt")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QLabel  # noqa: E402

from azoth.gui.main_window import MainWindow  # noqa: E402


@pytest.fixture
def window(qtbot):
    # Like the app (gui/app.py): memory clean-up only on the main thread, never in a
    # conversion thread, where freeing a Qt object crashes on Windows.
    from azoth.gui.main_thread_gc import MainThreadGC

    collector = MainThreadGC()
    w = MainWindow()
    qtbot.addWidget(w)
    yield w
    collector.stop()


def test_convert_files_from_window(window, qtbot, sample_png, sample_pdf, tmp_path):
    window.add_files([sample_png, sample_pdf])
    assert window.file_list.count() == 2

    # Only targets that work for both a PNG and a PDF are offered.
    targets = window.target_picker.ids()
    assert "jpg" in targets and "pdf" in targets
    assert "xlsx" not in targets  # neither can become Excel

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


def test_choose_file_name(window, qtbot, sample_png, sample_pdf, tmp_path):
    row = window.name_row
    assert not row.edit.isEnabled()
    window.add_files([sample_png])
    assert row.edit.isEnabled() and row.edit.text() == "logo"
    assert row.custom_name() is None  # unchanged: the original's name
    window.target_picker.select("webp")
    assert row.extension.text() == ".webp"
    row.edit.setText("Company logo")
    window.output_dir = tmp_path / "out"
    window.start_conversion()
    qtbot.waitUntil(lambda: window._thread is None, timeout=30000)
    assert [p.name for p in (tmp_path / "out").iterdir()] == ["Company logo.webp"]

    window.add_files([sample_pdf])  # several files: each keeps its own name
    assert not row.edit.isEnabled() and row.custom_name() is None
    assert row.edit.placeholderText() == row.MANY


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
    assert "Remove metadata" in chips("pdf") and "Remove metadata" in chips("docx")
    assert "Remove metadata" not in chips("xls")  # old Office formats: convert first


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
    assert "stays exactly the same" in window.notes_label.toolTip()  # the details on hover

    window.start_conversion()
    qtbot.waitUntil(lambda: window._thread is None, timeout=30000)
    assert (tmp_path / "holiday (clean).jpg").exists()
    assert (tmp_path / "logo (clean).png").exists()
    assert window.file_list.status(0) == "✓ holiday (clean).jpg"
    assert "Location (GPS)" in window.file_list.status_tooltip(0)
    assert b"SecretCamera" not in (tmp_path / "holiday (clean).jpg").read_bytes()


def test_remove_metadata_offered_only_if_every_file_supports_it(window, sample_png, tmp_path):
    from azoth.gui.targets import CLEAN_TARGET

    notes = tmp_path / "notes.txt"
    notes.write_text("plain text")
    window.add_files([sample_png, notes])
    assert CLEAN_TARGET not in _targets(window)


def test_change_size_only(window, qtbot, sample_png, tmp_path):
    from PIL import Image

    from azoth.gui.targets import CLEAN_TARGET, RESIZE_TARGET
    from azoth.resize import FIT, Resize

    photo = tmp_path / "holiday.jpg"
    Image.new("RGB", (400, 300), "red").save(photo)
    window.add_files([photo, sample_png])
    targets = _targets(window)
    assert targets[-2:] == [RESIZE_TARGET, CLEAN_TARGET]
    sizes = window.resize_options
    assert sizes.isHidden() or sizes.spec() is None  # nothing is resized by default

    assert window.target_picker.select(RESIZE_TARGET)
    assert not sizes.isHidden()
    assert sizes.spec() == Resize(FIT, width=1920, height=1080)  # Full HD ready to go
    sizes.set_mode(None)
    assert not window.convert_btn.isEnabled()  # no size chosen
    assert window.convert_btn.text() == "Choose a new size"
    sizes.set_mode("percent")
    assert sizes.preset.currentText() == "50 %"  # a ready-made size, not "Custom"
    assert window.convert_btn.isEnabled() and window.convert_btn.text() == "Resize 2 files"
    assert "(resized)" in window.notes_label.toolTip()  # the details on hover

    window.start_conversion()
    qtbot.waitUntil(lambda: window._thread is None, timeout=30000)
    with Image.open(tmp_path / "holiday (resized).jpg") as im:
        assert im.size == (200, 150)
    with Image.open(tmp_path / "logo (resized).png") as im:
        assert im.size == (60, 40) and im.mode == "RGBA"
    assert window.done_card.message.text() == "Done! 2 files resized."


def test_enhance_with_ai(window, qtbot, tmp_path, upscale_ready):
    from PIL import Image

    from azoth.gui.targets import RESIZE_TARGET
    from azoth.resize import PERCENT, Resize

    photo = tmp_path / "small.png"
    Image.new("RGB", (30, 20), "red").save(photo)
    window.add_files([photo])
    sizes = window.resize_options
    assert window.target_picker.select(RESIZE_TARGET)
    assert not sizes.ai.isChecked() and sizes.denoise.isHidden()  # never on by default
    sizes.set_mode(None)
    sizes.ai.setChecked(True)
    assert not sizes.denoise.isHidden() and sizes.denoise.currentData() == "medium"
    assert sizes.spec() == Resize(PERCENT, percent=100, ai=True)  # same size, better
    assert window.convert_btn.text() == "Enhance 1 file"
    assert "not for documents" in sizes.hint.text()  # the AI's caveat stays visible
    assert "isn't fully true to the original" in sizes.hint.toolTip()
    window.start_conversion()
    qtbot.waitUntil(lambda: window._thread is None, timeout=60000)
    with Image.open(tmp_path / "small (enhanced).png") as im:
        assert im.size == (30, 20)
    assert window.done_card.message.text() == "Done! 1 file enhanced."
    assert not sizes.best.isHidden() and not sizes.best.isChecked()  # never on by default
    sizes.best.setChecked(True)  # the big model has no noise levels: the choice goes
    assert sizes.denoise.isHidden() and sizes.spec().best
    sizes.best.setChecked(False)
    assert not sizes.denoise.isHidden() and not sizes.spec().best
    sizes.set_mode("percent")
    assert sizes.spec().ai and "bigger or keep their size" in sizes.hint.toolTip()
    sizes.ai.setChecked(False)
    assert sizes.denoise.isHidden() and sizes.best.isHidden() and not sizes.spec().ai


def test_size_while_converting(window, qtbot, sample_png, sample_pdf, tmp_path):
    from PIL import Image

    window.add_files([sample_png])
    window.output_dir = tmp_path / "out"
    assert window.target_picker.select("jpg")
    sizes = window.resize_options
    assert not sizes.isHidden() and sizes.spec() is None
    sizes.set_mode("width")
    assert sizes.width_box.isHidden()  # a ready-made size: no number to type
    sizes.set_custom(width=60)
    assert not sizes.width_box.isHidden()
    window.start_conversion()
    qtbot.waitUntil(lambda: window._thread is None, timeout=30000)
    with Image.open(tmp_path / "out" / "logo.jpg") as im:
        assert im.size == (60, 40)
    assert window.file_list.status(0) == "✓ logo.jpg · 60 × 40 px"

    assert window.target_picker.select("pdf")
    assert sizes.isHidden()  # a PDF page isn't resized
    window.add_files([sample_pdf])
    assert window.target_picker.select("png")
    assert sizes.isHidden()  # PDF pages use the quality's sharpness instead


def test_size_also_resizes_files_already_in_that_format(window, sample_png, tmp_path):
    from PIL import Image

    photo = tmp_path / "holiday.jpg"
    Image.new("RGB", (40, 30), "red").save(photo)
    window.add_files([photo, sample_png])
    assert window.target_picker.select("jpg")
    assert window.convert_btn.text() == "Convert 1 file to JPG"  # the JPG is skipped
    window.resize_options.set_mode("percent")
    assert window.convert_btn.text() == "Convert 2 files to JPG"  # … unless it gets a new size


def test_show_metadata_text(window, sample_pdf, tmp_path):
    photo = _photo_with_location(tmp_path / "holiday.jpg")
    window.add_files([photo, sample_pdf])
    text = window.file_list.metadata_text(0)
    assert "Location (GPS): 47.36944° N, 8.53333° E" in text
    assert "Camera: SecretCamera" in text
    assert "letter.pdf contains" in window.file_list.metadata_text(1) or "no metadata" in (
        window.file_list.metadata_text(1)
    )
    notes = tmp_path / "notes.txt"
    notes.write_text("plain text")
    window.add_files([notes])
    assert "photos and images" in window.file_list.metadata_text(2)


def test_metadata_button_on_photo_cards(window, monkeypatch, sample_pdf, tmp_path):
    from azoth.gui import file_list

    photo = _photo_with_location(tmp_path / "holiday.jpg")
    window.add_files([photo, sample_pdf])
    cards = window.file_list.cards
    assert not cards[0].metadata_btn.isHidden()  # a photo: the button is there
    assert cards[0].size.text().startswith("40 × 30 px · ")  # pixels shown for photos
    assert " px" not in cards[1].size.text()
    assert not cards[1].metadata_btn.isHidden()  # PDFs have metadata too
    shown = []
    monkeypatch.setattr(
        file_list.QMessageBox, "information", lambda parent, title, text: shown.append(text)
    )
    cards[0].metadata_btn.click()
    assert "Camera: SecretCamera" in shown[0]


def test_check_for_updates_only_opens_the_browser(window, monkeypatch):
    from azoth.gui import settings_page

    opened = []
    monkeypatch.setattr(settings_page.QDesktopServices, "openUrl", opened.append)
    window.settings_page.updates_btn.click()
    assert [u.toString() for u in opened] == [settings_page.RELEASES_URL]
    assert settings_page.RELEASES_URL.startswith("https://github.com/Rxap3r/Azoth-Converter/")


def test_metadata_setting_explains_what_is_removed(window):
    text = window.settings_page.metadata_check.toolTip()  # explained on hover
    assert not window.settings_page.metadata_check.isChecked()  # removed by default
    for word in ("GPS location", "date and time", "serial number", "preview", "Kept:"):
        assert word in text


def test_open_folder_only_for_one_folder_and_result_clears(window, qtbot, sample_png, tmp_path):
    import shutil

    def convert():
        assert window.target_picker.select("webp")
        window.start_conversion()
        qtbot.waitUntil(lambda: window._thread is None, timeout=30000)

    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()
    one = shutil.copy(sample_png, a / "one.png")
    two = shutil.copy(sample_png, b / "two.png")

    window.add_files([one])
    convert()
    card = window.done_card
    assert card.isVisibleTo(window) and card.message.text() == "Done! 1 file converted."
    assert card.folder_btn.isVisibleTo(window) and window.last_output == a
    assert card.file_btn.isVisibleTo(window) and card.file == a / "one.webp"

    window.add_files([two])  # list changed: the old result is cleared
    assert not card.isVisibleTo(window)
    assert not window.progress.isVisibleTo(window) and window.status_label.text() == ""

    convert()  # results in two folders: each file has its own "Show in folder" instead
    assert card.message.text() == "Done! 2 files converted."
    assert not card.folder_btn.isVisibleTo(window) and window.last_output is None
    assert not card.file_btn.isVisibleTo(window)  # several results: no single file to open

    window.file_list.remove_rows(range(window.file_list.count()))  # empty list
    assert not card.isVisibleTo(window) and not window.progress.isVisibleTo(window)


def test_uninstall_button_only_in_installed_app(qtbot, monkeypatch, tmp_path):
    import sys

    from azoth.gui import settings_page

    assert settings_page.uninstaller() is None  # run from source: nothing to uninstall
    exe = tmp_path / "AzothConverter.exe"
    exe.write_bytes(b"")
    (tmp_path / "unins000.exe").write_bytes(b"")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe))
    assert settings_page.uninstaller() == tmp_path / "unins000.exe"

    window = MainWindow()
    qtbot.addWidget(window)
    page = window.settings_page
    assert page.uninstall_btn.isVisibleTo(page)

    started, quit_called = [], []
    monkeypatch.setattr(
        settings_page.QProcess,
        "startDetached",
        lambda program, args: started.append(program) or True,
    )
    monkeypatch.setattr(settings_page.QApplication, "quit", lambda: quit_called.append(True))
    no, yes = (
        settings_page.QMessageBox.StandardButton.No,
        settings_page.QMessageBox.StandardButton.Yes,
    )
    monkeypatch.setattr(settings_page.QMessageBox, "question", lambda *a: no)
    page.uninstall_btn.click()
    assert started == [] and quit_called == []  # asked first; "No" does nothing
    monkeypatch.setattr(settings_page.QMessageBox, "question", lambda *a: yes)
    page.uninstall_btn.click()
    assert started == [str(tmp_path / "unins000.exe")] and quit_called == [True]


def test_no_uninstall_button_when_run_from_source(window):
    assert not window.settings_page.uninstall_btn.isVisibleTo(window.settings_page)


def test_done_messages():
    from azoth.gui.done_card import done_message

    assert done_message(1, 0, False) == "Done! 1 file converted."
    assert done_message(3, 0, False, cleaning=True) == "Done! Metadata removed from 3 files."
    assert done_message(2, 1, False).startswith("2 done, 1 failed.")
    assert done_message(0, 2, False).startswith("Nothing was saved: 2 files failed.")
    assert done_message(2, 0, True) == "Cancelled after 2 files."
    assert done_message(0, 0, True) == "Cancelled."


def test_notification_only_in_the_background(window, monkeypatch):
    from PySide6.QtWidgets import QSystemTrayIcon

    shown = []
    monkeypatch.setattr(QSystemTrayIcon, "isSystemTrayAvailable", staticmethod(lambda: True))
    monkeypatch.setattr(QSystemTrayIcon, "showMessage", lambda self, *a: shown.append(a[1]))
    notifier = window.notifier
    monkeypatch.setattr(window, "isActiveWindow", lambda: True)
    assert not notifier.notify("Done!") and not shown  # the user is looking at the app
    monkeypatch.setattr(window, "isActiveWindow", lambda: False)
    assert notifier.notify("Done! 2 files converted.") and shown == ["Done! 2 files converted."]
    window.settings_page.notify_check.setChecked(False)  # turned off in Settings
    assert not notifier.notify("Done!") and len(shown) == 1
    from azoth.gui.settings import Preferences

    assert Preferences().notify is False


def test_turn_pages_setting(window):
    from azoth.gui.settings import Preferences

    assert window.settings_page.turn_check.isChecked()  # on by default
    window.settings_page.turn_check.setChecked(False)
    assert Preferences().ocr_turn_pages is False


def test_no_page_squeezes_its_buttons(qtbot, tmp_path, sample_png):
    """In a window that is too low, every page scrolls instead of squeezing buttons and
    checkboxes (they would be cut off or overlap): each one is as tall as in a big window."""
    from PySide6.QtWidgets import QAbstractButton, QApplication

    from azoth.gui.main_window import MainWindow

    w = MainWindow()
    qtbot.addWidget(w)
    w.show()
    w.add_files([sample_png])  # the Convert page with its format tiles

    def heights(page: str) -> dict:
        w.show_page(page)
        QApplication.processEvents()
        return {
            id(b): (b.text(), b.height())
            for b in w.findChildren(QAbstractButton)
            if b.isVisible() and b.window() is w
        }

    for page in w.nav_buttons:
        w.resize(1600, 1400)
        roomy = heights(page)
        # Lower than the window allows: like larger text (Windows scaling) on a small screen.
        w.setMinimumSize(0, 0)
        w.resize(960, 420)
        small = heights(page)
        for key, (text, height) in small.items():
            if key in roomy:
                assert height >= roomy[key][1], (page, text, height, roomy[key][1])


def test_missing_libreoffice_offers_its_download_page(qtbot, monkeypatch, with_ffmpeg):
    from azoth.converters import office
    from azoth.gui import widgets

    monkeypatch.setattr(office, "find_soffice", lambda: None)
    opened = []
    monkeypatch.setattr(widgets.QDesktopServices, "openUrl", opened.append)
    w = MainWindow()
    qtbot.addWidget(w)
    [button] = w.convert_page.download_buttons
    assert button.text() == "Download LibreOffice…"
    button.click()
    w.formats_panel.download_btn.click()
    assert [u.toString() for u in opened] == [office.DOWNLOAD_URL] * 2
    assert office.DOWNLOAD_URL.startswith("https://www.libreoffice.org/")


def test_no_download_button_when_libreoffice_is_installed(with_ffmpeg, window):
    from azoth.converters.office import find_soffice

    if find_soffice() is None:
        pytest.skip("LibreOffice not installed")
    assert window.convert_page.download_buttons == []
    assert window.formats_panel.download_btn is None


def test_wrapped_text_is_never_drawn_over_buttons_with_larger_text(qtbot):
    """Windows' fonts and text scaling make text wider than here: wrapped text must still
    get all the height it needs (otherwise it's drawn over the buttons next to it)."""
    from PySide6.QtGui import QFont
    from PySide6.QtWidgets import QApplication

    w = MainWindow()
    qtbot.addWidget(w)
    w.resize(1000, 720)
    w.show()
    for size in (12, 14):
        for widget in w.findChildren(QLabel):
            font = QFont(widget.font())
            font.setPointSizeF(size)
            widget.setFont(font)
        for page in w.nav_buttons:
            w.show_page(page)
            QApplication.processEvents()
            QApplication.processEvents()
            for lbl in w.findChildren(QLabel):
                if lbl.isVisible() and lbl.wordWrap() and lbl.text():
                    needed = lbl.heightForWidth(lbl.width())
                    assert lbl.height() >= needed, (page, size, lbl.text()[:40])


def test_a_warning_is_shown_on_the_file_card(window, sample_png, tmp_path):
    window.add_files([sample_png])
    window._job_count = 1
    out = str(tmp_path / "photo.pdf")
    window._on_done(0, [out], ["⚠ Word failed, LibreOffice was used (the layout may differ).", "x"])
    card = window.file_list.cards[0]
    assert card.status.text() == "✓ photo.pdf  ⚠ Word failed, LibreOffice was used"
    assert "the layout may differ" in card.status.toolTip()


def test_ready_made_picture_sizes(qtbot):
    from azoth import resize
    from azoth.gui.options_panel import ResizeOptions

    panel = ResizeOptions()
    qtbot.addWidget(panel)
    assert panel.spec() is None and panel.preset.isHidden()
    modes = [panel.mode.itemData(i) for i in range(panel.mode.count())]
    assert resize.LONGEST not in modes  # "Screen size" covers it, simpler to choose
    assert not panel.only_shrink.isChecked()  # a chosen size is what you get
    panel.set_mode(resize.FIT)
    items = [panel.preset.itemText(i) for i in range(panel.preset.count())]
    assert items[2] == "3840 × 2160 (4K UHD)" and items[-1] == panel.CUSTOM
    assert panel.preset.currentText() == "1920 × 1080 (Full HD, 1080p)"  # not "Custom"
    panel.preset.setCurrentIndex(2)
    assert panel.spec() == resize.Resize(resize.FIT, width=3840, height=2160)
    panel.set_mode(resize.HEIGHT)
    assert panel.spec() == resize.Resize(resize.HEIGHT, width=1920, height=1080)
    panel.set_custom(height=777)
    assert panel.spec().height == 777 and not panel.height_box.isHidden()


def test_explorer_request_converts_right_away(window, qtbot, sample_png, tmp_path):
    out = tmp_path / "out"
    window.output_dir = out
    window.run_explorer_request("jpg", [sample_png])
    qtbot.waitUntil(lambda: not window.is_busy(), timeout=20000)
    assert [p.suffix for p in out.iterdir()] == [".jpg"]


def test_explorer_open_adds_to_the_files_already_there(window, sample_png, sample_pdf):
    window.add_files([sample_pdf])
    window.run_explorer_request("open", [sample_png])
    assert window.file_list.files == [sample_pdf, sample_png] and not window.is_busy()


def test_explorer_convert_starts_a_fresh_list(window, qtbot, sample_png, sample_pdf, tmp_path):
    window.add_files([sample_pdf])
    window.output_dir = tmp_path / "out"
    window.run_explorer_request("jpg", [sample_png])
    assert window.file_list.files == [sample_png]  # only what was chosen is converted
    qtbot.waitUntil(lambda: not window.is_busy(), timeout=20000)


def test_window_opened_normally_takes_right_click_files(
    qtbot, monkeypatch, tmp_path, local_sockets, sample_png
):
    """Started from the Start menu, the window still receives files chosen later in
    Explorer's right-click menu, instead of a second window opening."""
    from PySide6.QtWidgets import QApplication

    from azoth.gui import app, explorer, settings
    from azoth.gui.main_window import MainWindow

    storage = tmp_path / "settings"
    storage.mkdir()
    monkeypatch.setattr(explorer, "_storage", lambda: storage)
    monkeypatch.setattr(settings, "configure_storage", lambda *a: None)
    from azoth import engine
    from azoth.gui import error_log

    monkeypatch.setattr(engine, "cleanup_stale_temp_folders", lambda: None)
    monkeypatch.setattr(error_log, "install", lambda: None)
    from azoth.gui import main_window

    created, seen = [], []

    class Recorded(MainWindow):
        def __init__(self):
            super().__init__()
            created.append(self)

    monkeypatch.setattr(main_window, "MainWindow", Recorded)

    def run_instead_of_waiting(self):
        [window] = created
        qtbot.addWidget(window)
        assert explorer.forward("open", [str(sample_png)], storage)  # a right-click later
        qtbot.waitUntil(lambda: window.file_list.files == [sample_png], timeout=10000)
        seen.append(window)
        window.close()
        return 0

    monkeypatch.setattr(QApplication, "exec", run_instead_of_waiting)
    assert app.main() == 0
    assert seen


def test_no_stray_windows_flash_up(window, qtbot, sample_png, sample_pdf, tmp_path):
    """A widget shown before it has a place in the window is a window of its own: on
    Windows it flashes up as a small empty window. Only real windows may appear."""
    from PySide6.QtCore import QEvent, QObject
    from PySide6.QtWidgets import QApplication, QWidget

    shown = []

    class Spy(QObject):
        def eventFilter(self, obj, event):
            if event.type() == QEvent.Type.Show and isinstance(obj, QWidget) and obj.isWindow():
                shown.append(type(obj).__name__)
            return False

    spy = Spy()
    QApplication.instance().installEventFilter(spy)
    try:
        fresh = MainWindow()
        qtbot.addWidget(fresh)
        fresh.show()
        fresh.add_files([sample_png, sample_pdf])
        fresh.file_list.remove_rows([0])
        fresh.add_files([sample_png])
        for page in ("pdf", "settings", "convert"):
            fresh.show_page(page)
        fresh.output_dir = tmp_path / "out"
        fresh.run_explorer_request("open", [sample_pdf])
        fresh.run_explorer_request("png", [sample_pdf])
        qtbot.waitUntil(lambda: not fresh.is_busy(), timeout=20000)
        QApplication.processEvents()
    finally:
        QApplication.instance().removeEventFilter(spy)
    assert shown == ["MainWindow"]


def test_explorer_files_selected_together_are_one_batch(window, qtbot, tmp_path, local_sockets):
    from PIL import Image

    from azoth.gui import explorer

    storage = tmp_path / "settings"
    storage.mkdir()
    photos = []
    for n in range(3):
        photos.append(tmp_path / f"p{n}.png")
        Image.new("RGB", (8, 8), (n * 40, 0, 0)).save(photos[-1])
    out = tmp_path / "out"
    window.output_dir = out
    batches = []
    window.batch_finished.connect(lambda: batches.append(len(window.file_list.files)))
    listener = explorer.listen(storage)
    requests = explorer.attach(window, listener)
    try:
        requests.add("jpg", [str(photos[0])])
        for photo in photos[1:]:  # Explorer starts one program per selected file
            assert explorer.forward("jpg", [str(photo)], storage)
        qtbot.waitUntil(lambda: bool(batches), timeout=20000)
        assert batches == [3] and len(list(out.iterdir())) == 3
    finally:
        requests.close()


def test_only_the_most_useful_formats_show_at_first(window, sample_pdf):
    picker = window.target_picker
    window.add_files([sample_pdf])
    shown = [t.target for t in picker.tiles if not t.isHidden()]
    assert len(shown) == 6 and shown[0] == "docx"
    assert "More formats" in picker.more_btn.text()
    picker.more_btn.click()
    assert all(not t.isHidden() for t in picker.tiles)
    assert picker.select("doc")  # a rare one, behind "More formats"
    picker.more_btn.click()  # fold again
    from azoth.gui import targets

    choices = targets.choices(window.engine, window.file_list.formats)
    picker.set_choices(choices, keep=["doc"])  # e.g. remembered from last time
    assert picker.current() == "doc"
    assert not next(t for t in picker.tiles if t.target == "doc").isHidden()


def test_more_options_are_folded_with_a_summary(window, sample_png):
    more = window.convert_page.more
    window.add_files([sample_png])
    window.target_picker.select("jpg")
    assert not more.is_open() and more.content.isHidden()
    assert more.summary.text() == "Original size · Maximum quality"
    window.quality.set_level("high")
    assert more.summary.text() == "Original size · High quality"
    more.header.click()
    assert more.is_open() and window.prefs.options_open  # remembered for next time
    more.header.click()
    window.target_picker.select("resize")
    assert more.is_open()  # "Change size only": the size is chosen in there


def test_quality_only_where_it_changes_something(window, sample_png, sample_pdf):
    window.add_files([sample_pdf])
    window.target_picker.select("docx")
    assert window.quality.isHidden()  # PDF → Word: nothing to choose
    window.target_picker.select("png")
    assert not window.quality.isHidden()  # pages as pictures: sharpness
    window.file_list.clear()
    window.add_files([sample_png])
    window.target_picker.select("jpg")
    assert not window.quality.isHidden()


def test_notes_show_one_sentence_and_the_rest_on_hover():
    from azoth.gui.targets import first_sentence

    assert first_sentence("The layout is rebuilt. Simple ones work.") == "The layout is rebuilt."
    assert first_sentence("VAT is 8.1 % here. More") == "VAT is 8.1 % here."
    assert first_sentence("Removed: GPS, camera. Rest") == "Removed: GPS, camera."
    assert first_sentence("One sentence") == "One sentence"
