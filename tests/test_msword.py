"""Microsoft Word engine. Word itself only exists on Windows PCs with Office, so most
tests replace PowerShell with a fake; on Windows CI the real PowerShell checks the script."""

import base64
import subprocess
import sys

import pytest

from azoth.converters import ConversionError, all_converters, msword
from azoth.converters.office import find_soffice
from azoth.engine import Engine


class FakePowerShell:
    """Stands in for subprocess.Popen: records the call and 'converts' or fails."""

    calls: list = []
    succeed = True

    def __init__(self, cmd, env):
        FakePowerShell.calls.append((cmd, env))
        self.returncode = None
        if FakePowerShell.succeed:
            with open(env["AZOTH_DST"], "wb") as fh:
                fh.write(b"%PDF-1.7 made by fake Word")
            self._code, self._err = 0, b""
        else:
            self._code, self._err = 1, b"Word could not open the document.\r\n"

    def poll(self):
        self.returncode = self._code
        return self._code

    def kill(self):
        pass

    def communicate(self):
        return b"", self._err


@pytest.fixture
def fake_word(monkeypatch):
    FakePowerShell.calls = []
    FakePowerShell.succeed = True
    monkeypatch.setattr(msword, "word_installed", lambda: True)
    monkeypatch.setattr(msword, "find_powershell", lambda: "powershell.exe")
    monkeypatch.setattr(msword, "_start_process", FakePowerShell)
    return FakePowerShell


def test_word_not_used_when_missing_or_disabled(monkeypatch):
    monkeypatch.setattr(msword, "word_installed", lambda: False)
    engine = Engine(all_converters())
    assert not engine.uses_word()
    assert "msword" not in {c.id for c in engine.unavailable()}  # no warning banner


def test_word_preferred_for_word_to_pdf(fake_word):
    engine = Engine(all_converters(use_word=True))
    assert engine.uses_word()
    route = engine.find_route("docx", "pdf")
    assert [s.converter.id for s in route] == ["msword"]
    # Other office conversions still use LibreOffice.
    if find_soffice():
        assert engine.find_route("docx", "odt")[0].converter.id == "libreoffice"
    # Turned off: back to LibreOffice.
    off = Engine(all_converters(use_word=False))
    assert not off.uses_word()


def test_word_conversion_passes_paths_safely(fake_word, sample_docx, tmp_path):
    result = Engine(all_converters(use_word=True)).convert(sample_docx, "pdf", tmp_path / "o")
    [out] = result.outputs
    assert out.name == "report.pdf"
    assert out.read_bytes().startswith(b"%PDF")

    [(cmd, env)] = fake_word.calls
    assert "-EncodedCommand" in cmd and "-NoProfile" in cmd
    # Paths only travel in environment variables, never inside the script.
    script = base64.b64decode(cmd[cmd.index("-EncodedCommand") + 1]).decode("utf-16-le")
    assert str(sample_docx) not in script
    assert env["AZOTH_SRC"].endswith("input.docx")
    assert "report.docx" not in env["AZOTH_SRC"]  # Word only sees a private copy
    assert "AutomationSecurity = 3" in script  # macros force-disabled
    assert "DisplayAlerts = 0" in script


@pytest.mark.skipif(find_soffice() is None, reason="LibreOffice not installed")
def test_falls_back_to_libreoffice_when_word_fails(fake_word, sample_docx, tmp_path):
    fake_word.succeed = False
    result = Engine(all_converters(use_word=True)).convert(sample_docx, "pdf", tmp_path)
    [out] = result.outputs
    assert out.read_bytes().startswith(b"%PDF")
    assert b"fake Word" not in out.read_bytes()  # made by LibreOffice


def test_clear_error_when_word_fails_without_fallback(fake_word, sample_docx, tmp_path):
    fake_word.succeed = False
    conv = msword.WordConverter(enabled=True, fallback=None)
    with pytest.raises(ConversionError, match="Microsoft Word could not convert"):
        Engine([conv]).convert(sample_docx, "pdf", tmp_path / "out")
    assert not (tmp_path / "out").exists() or list((tmp_path / "out").iterdir()) == []


@pytest.mark.skipif(sys.platform != "win32", reason="needs Windows PowerShell")
def test_script_is_valid_powershell():
    check = (
        "$e = $null; [void][System.Management.Automation.Language.Parser]::ParseInput("
        "$env:SCRIPT_TEXT, [ref]$null, [ref]$e); if ($e) { $e | ForEach-Object { "
        "[Console]::Error.WriteLine($_.Message) }; exit 1 }"
    )
    env = {**__import__("os").environ, "SCRIPT_TEXT": msword.POWERSHELL_SCRIPT}
    result = subprocess.run(
        [msword.find_powershell(), "-NoProfile", "-NonInteractive", "-Command", check],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.skipif(sys.platform != "win32", reason="needs Windows PowerShell")
@pytest.mark.skipif(msword.word_installed(), reason="Word is installed here")
def test_real_powershell_reports_missing_word(monkeypatch, sample_docx, tmp_path):
    """On a Windows PC without Word the script must fail cleanly, not hang."""
    monkeypatch.setattr(msword, "word_installed", lambda: True)
    conv = msword.WordConverter(enabled=True, fallback=None)
    with pytest.raises(ConversionError, match="Microsoft Word could not convert"):
        Engine([conv]).convert(sample_docx, "pdf", tmp_path, options={"timeout": 120})
