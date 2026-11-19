"""The PDF tools page: merge, split and edit pages from the window."""

from __future__ import annotations

import pymupdf
import pytest

pytest.importorskip("pytestqt")

from PySide6.QtCore import QMimeData, QPointF, Qt, QUrl  # noqa: E402
from PySide6.QtGui import QDropEvent  # noqa: E402

from azoth.gui.main_window import MainWindow  # noqa: E402


def make_pdf(path, labels):
    doc = pymupdf.open()
    for text in labels:
        doc.new_page().insert_text((72, 72), text, fontsize=20)
    doc.save(path)
    doc.close()
    return path


def texts(path):
    with pymupdf.open(path) as doc:
        return [page.get_text().strip() for page in doc]


@pytest.fixture
def window(qtbot):
    w = MainWindow()
    qtbot.addWidget(w)
    w.show_page("pdf")
    return w


def run(window, qtbot):
    page = window.pdf_page
    assert page.action_btn.isEnabled()
    page.action_btn.click()
    qtbot.waitUntil(lambda: not page.busy, timeout=30000)
    return page.result.text()


def test_sidebar_has_pdf_tools(window):
    assert window.current_page() == "pdf"
    assert list(window.nav_buttons) == ["convert", "pdf", "formats", "settings"]
    assert window.pdf_page.current_tool() == "merge"


def test_merge_in_chosen_order(window, qtbot, tmp_path):
    a = make_pdf(tmp_path / "a.pdf", ["A1"])
    b = make_pdf(tmp_path / "b.pdf", ["B1", "B2"])
    page = window.pdf_page
    page.add_files([a, b, a])  # duplicate ignored
    merge = page.merge
    assert [p.name for p in merge.files()] == ["a.pdf", "b.pdf"]
    assert page.action_btn.text() == "Merge 2 PDFs"
    merge.list.item(1).setSelected(True)
    merge.up_btn.click()  # b first
    merge.name.setText("Both")
    assert "✓ Saved Both.pdf" == run(window, qtbot)
    assert texts(tmp_path / "Both.pdf") == ["B1", "B2", "A1"]
    assert page.result.open_btn.isVisibleTo(page) and page.result.folder_btn.isVisibleTo(page)


def test_merge_bin_button_removes_one_row(window, qtbot, tmp_path):
    from PySide6.QtTest import QTest

    files = [make_pdf(tmp_path / f"{n}.pdf", [n]) for n in "abc"]
    merge = window.pdf_page.merge
    window.pdf_page.add_files(files)
    window.resize(1200, 800)
    view = merge.list
    rect = merge.remover.button_rect(view.visualItemRect(view.item(1)))
    QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=rect.center())
    assert [p.name for p in merge.files()] == ["a.pdf", "c.pdf"]
    view.item(0).setSelected(True)
    view.setFocus()
    QTest.keyClick(view, Qt.Key.Key_Delete)  # the keyboard way
    assert [p.name for p in merge.files()] == ["c.pdf"]
    assert not merge.remover.icon.isNull()  # drawn in the theme's colour


def test_merge_refuses_unreadable_pdfs(window, tmp_path):
    a = make_pdf(tmp_path / "a.pdf", ["A"])
    locked = tmp_path / "locked.pdf"
    doc = pymupdf.open()
    doc.new_page()
    doc.save(locked, encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="x", owner_pw="x")
    doc.close()
    window.pdf_page.add_files([a, locked, tmp_path])  # a folder is ignored too
    assert [p.name for p in window.pdf_page.merge.files()] == ["a.pdf"]
    assert "password-protected" in window.pdf_page.result.text()
    assert not window.pdf_page.action_btn.isEnabled()  # one PDF can't be merged


def test_split_by_ranges(window, qtbot, tmp_path):
    src = make_pdf(tmp_path / "doc.pdf", ["D1", "D2", "D3", "D4"])
    page = window.pdf_page
    page.show_tool("split")
    page.add_files([src])
    assert page.action_btn.text() == "Split into 4 PDFs"
    page.split.by_ranges.setChecked(True)
    page.split.ranges.setText("1-2, 9")
    assert not page.action_btn.isEnabled()
    assert "doesn't fit" in page.split.hint.text()
    page.split.ranges.setText("1-2, 4")
    assert page.action_btn.text() == "Split into 2 PDFs"
    window.output_dir = None
    page.output_row.folder = tmp_path / "out"
    assert run(window, qtbot) == "✓ Saved 2 PDFs in doc_pages"
    folder = tmp_path / "out" / "doc_pages"
    assert texts(folder / "doc (pages 1-2).pdf") == ["D1", "D2"]
    assert texts(folder / "doc (page 4).pdf") == ["D4"]


def test_edit_pages(window, qtbot, tmp_path):
    src = make_pdf(tmp_path / "scan.pdf", ["S1", "S2", "S3"])
    page = window.pdf_page
    page.show_tool("edit")
    page.add_files([src])
    edit = page.edit
    qtbot.waitUntil(lambda: not edit.loading(), timeout=10000)
    assert edit.pages.count() == 3
    assert all(not edit.pages.item(i).icon().isNull() for i in range(3))  # thumbnails
    assert not page.action_btn.isEnabled()  # nothing changed yet

    edit.pages.item(1).setSelected(True)
    edit.right_btn.click()  # turn page 2
    assert edit.pages.item(1).text() == "Page 2  ↻90°"
    edit.pages.clearSelection()
    edit.pages.item(2).setSelected(True)
    edit.delete_btn.click()  # delete page 3
    edit.pages.item(0).setSelected(True)
    edit.later_btn.click()  # page 1 after page 2
    assert page.action_btn.text() == "Save as new PDF"
    assert run(window, qtbot) == "✓ Saved scan (edited).pdf"
    out = tmp_path / "scan (edited).pdf"
    assert texts(out) == ["S2", "S1"]
    with pymupdf.open(out) as doc:
        assert [p.rotation for p in doc] == [90, 0]
    assert texts(src) == ["S1", "S2", "S3"]  # original unchanged

    edit.pages.selectAll()
    assert not edit.delete_btn.isEnabled()  # at least one page has to stay
    edit.reset_btn.click()
    qtbot.waitUntil(lambda: not edit.loading(), timeout=10000)
    assert edit.pages.count() == 3


def test_dropped_pdfs_go_to_the_open_tool(window, tmp_path):
    a = make_pdf(tmp_path / "a.pdf", ["A"])
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(a))])
    event = QDropEvent(
        QPointF(5, 5), Qt.DropAction.CopyAction, mime, Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    )  # fmt: skip
    window.dropEvent(event)
    assert window.current_page() == "pdf"
    assert [p.name for p in window.pdf_page.merge.files()] == ["a.pdf"]
    assert window.file_list.count() == 0  # not added to Convert

    window.show_page("convert")
    window.dropEvent(event)
    assert window.file_list.count() == 1
