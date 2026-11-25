"""Passwords on Word, Excel and PowerPoint files (office_password.py): adding, removing,
and converting protected files (engine, CLI, app)."""

import io
import sys

import docx
import openpyxl
import pptx
import pytest

from azoth import office_password
from azoth.cli import main
from azoth.converters import ConversionError, all_converters, msword
from azoth.converters.office import find_soffice
from azoth.engine import Engine
from azoth.office_password import PasswordNeeded

PASSWORD = "Blue-Horse-42!"


def _make(tmp_path, kind: str):
    path = tmp_path / f"plain.{kind}"
    if kind == "docx":
        d = docx.Document()
        d.add_paragraph("Quarterly secret numbers")
        d.save(path)
    elif kind == "xlsx":
        wb = openpyxl.Workbook()
        wb.active["A1"] = "Quarterly secret numbers"
        wb.save(path)
    else:
        prs = pptx.Presentation()
        slide = prs.slides.add_slide(prs.slide_layouts[5])
        slide.shapes.title.text = "Quarterly secret numbers"
        prs.save(path)
    return path


def _locked(tmp_path, kind: str):
    return office_password.add_password(
        _make(tmp_path, kind), tmp_path / f"locked.{kind}", PASSWORD
    )


@pytest.mark.parametrize("kind", ["docx", "xlsx", "pptx"])
def test_add_and_remove_give_back_the_exact_file(tmp_path, kind):
    plain = _make(tmp_path, kind)
    before = plain.read_bytes()
    locked = office_password.add_password(plain, office_password.protected_path(plain), PASSWORD)
    assert locked.name == f"plain (protected).{kind}"
    assert office_password.is_protected(locked) and not office_password.is_protected(plain)
    assert plain.read_bytes() == before  # the original is never touched
    import msoffcrypto

    with locked.open("rb") as fh:  # what Office reads: AES-256 "agile" encryption
        info = msoffcrypto.OfficeFile(fh)
        assert info.type == "agile"
    unlocked = office_password.remove_password(
        locked, office_password.unlocked_path(locked), PASSWORD
    )
    assert unlocked.read_bytes() == before
    assert office_password.is_protected(locked)  # still locked


def test_wrong_or_missing_password(tmp_path):
    locked = _locked(tmp_path, "docx")
    with pytest.raises(PasswordNeeded, match="is not correct"):
        office_password.remove_password(locked, tmp_path / "x.docx", "wrong")
    with pytest.raises(ConversionError, match="Enter the password of the file"):
        office_password.remove_password(locked, tmp_path / "x.docx", "")
    assert not (tmp_path / "x.docx").exists()


def test_refused_cases(tmp_path):
    locked = _locked(tmp_path, "xlsx")
    with pytest.raises(ConversionError, match="has a password. Remove that password first"):
        office_password.add_password(locked, tmp_path / "again.xlsx", PASSWORD)
    with pytest.raises(ConversionError, match="has no password"):
        office_password.remove_password(_make(tmp_path, "pptx"), tmp_path / "o.pptx", "x")
    with pytest.raises(ConversionError, match="cannot start or end with a space"):
        office_password.add_password(_make(tmp_path, "docx"), tmp_path / "o.docx", " pw ")
    old = tmp_path / "old.doc"
    old.write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\0" * 600)
    if office_password.file_kind(old) == "doc":
        with pytest.raises(ConversionError, match="only to DOCX"):
            office_password.add_password(old, tmp_path / "o.doc", PASSWORD)


def test_never_overwrites(tmp_path):
    plain = _make(tmp_path, "docx")
    first = office_password.add_password(plain, tmp_path / "out.docx", PASSWORD)
    second = office_password.add_password(plain, tmp_path / "out.docx", PASSWORD)
    assert first != second and second.name == "out (1).docx"


# --- converting protected files --------------------------------------------------------


def test_protected_file_needs_its_password(tmp_path):
    locked = _locked(tmp_path, "docx")
    # The password is asked for before any engine runs, so this works on every PC.
    engine = Engine(all_converters(), assume_available=True)
    with pytest.raises(PasswordNeeded, match="has a password"):
        engine.convert(locked, "pdf", tmp_path / "o")
    with pytest.raises(PasswordNeeded, match="is not correct"):
        engine.convert(locked, "pdf", tmp_path / "o", options={"passwords": {"*": "nope"}})


@pytest.mark.skipif(find_soffice() is None, reason="LibreOffice not installed")
@pytest.mark.parametrize("kind", ["docx", "xlsx", "pptx"])
def test_protected_file_converts_with_its_password(tmp_path, kind):
    import pymupdf

    locked = _locked(tmp_path, kind)
    result = Engine().convert(
        locked, "pdf", tmp_path / "o", options={"passwords": {str(locked): PASSWORD}}
    )
    with pymupdf.open(result.outputs[0]) as pdf:
        assert "Quarterly secret numbers" in "".join(p.get_text() for p in pdf)
    assert office_password.is_protected(locked)  # the original stays locked


