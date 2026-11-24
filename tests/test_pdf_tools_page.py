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
    page = window.password_page if window.current_page() == "password" else window.pdf_page
    assert page.action_btn.isEnabled()
    page.action_btn.click()
    qtbot.waitUntil(lambda: not page.busy, timeout=30000)
    return page.result.text()


def test_sidebar_has_pdf_tools(window):
    assert window.current_page() == "pdf"
    assert list(window.nav_buttons) == ["convert", "pdf", "password", "formats", "settings"]
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
    page.name_row.edit.setText("Both")
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
    assert "has a password" in window.pdf_page.result.text()
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
    assert "is not in the PDF" in page.split.hint.text()
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


# --- Compress and Password ----------------------------------------------------------


def make_photo_pdf(path):
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.effect_noise((3000, 2000), 60).convert("RGB").save(buf, "JPEG", quality=95)
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 60), "Holiday", fontsize=18)
    page.insert_image(pymupdf.Rect(72, 80, 272, 213), stream=buf.getvalue())
    doc.save(path)
    doc.close()
    return path


def test_compress_from_the_window(window, qtbot, tmp_path):
    from azoth import pdf_tools

    src = make_photo_pdf(tmp_path / "photos.pdf")
    page = window.pdf_page
    page.show_tool("compress")
    assert not page.action_btn.isEnabled()
    page.add_files([src])
    tool = page.compress
    assert tool.level() == "balanced" and "MB" in tool.file_label.text()
    tool.level_buttons["strong"].setChecked(True)
    assert page.action_btn.text() == "Compress"
    text = run(window, qtbot)
    out = tmp_path / "photos (compressed).pdf"
    assert out.exists() and "% smaller" in text and "→" in text
    assert page.result.open_btn.isVisible() or not window.isVisible()

    page.add_files([out])  # again: nothing to gain, shown as information, not an error
    text = run(window, qtbot)
    assert "did not save a file" in text and page.result.status.property("state") == "info"
    assert not (tmp_path / "photos (compressed) (compressed).pdf").exists()

    locked = pdf_tools.add_password(src, tmp_path / "locked.pdf", "Long enough 123!")
    page.add_files([locked])
    assert "has a password" in tool.file_label.text() and not page.action_btn.isEnabled()


def test_add_and_remove_password_from_the_window(window, qtbot, tmp_path):
    from azoth import pdf_tools

    src = make_pdf(tmp_path / "contract.pdf", ["Page 1", "Page 2"])
    window.show_page("password")
    page = window.password_page
    tool = page.password
    page.add_files([src])
    assert tool.adding() and not tool.repeat.isHidden() and not tool.forget.isHidden()
    assert tool.password.echoMode() == tool.password.EchoMode.Password
    tool.password.setText("short")
    assert "easy to guess" in tool.hint.text() and not page.action_btn.isEnabled()
    assert page.action_btn.text() == "Add password"
    tool.password.setText("Grüezi Welt 2026!")
    tool.repeat.setText("Grüezi Welt 2026")
    assert "are not the same" in tool.hint.text() and not page.action_btn.isEnabled()
    tool.repeat.setText("Grüezi Welt 2026!")
    assert page.action_btn.text() == "Add password"
    text = run(window, qtbot)
    locked = tmp_path / "contract (protected).pdf"
    assert "needs the password" in text
    assert pdf_tools.lock_state(locked) == pdf_tools.NEEDS_PASSWORD
    assert tool.password.text() == "" and tool.repeat.text() == ""  # forgotten right away

    page.add_files([locked])
    assert not tool.adding() and tool.repeat.isHidden() and tool.forget.isHidden()
    tool.password.setText("wrong")
    assert page.action_btn.text() == "Remove password"
    text = run(window, qtbot)
    assert "is not correct" in text and page.result.status.property("state") == "failed"
    assert tool.password.text() == ""
    tool.password.setText("Grüezi Welt 2026!")
    tool.password.returnPressed.emit()  # Enter works like the button
    qtbot.waitUntil(lambda: not page.busy, timeout=30000)
    unlocked = tmp_path / "contract (protected) (unlocked).pdf"
    assert "without a password" in page.result.text()
    assert texts(unlocked) == ["Page 1", "Page 2"]
    assert pdf_tools.lock_state(unlocked) == pdf_tools.UNLOCKED


def test_signed_pdfs_get_a_warning(window, tmp_path):
    src = make_pdf(tmp_path / "signed.pdf", ["Signed"])
    with pymupdf.open(src) as doc:
        doc.xref_set_key(doc.pdf_catalog(), "AcroForm", "<< /Fields [] /SigFlags 3 >>")
        doc.save(tmp_path / "s.pdf")
    for page, key in ((window.pdf_page, "compress"), (window.password_page, "password")):
        page.show_tool(key)
        page.add_files([tmp_path / "s.pdf"])
        assert not page.tools[key].signed.isHidden()
        page.add_files([src])
        assert page.tools[key].signed.isHidden()


