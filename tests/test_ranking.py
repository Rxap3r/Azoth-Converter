"""The most useful target comes first and is the default."""

import pytest

from fileconv.engine import Engine

ENGINE = Engine()


@pytest.mark.parametrize(
    ("source", "first"),
    [("pdf", "docx"), ("png", "jpg"), ("jpg", "png"), ("heic", "jpg"), ("webp", "jpg")],
)
def test_first_target(source, first):
    assert ENGINE.targets_for(source)[0].id == first


@pytest.mark.parametrize("source", ["docx", "odt", "xlsx", "csv", "pptx", "doc"])
def test_office_files_start_with_pdf(source):
    targets = ENGINE.targets_for(source)
    if not targets:
        pytest.skip("LibreOffice not installed")
    assert targets[0].id == "pdf"


@pytest.mark.parametrize(
    ("source", "old"), [("pdf", "doc"), ("docx", "doc"), ("xlsx", "xls"), ("pptx", "ppt")]
)
def test_old_formats_come_last(source, old):
    ids = [t.id for t in ENGINE.targets_for(source)]
    if old not in ids:
        pytest.skip("needs LibreOffice")
    assert ids[-1] == old


def test_window_defaults_to_most_useful(qtbot, sample_pdf):
    from fileconv.gui.main_window import MainWindow

    window = MainWindow()
    qtbot.addWidget(window)
    window.add_files([sample_pdf])
    assert window.target_combo.currentData() == "docx"