def test_microsoft_office_only_sees_the_unlocked_private_copy(tmp_path, monkeypatch):
    from test_msword import FakePowerShell

    FakePowerShell.calls, FakePowerShell.succeed, FakePowerShell.fail = [], True, set()
    seen = []

    class Recording(FakePowerShell):
        def __init__(self, cmd, env):
            from pathlib import Path

            seen.append(Path(env["AZOTH_SRC_0"]).read_bytes())
            super().__init__(cmd, env)

    monkeypatch.setattr(msword, "app_installed", lambda app: True)
    monkeypatch.setattr(msword, "find_powershell", lambda: "powershell.exe")
    monkeypatch.setattr(msword, "_start_process", Recording)
    locked = _locked(tmp_path, "xlsx")
    engine = Engine(all_converters(use_word=True))
    engine.convert(locked, "pdf", tmp_path / "o", options={"passwords": {"*": PASSWORD}})
    assert seen and seen[0].startswith(b"PK")  # a normal (unlocked) XLSX


def test_cli_password_tool_for_office_files(tmp_path, monkeypatch, capsys):
    import getpass

    answers = iter([PASSWORD, PASSWORD, PASSWORD])
    monkeypatch.setattr(getpass, "getpass", lambda prompt="": next(answers))
    plain = _make(tmp_path, "pptx")
    assert main(["password", "add", str(plain)]) == 0
    locked = tmp_path / "plain (protected).pptx"
    assert office_password.is_protected(locked)
    assert main(["pdf", "password", "remove", str(locked)]) == 0
    assert (tmp_path / "plain (protected) (unlocked).pptx").read_bytes() == plain.read_bytes()


def test_cli_convert_asks_for_the_password(tmp_path, monkeypatch):
    import getpass

    locked = _locked(tmp_path, "docx")
    answers = iter(["wrong", PASSWORD])
    monkeypatch.setattr(getpass, "getpass", lambda prompt="": next(answers))
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True, raising=False)
    asked = {}

    def convert_many(self, paths, target, output, *, options, **kw):
        asked.update(options["passwords"])
        return iter(())

    monkeypatch.setattr(Engine, "convert_many", convert_many)
    assert main(["convert", str(locked), "--to", "pdf", "-q"]) == 0
    assert asked == {str(locked): PASSWORD}  # checked: the wrong one was asked again


# --- the app -----------------------------------------------------------------------------


def test_password_tool_in_the_app(qtbot, tmp_path):
    pytest.importorskip("pytestqt")
    from azoth.gui.pdf_tools_page import PasswordTool

    tool = PasswordTool()
    qtbot.addWidget(tool)
    plain = _make(tmp_path, "xlsx")
    tool.add_files([plain])
    assert tool.source == plain and tool.adding() and tool.name_extension == "xlsx"
    assert tool.result_name() == "plain (protected)"
    tool.password.setText(PASSWORD)
    tool.repeat.setText(PASSWORD)
    assert tool.action() == "Add password"
    [out] = tool.job(None, "plain (protected)")()
    assert out.suffix == ".xlsx" and office_password.is_protected(out)
    assert "needs the password" in tool.done_text([out])

    tool.add_files([out])
    assert not tool.adding() and tool.repeat.isHidden()
    assert tool.mode.text().startswith("This file is locked")
    tool.password.setText(PASSWORD)
    [back] = tool.job(None, "plain (unlocked)")()
    assert back.read_bytes() == plain.read_bytes()


def test_app_asks_for_the_password_and_skips_on_cancel(qtbot, tmp_path, monkeypatch):
    pytest.importorskip("pytestqt")
    from azoth.gui.main_window import MainWindow

    window = MainWindow()
    qtbot.addWidget(window)
    locked = _locked(tmp_path, "docx")
    window.add_files([locked])
    asked = []
    monkeypatch.setattr(window, "ask_password", lambda path: asked.append(path) or None)
    jobs = [(0, locked, "pdf")]
    assert window._office_passwords(jobs) == {} and jobs == []
    assert asked == [locked]
    assert window.file_list.status(0) == "Skipped: no password entered"
    monkeypatch.setattr(window, "ask_password", lambda path: PASSWORD)
    jobs = [(0, locked, "pdf")]
    assert window._office_passwords(jobs) == {str(locked): PASSWORD} and len(jobs) == 1


def test_password_bytes_are_never_written_to_disk(tmp_path):
    """The unlocked copy for converting only goes into the job's own temporary folder."""
    locked = _locked(tmp_path, "docx")
    folder = tmp_path / "job"
    folder.mkdir()
    copy = office_password.unlock_into(locked, folder, PASSWORD)
    assert copy.parent == folder and copy.read_bytes()[:2] == b"PK"
    assert PASSWORD.encode() not in io.BytesIO(copy.read_bytes()).getvalue()
