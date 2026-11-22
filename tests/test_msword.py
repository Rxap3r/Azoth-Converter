"""Microsoft Word engine. Word itself only exists on Windows PCs with Office, so most
tests replace PowerShell with a fake; on GitHub's Windows test machine the real
PowerShell checks the script."""

import base64
import subprocess
import sys
from pathlib import Path

import pytest

from azoth.converters import ConversionError, all_converters, msword
from azoth.converters.office import find_soffice
from azoth.engine import Engine


class FakePowerShell:
    """Stands in for subprocess.Popen: records the call and 'converts' or fails, writing
    the same status lines as the real script. ``fail`` holds the source file names
    (in Word's private copy: "input<n>.docx") that fail, ``True`` fails all."""

    calls: list = []
    succeed = True
    fail: set = set()

    def __init__(self, cmd, env):
        FakePowerShell.calls.append((cmd, env))
        self.returncode = None
        self._code, self._err = 0, b""
        if not FakePowerShell.succeed:  # Word itself can't start
            self._code, self._err = 1, b"Word could not open the document.\r\n"
            return
        with open(env["AZOTH_STATUS"], "a", encoding="utf-8") as status:
            for n in range(int(env["AZOTH_COUNT"])):
                src = Path(env[f"AZOTH_SRC_{n}"])
                if src.name in FakePowerShell.fail or Path(src).read_bytes() == b"bad":
                    status.write(f"failed {n} The file appears to be corrupted.\n")
                    continue
                Path(env[f"AZOTH_DST_{n}"]).write_bytes(b"%PDF-1.7 made by fake Word")
                status.write(f"ok {n}\n")

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
    FakePowerShell.fail = set()
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
    assert env["AZOTH_COUNT"] == "1"
    assert env["AZOTH_SRC_0"].endswith("input0.docx")
    assert "report.docx" not in env["AZOTH_SRC_0"]  # Word only sees a private copy
    assert "AutomationSecurity = 3" in script  # macros force-disabled
    assert "DisplayAlerts = 0" in script
    # Open's options go by name through InvokeMember: passing $true/$false directly made
    # Word fail on every PC ("True" of type "bool" can't be converted to "Object").
    assert "InvokeMember('Open'" in script and "'ReadOnly'" in script
    assert ".Documents.Open(" not in script


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


def test_clear_error_when_one_document_fails(fake_word, tmp_path):
    bad = tmp_path / "bad.docx"
    bad.write_bytes(b"bad")
    conv = msword.WordConverter(enabled=True, fallback=None)
    with pytest.raises(ConversionError, match="could not convert the file: The file appears"):
        Engine([conv]).convert(bad, "pdf", tmp_path / "out")


def test_word_converts_a_batch_in_one_start(fake_word, tmp_path):
    from conftest import make_docx

    files = [make_docx(tmp_path / f"r{i}.docx") for i in range(4)]
    bad = tmp_path / "bad.docx"
    bad.write_bytes(b"bad")
    files.insert(2, bad)
    conv = msword.WordConverter(enabled=True, fallback=None)
    results = dict(Engine([conv]).convert_many(files, "pdf", tmp_path / "out"))
    # one start for the batch, plus one for the bad file, tried again on its own
    assert [c[1]["AZOTH_COUNT"] for c in fake_word.calls] == ["5", "1"]
    for i, src in enumerate(files):
        if src is bad:
            assert "could not convert the file: The file appears" in str(results[i])
        else:
            assert results[i].outputs[0].name == f"{src.stem}.pdf"
            assert results[i].outputs[0].read_bytes().startswith(b"%PDF")


@pytest.mark.skipif(find_soffice() is None, reason="LibreOffice not installed")
def test_a_document_word_fails_in_a_batch_still_falls_back_to_libreoffice(fake_word, tmp_path):
    from conftest import make_docx

    files = [make_docx(tmp_path / f"r{i}.docx", f"Report {i}") for i in range(3)]
    fake_word.fail = {"input0.docx"}  # the first file: fails in the batch and alone
    results = dict(Engine(all_converters(use_word=True)).convert_many(files, "pdf", tmp_path))
    outputs = [results[i].outputs[0].read_bytes() for i in range(3)]
    assert all(out.startswith(b"%PDF") for out in outputs)
    assert b"fake Word" not in outputs[0]  # made by LibreOffice
    assert b"fake Word" in outputs[1] and b"fake Word" in outputs[2]
    assert [c[1]["AZOTH_COUNT"] for c in fake_word.calls] == ["3", "1"]


@pytest.mark.skipif(find_soffice() is None, reason="LibreOffice not installed")
def test_word_fallback_is_shown_with_words_reason(fake_word, sample_docx, tmp_path):
    fake_word.succeed = False
    result = Engine(all_converters(use_word=True)).convert(sample_docx, "pdf", tmp_path)
    [warning] = result.warnings
    assert warning.startswith("Word failed, LibreOffice was used")
    assert "Word could not open the document." in warning  # Word's own reason
