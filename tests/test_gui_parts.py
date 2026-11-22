"""The window's parts on their own: target logic (no Qt), file list, options, output folder."""

import pytest

from azoth import formats
from azoth.engine import Engine
from azoth.gui import targets

ENGINE = Engine()
F = formats.FORMATS


def test_targets_common_to_all_files():
    choices = targets.choices(ENGINE, [F["png"], F["pdf"]])
    ids = [f.id for f in choices.formats]
    assert "jpg" in ids and "pdf" in ids  # PDF is offered: the PDF itself is just skipped
    assert "xlsx" not in ids  # neither can become Excel
    assert not choices.can_clean  # PDFs have no photo metadata to remove


def test_targets_for_photos_offer_cleaning():
    choices = targets.choices(ENGINE, [F["jpg"], F["png"], None])  # None: unknown file
    assert choices.can_clean
    assert "jpg" in [f.id for f in choices.formats]


def test_targets_for_one_format_exclude_itself():
    ids = [f.id for f in targets.choices(ENGINE, [F["jpg"], F["jpg"]]).formats]
    assert "jpg" not in ids and "png" in ids


def test_no_files_no_targets():
    choices = targets.choices(ENGINE, [None])
    assert not choices and choices.formats == [] and not choices.can_clean


def test_source_formats_and_category():
    file_formats = [F["png"], None, F["jpg"], F["png"]]
    assert targets.source_formats(file_formats) == ["png", "jpg"]
    assert targets.single_category(file_formats) == "image"
    assert targets.single_category([F["png"], F["pdf"]]) is None


def test_notes():
    assert targets.notes(ENGINE, [F["jpg"]], targets.CLEAN_TARGET) == [targets.CLEAN_NOTE]
    assert any("256 colours" in n for n in targets.notes(ENGINE, [F["jpg"]], "gif"))
    assert targets.notes(ENGINE, [F["jpg"]], None) == []


# --- Qt widgets -------------------------------------------------------------------

pytest.importorskip("pytestqt")


@pytest.fixture
def file_list(qtbot):
    from azoth.gui.file_list import FileList

    widget = FileList()
    qtbot.addWidget(widget)
    return widget


def test_file_list_adds_folders_and_ignores_duplicates(file_list, qtbot, tmp_path, sample_png):
    folder = tmp_path / "more"
    folder.mkdir()
    (folder / "notes.txt").write_text("hello", encoding="utf-8")
    (folder / "nested").mkdir()  # sub-folders are not opened
    with qtbot.waitSignal(file_list.changed):
        file_list.add_files([sample_png, folder, sample_png, tmp_path / "missing.png"])
    assert [p.name for p in file_list.files] == ["logo.png", "notes.txt"]
    assert [f.id for f in file_list.formats] == ["png", "txt"]


def test_file_list_unknown_files_are_marked(file_list, tmp_path):
    odd = tmp_path / "data.xyz"
    odd.write_bytes(b"\x00\x01\x02")
    file_list.add_files([odd])
    assert file_list.formats == [None]
    assert file_list.status(0) == "Unknown file type, will be skipped"


def test_file_list_remove_and_clear(file_list, tmp_path, sample_png, sample_pdf):
    file_list.add_files([sample_png, sample_pdf])
    assert file_list.empty_label.isHidden()
    file_list.cards[0].remove_btn.click()  # the bin button on the card
    assert [p.name for p in file_list.files] == ["letter.pdf"]
    assert file_list.cards[0].remove_btn.accessibleName() == "Remove letter.pdf from the list"
    file_list.clear()
    assert file_list.count() == 0 and file_list.cards == []
    assert not file_list.empty_label.isHidden()
    assert not file_list.clear_btn.isEnabled()  # nothing to clear


def test_file_list_cannot_change_while_busy(file_list, sample_png):
    file_list.add_files([sample_png])
    file_list.set_busy(True)
    assert not file_list.add_btn.isEnabled()
    assert not file_list.cards[0].remove_btn.isEnabled()
    file_list.remove_rows([0])
    file_list.clear()
    assert file_list.count() == 1
    file_list.set_busy(False)
    file_list.remove_rows([0])
    assert file_list.count() == 0


def test_file_card_progress_and_done(file_list, sample_png, tmp_path):
    file_list.add_files([sample_png])
    card = file_list.cards[0]
    assert card.size.text().endswith(("KB", "bytes"))
    file_list.set_progress(0, 0.5, "Saving")
    assert card.progress.isVisibleTo(card) and card.progress.value() == 500
    assert file_list.status(0) == "50% Saving"
    file_list.set_status(0, "✓ logo.jpg", output=str(tmp_path / "logo.jpg"), state="done")
    assert not card.progress.isVisibleTo(card)
    assert card.open_btn.isVisibleTo(card) and card.folder_btn.isVisibleTo(card)
    file_list.set_status(0, "✗ broken", state="failed")
    assert not card.open_btn.isVisibleTo(card)


