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
    assert "docx" not in ids  # PNG can't become Word
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
    assert file_list.drop_hint.isHidden() and not file_list.tree.isHidden()
    file_list.remove_rows([0])
    assert [p.name for p in file_list.files] == ["letter.pdf"]
    file_list.clear()
    assert file_list.count() == 0
    assert not file_list.drop_hint.isHidden() and file_list.tree.isHidden()


def test_file_list_cannot_change_while_busy(file_list, sample_png):
    file_list.add_files([sample_png])
    file_list.set_busy(True)
    assert not file_list.add_btn.isEnabled() and not file_list.remove_btn.isEnabled()
    file_list.remove_rows([0])
    file_list.clear()
    assert file_list.count() == 1
    file_list.set_busy(False)
    file_list.remove_rows([0])
    assert file_list.count() == 0


def test_file_list_status(file_list, sample_png):
    file_list.add_files([sample_png])
    file_list.set_status(0, "✓ logo.jpg", tooltip="/out/logo.jpg", output="/out/logo.jpg")
    assert file_list.status(0) == "✓ logo.jpg"
    assert file_list.status_tooltip(0) == "/out/logo.jpg"


def test_options_panel(qtbot):
    from azoth.gui.options_panel import OptionsPanel

    panel = OptionsPanel(word_installed=False, use_word=True)
    qtbot.addWidget(panel)
    assert panel.options() == {"level": "maximum", "keep_metadata": False}
    panel.set_level("compact")
    panel.set_level("no-such-level")  # ignored
    panel.metadata_check.setChecked(True)
    assert panel.options() == {"level": "compact", "keep_metadata": True}
    assert "82" in panel.level_hint.text()  # photo quality of "Smaller files"
    assert panel.word_check.isHidden()
    assert panel.use_word(saved=True) is True  # Word not installed: keep the saved choice


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
