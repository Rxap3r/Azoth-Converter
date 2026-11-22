"""Starting the program: app, command line, or the note of azoth-terminal.exe."""

import sys

from azoth import __main__ as entry


def test_double_clicked_terminal_program_explains_itself(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "azoth-terminal.exe"))
    monkeypatch.setattr(sys, "argv", ["azoth-terminal.exe"])
    monkeypatch.setattr(entry, "_own_console_window", lambda: True)
    waited = []
    monkeypatch.setattr("builtins.input", lambda prompt: waited.append(prompt))
    monkeypatch.setattr("azoth.gui.app.main", lambda: 99)  # must not be opened
    assert entry.main() == 0
    out = capsys.readouterr().out
    assert "azoth-terminal convert photo.jpg --to png" in out
    assert "AzothConverter.exe" in out
    assert waited  # the window stays open until Enter is pressed


def test_the_app_still_opens_from_its_own_program(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "AzothConverter.exe"))
    monkeypatch.setattr(sys, "argv", ["AzothConverter.exe"])
    monkeypatch.setattr("azoth.gui.app.main", lambda: 99)
    assert entry.main() == 99


def test_commands_still_work_in_the_terminal_program(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "azoth-terminal.exe"))
    monkeypatch.setattr(sys, "argv", ["azoth-terminal.exe", "formats"])
    assert entry.main() == 0