def test_make_searchable_from_the_window(window, qtbot, tmp_path, ocr_ready):
    from conftest import make_text_scan

    picture = make_text_scan(tmp_path / "page.png", ["Scanned contract text"])
    scan = tmp_path / "scan.pdf"
    doc = pymupdf.open()
    doc.new_page(width=500, height=300).insert_image(
        pymupdf.Rect(0, 0, 500, 300), filename=str(picture)
    )
    doc.save(scan)
    doc.close()
    page = window.pdf_page
    page.show_tool("ocr")
    assert not page.action_btn.isEnabled()
    tool = page.searchable
    tool.language.set_language("eng")
    page.add_files([scan])
    assert page.action_btn.text() == "Make searchable"
    assert page.name_row.edit.text() == "scan (searchable)"
    text = run(window, qtbot)
    out = tmp_path / "scan (searchable).pdf"
    assert text == f"✓ Saved {out.name}"
    assert "Scanned contract text" in texts(out)[0]

    page.add_files([out])  # already has text: explained, nothing to do
    assert "already has selectable text" in tool.file_label.text()
    assert not page.action_btn.isEnabled()


def test_every_tool_lets_you_name_the_result(window, qtbot, tmp_path):
    src = make_pdf(tmp_path / "report.pdf", ["P1", "P2"])
    page = window.pdf_page
    row = page.name_row
    expected = {
        "split": ("report_pages", "Folder name"),
        "edit": ("report (edited)", "File name"),
        "compress": ("report (compressed)", "File name"),
    }
    for tool, (name, caption) in expected.items():
        page.show_tool(tool)
        assert not row.edit.isEnabled()  # no PDF yet: nothing to name
        page.add_files([src])
        assert row.edit.text() == name and row.caption.text() == caption
        assert row.edit.isEnabled()

    page.show_tool("split")
    row.edit.setText("Chapters")
    run(window, qtbot)
    assert sorted(p.name for p in (tmp_path / "Chapters").iterdir()) == [
        "report_page001.pdf",
        "report_page002.pdf",
    ]

    page.show_tool("edit")
    page.edit.pages.item(0).setSelected(True)
    page.edit.delete_selected()
    row.edit.setText("Only page two.pdf")  # a typed ".pdf" is not doubled
    assert run(window, qtbot) == "✓ Saved Only page two.pdf"
    assert texts(tmp_path / "Only page two.pdf") == ["P2"]

    page.edit.pages.item(0).setSelected(True)
    page.edit.delete_selected()
    row.edit.setText("report")  # the original's name: never overwritten
    run(window, qtbot)
    assert texts(src) == ["P1", "P2"] and (tmp_path / "report (1).pdf").exists()

    page.edit.pages.item(0).setSelected(True)
    page.edit.delete_selected()
    row.edit.setText("bad:name")
    page.action_btn.click()
    assert "cannot contain" in page.result.text() and not page.busy


def test_make_searchable_shows_progress_and_can_be_cancelled(
    window, qtbot, tmp_path, ocr_ready, monkeypatch
):
    import time

    from conftest import make_text_scan

    from azoth import ocr

    real = ocr._text_layer

    def slow(*args):  # long enough per page to watch the progress and press Cancel
        time.sleep(0.3)
        return real(*args)

    monkeypatch.setattr(ocr, "_text_layer", slow)

    picture = make_text_scan(tmp_path / "page.png", ["Scanned contract text"])
    scan = tmp_path / "long.pdf"
    doc = pymupdf.open()
    for _ in range(6):
        doc.new_page(width=500, height=300).insert_image(
            pymupdf.Rect(0, 0, 500, 300), filename=str(picture)
        )
    doc.save(scan)
    doc.close()
    page = window.pdf_page
    page.show_tool("ocr")
    page.add_files([scan])
    page.action_btn.click()
    assert page.cancel_btn.isVisibleTo(page)
    qtbot.waitUntil(lambda: page.progress.isVisibleTo(page), timeout=30000)
    assert "Reading text on page" in page.result.text()
    page.cancel_btn.click()
    qtbot.waitUntil(lambda: not page.busy, timeout=60000)
    assert page.result.text() == "Cancelled. Azoth Converter did not save a file."
    assert not (tmp_path / "long (searchable).pdf").exists()
    assert not page.cancel_btn.isVisibleTo(page) and not page.progress.isVisibleTo(page)


def test_other_tools_have_no_cancel_button(window, qtbot, tmp_path):
    src = make_pdf(tmp_path / "a.pdf", ["A"])
    page = window.pdf_page
    page.show_tool("split")
    page.add_files([src])
    page.action_btn.click()
    assert not page.cancel_btn.isVisibleTo(page)
    qtbot.waitUntil(lambda: not page.busy, timeout=30000)


def test_password_has_its_own_page(window, tmp_path):
    """Passwords work for Word, Excel and PowerPoint too, so they aren't a PDF tool."""
    assert "password" not in window.pdf_page.tools
    assert window.nav_buttons["password"].text() == "Password"
    window.show_page("password")
    page = window.password_page
    assert list(page.tools) == ["password"]
    assert all(b.isHidden() for b in page.tool_buttons.values())  # nothing to switch
    src = make_pdf(tmp_path / "report.pdf", ["P1"])
    page.add_files([src])
    assert page.name_row.edit.text() == "report (protected)"
