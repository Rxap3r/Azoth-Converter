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
    window.dpi_spin.setValue(50)
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