def test_human_size():
    from azoth.gui.file_list import human_size

    assert human_size(512) == "512 bytes"
    assert human_size(2048) == "2.0 KB"
    assert human_size(3 * 1024 * 1024) == "3.0 MB"


def test_file_list_status(file_list, sample_png):
    file_list.add_files([sample_png])
    file_list.set_status(0, "✓ logo.jpg", tooltip="/out/logo.jpg", output="/out/logo.jpg")
    assert file_list.status(0) == "✓ logo.jpg"
    assert file_list.status_tooltip(0) == "/out/logo.jpg"


def test_quality_selector(qtbot):
    from azoth.gui.options_panel import QualitySelector

    selector = QualitySelector()
    qtbot.addWidget(selector)
    assert selector.level() == "maximum"
    with qtbot.waitSignal(selector.level_changed):
        selector.set_level("compact")
    selector.set_level("no-such-level")  # ignored
    selector.set_level(None)  # nothing saved yet: ignored
    assert selector.level() == "compact"
    assert "Smallest files" in selector.hint.text()
    assert "82" not in selector.hint.text()  # plain words; the numbers are in the tooltip
    assert "82" in selector.hint.toolTip()  # photo quality of "Smaller files"
    selector.set_busy(True)
    assert not selector.buttons["high"].isEnabled()


def test_target_picker(qtbot):
    from azoth.gui.target_picker import TargetPicker

    picker = TargetPicker()
    qtbot.addWidget(picker)
    choices = targets.choices(ENGINE, [F["jpg"]])
    picker.set_choices(choices)
    assert picker.ids()[0] == "png" and picker.ids()[-1] == targets.CLEAN_TARGET
    assert picker.current() == "png"  # the most useful target is the default
    picker.set_choices(choices, keep=[None, "pdf"])  # keep a remembered choice
    assert picker.current() == "pdf"
    with qtbot.waitSignal(picker.changed) as signal:
        picker.tiles[2].click()
    assert signal.args == [picker.tiles[2].target]
    assert picker.select(targets.CLEAN_TARGET) and picker.current() == targets.CLEAN_TARGET
    assert not picker.select("xlsx")  # not offered for photos
    assert picker.tiles[0].accessibleName() == "PNG: Lossless"

    picker.set_choices(targets.choices(ENGINE, [F["pdf"]]))
    assert targets.CLEAN_TARGET not in picker.ids() and picker.current() == "docx"
    picker.set_choices(targets.choices(ENGINE, []))
    assert picker.ids() == [] and picker.current() is None


def test_settings_page(qtbot):
    from azoth.gui.settings_page import SettingsPage

    page = SettingsPage(word_installed=False, use_word=True, theme_choice="dark")
    qtbot.addWidget(page)
    assert page.theme_choice() == "dark"
    with qtbot.waitSignal(page.theme_changed) as signal:
        page.theme_buttons["light"].click()
    assert signal.args == ["light"]
    assert page.word_check.isHidden()
    assert page.use_word(saved=True) is True  # Word not installed: keep the saved choice


def test_output_folder_row(qtbot, tmp_path):
    from azoth.gui.output_folder import SAME_FOLDER, OutputFolderRow

    row = OutputFolderRow()
    qtbot.addWidget(row)
    assert row.folder is None and row.label.text() == SAME_FOLDER
    row.folder = tmp_path
    assert row.folder == tmp_path and row.label.text() == str(tmp_path)
    row.reset_btn.click()
    assert row.folder is None and row.label.text() == SAME_FOLDER
    row.set_busy(True)
    assert not row.choose_btn.isEnabled()


def test_ocr_choices_follow_the_files_and_target():
    assert targets.ocr_mode([F["jpg"]], "docx") == "always"
    assert targets.ocr_mode([F["pdf"]], "txt") == "always"  # used for scanned pages
    assert targets.ocr_mode([F["png"], F["heic"]], "pdf") == "optional"
    assert targets.ocr_mode([F["pdf"]], "png") is None
    assert targets.ocr_mode([F["docx"]], "pdf") is None
    assert targets.ocr_mode([], "pdf") is None


def test_ocr_options_panel(qtbot, ocr_ready):
    from azoth.gui.options_panel import OcrOptions
    from azoth.gui.settings import Preferences

    panel = OcrOptions()
    qtbot.addWidget(panel)
    panel.show()
    panel.set_mode(None)
    assert not panel.isVisible()
    panel.set_mode("always")
    assert panel.isVisible() and not panel.searchable.isVisible()
    assert panel.options()["ocr"] is True
    panel.language.set_language("ita")
    assert panel.options()["ocr_language"] == "ita"
    assert Preferences().ocr_language == "ita"  # remembered
    panel.set_mode("optional")
    assert panel.searchable.isVisible() and not panel.searchable.isChecked()
    assert panel.options()["ocr"] is False and not panel.language.isVisible()
    panel.searchable.setChecked(True)
    assert panel.options()["ocr"] is True and panel.language.isVisible()
    assert Preferences().ocr_searchable
