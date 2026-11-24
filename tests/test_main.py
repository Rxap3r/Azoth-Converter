"""Starting the program: app, command line, or the note of azoth-terminal.exe."""

import sys
from pathlib import Path

import pytest

from azoth import __main__ as entry


def test_double_clicked_terminal_program_explains_itself(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "azoth-terminal.exe"))
    monkeypatch.setattr(sys, "argv", ["azoth-terminal.exe"])
    monkeypatch.setattr(entry, "_own_console_window", lambda: True)
    prompts = []
    monkeypatch.setattr(entry, "_open_command_prompt", lambda: prompts.append(1) or True)
    monkeypatch.setattr("builtins.input", lambda prompt: pytest.fail("Enter must not close it"))
    monkeypatch.setattr("azoth.gui.app.main", lambda: 99)  # must not be opened
    assert entry.main() == 0
    out = capsys.readouterr().out
    assert "azoth-terminal convert photo.jpg --to png" in out
    assert "AzothConverter.exe" in out
    assert "Type your commands below" in out
    assert prompts  # the window becomes a Command Prompt where commands can be typed


def test_command_prompt_starts_in_the_users_folder_with_the_program_on_path(monkeypatch, tmp_path):
    import signal
    import subprocess

    monkeypatch.setattr(sys, "executable", str(tmp_path / "prog" / "azoth-terminal.exe"))
    monkeypatch.setattr(signal, "signal", lambda *a: None)
    calls = []
    monkeypatch.setattr(subprocess, "call", lambda cmd, **kw: calls.append((cmd, kw)) or 0)
    assert entry._open_command_prompt()
    cmd, kw = calls[0]
    assert cmd[0].lower().endswith("cmd.exe") and cmd[1] == "/k"
    assert kw["cwd"] == Path.home()
    assert kw["env"]["PATH"].startswith(str(tmp_path / "prog"))


def test_if_no_command_prompt_starts_enter_closes_the_window(monkeypatch, capsys):
    monkeypatch.setattr(entry, "_own_console_window", lambda: True)
    monkeypatch.setattr(entry, "_open_command_prompt", lambda: False)
    waited = []
    monkeypatch.setattr("builtins.input", lambda prompt: waited.append(prompt))
    assert entry.show_terminal_note() == 0
    assert waited


def test_typed_in_a_terminal_the_note_just_prints(monkeypatch, capsys):
    monkeypatch.setattr(entry, "_own_console_window", lambda: False)
    monkeypatch.setattr(entry, "_open_command_prompt", lambda: pytest.fail("no new prompt"))
    assert entry.show_terminal_note() == 0
    assert "Type your commands below" not in capsys.readouterr().out


def test_wildcards_are_expanded_for_windows_terminals(tmp_path, monkeypatch):
    from azoth.cli import expand_wildcards

    for name in ("b.heic", "a.heic", "c.jpg"):
        (tmp_path / name).write_bytes(b"x")
    monkeypatch.chdir(tmp_path)
    assert expand_wildcards(["*.heic", "c.jpg"]) == ["a.heic", "b.heic", "c.jpg"]
    assert expand_wildcards(["*.png"]) == ["*.png"]  # no match: "not found" as usual


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
