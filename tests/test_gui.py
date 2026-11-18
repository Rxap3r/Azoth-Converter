import pytest

pytest.importorskip("pytestqt")

from fileconv.gui.main_window import MainWindow  # noqa: E402


@pytest.fixture
def window(qtbot):
    w = MainWindow()
    qtbot.addWidget(w)
    return w


def test_convert_files_from_window(window, qtbot, sample_png, sample_pdf, tmp_path):
    window.add_files([sample_png, sample_pdf])
    assert window.tree.topLevelItemCount() == 2

    # Only targets that work for both a PNG and a PDF are offered.
    targets = [window.target_combo.itemData(i) for i in range(window.target_combo.count())]
    assert "jpg" in targets and "pdf" in targets
    assert "docx" not in targets  # PNG can't become Word

    window.output_dir = tmp_path / "out"
    window.set_quality_level("compact")
    window.target_combo.setCurrentIndex(targets.index("jpg"))
    window.start_conversion()
    qtbot.waitUntil(lambda: window._thread is None, timeout=30000)

    produced = sorted(p.name for p in (tmp_path / "out").iterdir())
    assert produced == [
        "letter_page001.jpg",
        "letter_page002.jpg",
        "letter_page003.jpg",
        "logo.jpg",
    ]
    assert window.tree.topLevelItem(0).text(2).startswith("✓")
    assert window.tree.topLevelItem(1).text(2) == "✓ 3 files"


def test_files_already_in_target_format_are_skipped(
    window, qtbot, sample_pdf, sample_png, tmp_path
):
    window.add_files([sample_png, sample_pdf])
    window.output_dir = tmp_path / "out"
    targets = [window.target_combo.itemData(i) for i in range(window.target_combo.count())]
    window.target_combo.setCurrentIndex(targets.index("pdf"))
    window.start_conversion()
    qtbot.waitUntil(lambda: window._thread is None, timeout=30000)
    assert window.tree.topLevelItem(1).text(2) == "Skipped: already this format"
    assert (tmp_path / "out" / "logo.pdf").exists()


def test_duplicates_ignored(window, sample_png):
    window.add_files([sample_png, sample_png])
    assert window.tree.topLevelItemCount() == 1


def test_supported_formats_section(window):
    section = window.formats_section
    assert not section.is_expanded()
    assert section.content.isHidden()

    section.toggle.click()  # open
    assert section.is_expanded()
    assert not section.content.isHidden()

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
    section.toggle.click()  # close again
    assert section.content.isHidden()


def test_options_section_collapsible(window):
    assert window.options_section.content.isHidden()
    window.options_section.set_expanded(True)
    assert not window.options_section.content.isHidden()


def test_word_option_hidden_without_word(window):
    assert not window.engine.uses_word()
    assert window.word_check.isHidden()


def test_preferences_are_remembered(qtbot, tmp_path, sample_png):
    first = MainWindow()
    qtbot.addWidget(first)
    first.add_files([sample_png])
    first.target_combo.setCurrentIndex(first.target_combo.findData("webp"))
    first.set_quality_level("high")
    first.metadata_check.setChecked(True)
    first.output_dir = tmp_path / "out"
    first.start_conversion()  # remembers WebP as the choice for images
    qtbot.waitUntil(lambda: first._thread is None, timeout=30000)

    second = MainWindow()
    qtbot.addWidget(second)
    assert second.level_combo.currentData() == "high"
    assert second.metadata_check.isChecked()
    assert second.output_dir == tmp_path / "out"
    second.add_files([sample_png])
    assert second.target_combo.currentData() == "webp"


def test_remembered_target_is_per_kind_of_file(qtbot, tmp_path, sample_png, sample_pdf):
    first = MainWindow()
    qtbot.addWidget(first)
    first.add_files([sample_png])
    first.target_combo.setCurrentIndex(first.target_combo.findData("pdf"))
    first.output_dir = tmp_path / "out"
    first.start_conversion()
    qtbot.waitUntil(lambda: first._thread is None, timeout=30000)

    second = MainWindow()
    qtbot.addWidget(second)
    second.add_files([sample_pdf])
    # The image choice (PDF) doesn't apply to PDFs; they start with Word.
    assert second.target_combo.currentData() == "docx"


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
    from fileconv.gui.about import AboutDialog

    dialog = AboutDialog(window)
    names = [
        dialog.components.topLevelItem(i).text(0)
        for i in range(dialog.components.topLevelItemCount())
    ]
    assert "PyMuPDF / MuPDF" in names and "LibreOffice" in names
    assert "LibreOffice" in dialog.engines_label.text()
    dialog.close()
