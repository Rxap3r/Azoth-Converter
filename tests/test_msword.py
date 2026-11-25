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
    monkeypatch.setattr(msword, "app_installed", lambda app: True)
    monkeypatch.setattr(msword, "find_powershell", lambda: "powershell.exe")
    monkeypatch.setattr(msword, "_start_process", FakePowerShell)
    return FakePowerShell


def test_word_not_used_when_missing_or_disabled(monkeypatch):
    monkeypatch.setattr(msword, "app_installed", lambda app: False)
    engine = Engine(all_converters())
    assert not engine.uses_word()
    assert "msword" not in {c.id for c in engine.unavailable()}  # no warning banner


def test_word_preferred_for_word_to_pdf(fake_word):
    engine = Engine(all_converters(use_word=True))
    assert engine.uses_word()
    route = engine.find_route("docx", "pdf")
    assert [s.converter.id for s in route] == ["msword"]
    # Word also saves its other formats; Excel and PowerPoint do theirs.
    assert [s.converter.id for s in engine.find_route("doc", "docx")] == ["msword"]
    assert [s.converter.id for s in engine.find_route("xls", "pdf")] == ["msexcel"]
    assert [s.converter.id for s in engine.find_route("ppt", "pptx")] == ["mspowerpoint"]
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
    assert env["AZOTH_SRC_0"].endswith("input0.docx") and env["AZOTH_APP"] == "word"
    assert "report.docx" not in env["AZOTH_SRC_0"]  # Word only sees a private copy
    assert "AutomationSecurity = 3" in script  # macros force-disabled
    assert "DisplayAlerts = 0" in script
    # Open's options go by name through InvokeMember: passing $true/$false directly made
    # Word fail on every PC ("True" of type "bool" can't be converted to "Object").
    assert "InvokeMember($method" in script and "$app.Documents 'Open'" in script
    assert "$app.Workbooks 'Open'" in script and "'ReadOnly'" in script
    assert ".Documents.Open(" not in script and ".Workbooks.Open(" not in script


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
    with pytest.raises(ConversionError, match="Microsoft Word cannot convert"):
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
    monkeypatch.setattr(msword, "app_installed", lambda app: True)
    conv = msword.WordConverter(enabled=True, fallback=None)
    with pytest.raises(ConversionError, match="Microsoft Word cannot convert"):
        Engine([conv]).convert(sample_docx, "pdf", tmp_path, options={"timeout": 120})


def test_clear_error_when_one_document_fails(fake_word, tmp_path):
    bad = tmp_path / "bad.docx"
    bad.write_bytes(b"bad")
    conv = msword.WordConverter(enabled=True, fallback=None)
    with pytest.raises(ConversionError, match="cannot convert the file: The file appears"):
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
            assert "cannot convert the file: The file appears" in str(results[i])
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


@pytest.mark.parametrize(
    "src, dst, app, code",
    [
        ("xlsx", "pdf", "excel", "pdf"),
        ("xls", "xlsx", "excel", "51"),
        ("xlsx", "csv", "excel", "62"),
        ("pptx", "pdf", "powerpoint", "pdf"),
        ("ppt", "pptx", "powerpoint", "24"),
        ("doc", "docx", "word", "16"),
        ("docx", "txt", "word", "7"),
    ],
)
def test_excel_powerpoint_and_word_formats(fake_word, tmp_path, src, dst, app, code):
    source = tmp_path / f"file.{src}"
    source.write_bytes(b"PK\x03\x04 made-up office file")
    result = Engine(all_converters(use_word=True)).convert(source, dst, tmp_path / "o")
    [out] = result.outputs
    assert out.name == f"file.{dst}"
    [(_cmd, env)] = fake_word.calls
    assert env["AZOTH_APP"] == app and env["AZOTH_FMT_0"] == code
    assert env["AZOTH_DST_0"].endswith(f".{dst}")


def test_office_programs_are_optional_and_listed(monkeypatch):
    monkeypatch.setattr(msword, "app_installed", lambda app: app.key == "excel")
    assert [a.key for a in msword.office_installed()] == ["excel"]
    engine = Engine(all_converters())
    assert not {"msword", "msexcel", "mspowerpoint"} & {c.id for c in engine.unavailable()}


def test_password_protected_files_are_refused_before_office_opens_them(fake_word, tmp_path):
    # An encrypted DOCX/XLSX/PPTX is an OLE container with an "EncryptionInfo" stream.
    protected = tmp_path / "secret.xlsx"
    protected.write_bytes(
        b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\0" * 100 + "EncryptionInfo".encode("utf-16-le")
    )
    assert msword.password_protected(protected)
    with pytest.raises(ConversionError, match="has a password"):
        Engine(all_converters(use_word=True)).convert(protected, "pdf", tmp_path / "o")
    assert fake_word.calls == []  # Excel never saw it (it would ask for the password)
    plain = tmp_path / "plain.xlsx"
    plain.write_bytes(b"PK\x03\x04")
    assert not msword.password_protected(plain)


def test_powerpoint_is_left_open_when_the_user_has_it_open():
    """PowerPoint is one program for all windows: closing it after converting would close
    the user's own presentations."""
    script = msword.POWERSHELL_SCRIPT
    assert "Get-Process POWERPNT" in script
    assert "if (-not $leaveOpen -and $app.Presentations.Count -eq 0) { $app.Quit() }" in script
    assert "AutomationSecurity = 3" in script.split("powerpoint")[1]  # macros off there too


def _without_libreoffice(monkeypatch):
    from azoth.converters import office

    monkeypatch.setattr(office.OfficeConverter, "is_available", lambda self: False)


def test_no_libreoffice_message_when_office_does_everything(monkeypatch, with_ffmpeg):
    _without_libreoffice(monkeypatch)
    monkeypatch.setattr(msword, "app_installed", lambda app: True)
    monkeypatch.setattr(msword, "find_powershell", lambda: "powershell.exe")
    engine = Engine(all_converters())
    assert [c.id for c in engine.unavailable()] == ["libreoffice"]
    assert engine.needed_engines() == []  # Word, Excel and PowerPoint cover it all


def test_libreoffice_message_names_only_what_is_missing(monkeypatch, with_ffmpeg):
    _without_libreoffice(monkeypatch)
    monkeypatch.setattr(msword, "app_installed", lambda app: app.key == "word")
    monkeypatch.setattr(msword, "find_powershell", lambda: "powershell.exe")
    [(conv, missing)] = Engine(all_converters()).needed_engines()
    assert conv.id == "libreoffice"
    assert ("docx", "pdf") not in missing and ("xlsx", "pdf") in missing
    text = conv.unavailable_reason(missing)
    assert text.startswith(
        "LibreOffice (free) or Microsoft Office is necessary for Excel files and PowerPoint files"
    )
    # Without any Office program: the general message.
    monkeypatch.setattr(msword, "app_installed", lambda app: False)
    [(conv, missing)] = Engine(all_converters()).needed_engines()
    assert conv.unavailable_reason(missing).startswith("LibreOffice (free) is necessary for Office")


def test_formats_panel_counts_office_as_installed(qtbot, monkeypatch):
    pytest.importorskip("pytestqt")
    from azoth.gui.formats_panel import FormatsPanel

    monkeypatch.setattr(msword, "app_installed", lambda app: app.key == "excel")
    panel = FormatsPanel(False, can_convert=lambda s, d: s == "xlsx")
    qtbot.addWidget(panel)
    assert panel.status_label.text().startswith("Microsoft Excel does the office conversions")
