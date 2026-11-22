"""Several files at once (Engine.convert_many): same results as one by one, only faster."""

from __future__ import annotations

import subprocess
import threading
from collections.abc import Iterable
from pathlib import Path

import pymupdf
import pytest
from conftest import make_docx

from azoth.converters import ConversionCancelled, ConversionContext, ConversionError, Converter
from azoth.converters import office as office_mod
from azoth.converters.base import RetryAlone
from azoth.converters.office import OfficeConverter, find_soffice
from azoth.engine import Engine

needs_lo = pytest.mark.skipif(find_soffice() is None, reason="LibreOffice not installed")


# --- the engine's batch logic, with a fake engine program ---------------------------


class FakeBatcher(Converter):
    """Converts .txt → .rtf by upper-casing; in a batch, files named "retry*" are handed
    back to be tried alone, files named "bad*" fail for sure, and alone every file with
    "bad" in its name fails."""

    id = label = "fake"
    priority = 100

    def __init__(self) -> None:
        self.batches: list[int] = []
        self.singles: list[str] = []

    def capabilities(self) -> Iterable[tuple[str, str]]:
        return [("txt", "rtf")]

    def batch_key(self, src, dst):
        return "same"

    def convert(self, src: Path, dst: Path, ctx: ConversionContext) -> list[Path]:
        self.singles.append(src.name)
        if "bad" in src.name:
            raise ConversionError("bad file")
        dst.write_text(src.read_text().upper())
        return [dst]

    def convert_batch(self, jobs, ctx):
        self.batches.append(len(jobs))
        results = []
        for src, dst in jobs:
            ctx.check_cancelled()
            if src.name.startswith("retry"):
                results.append(RetryAlone())
            elif src.name.startswith("bad"):
                results.append(ConversionError("bad file"))
            else:
                dst.write_text(src.read_text().upper())
                results.append(None)
        return results


def _texts(tmp_path, names):
    paths = []
    for name in names:
        path = tmp_path / "in" / name
        path.parent.mkdir(exist_ok=True)
        path.write_text(f"text of {name}")
        paths.append(path)
    return paths


def test_convert_many_batches_and_keeps_the_order(tmp_path):
    fake = FakeBatcher()
    files = _texts(tmp_path, [f"f{i}.txt" for i in range(5)])
    results = list(Engine([fake]).convert_many(files, "rtf", tmp_path / "out", batch_size=3))
    assert [i for i, _ in results] == [0, 1, 2, 3, 4]
    assert fake.batches == [3, 2] and fake.singles == []
    for (_, result), src in zip(results, files, strict=True):
        [out] = result.outputs
        assert out == tmp_path / "out" / f"{src.stem}.rtf"
        assert out.read_text() == src.read_text().upper()


def test_files_that_fail_in_a_batch_get_the_same_error_as_alone(tmp_path):
    fake = FakeBatcher()
    files = _texts(tmp_path, ["a.txt", "retry.txt", "bad.txt", "retrybad.txt"])
    files.append(tmp_path / "missing.txt")
    results = dict(Engine([fake]).convert_many(files, "rtf", tmp_path / "out"))
    assert results[0].outputs[0].read_text() == "TEXT OF A.TXT"
    assert results[1].outputs[0].read_text() == "TEXT OF RETRY.TXT"  # tried alone
    assert str(results[2]) == "bad file"
    assert str(results[3]) == "bad file"  # its error from the try alone
    assert "File not found" in str(results[4])
    assert fake.singles == ["retry.txt", "retrybad.txt"]  # "bad" isn't tried twice


def test_convert_many_never_overwrites_and_leaves_no_temp_files(tmp_path, private_tmp):
    fake = FakeBatcher()
    files = _texts(tmp_path, ["a.txt", "b.txt"])
    out = tmp_path / "out"
    out.mkdir()
    (out / "a.rtf").write_text("keep me")
    results = dict(Engine([fake]).convert_many(files, "rtf", out))
    assert (out / "a.rtf").read_text() == "keep me"
    assert results[0].outputs[0].name != "a.rtf"
    assert list(private_tmp.iterdir()) == []


def test_convert_many_stops_when_cancelled(tmp_path):
    fake = FakeBatcher()
    cancel = threading.Event()
    cancel.set()
    files = _texts(tmp_path, ["a.txt", "b.txt"])
    results = list(Engine([fake]).convert_many(files, "rtf", tmp_path, cancel_event=cancel))
    assert results == []
    cancel.clear()
    started = []

    def start(i):
        started.append(i)
        cancel.set()  # the user clicks Cancel while the first file runs

    results = list(
        Engine([fake]).convert_many(files, "rtf", tmp_path, started=start, cancel_event=cancel)
    )
    assert started == [0] and len(results) == 1
    assert isinstance(results[0][1], ConversionCancelled)


def test_a_crashed_batch_falls_back_to_one_by_one(tmp_path):
    class Crashing(FakeBatcher):
        def convert_batch(self, jobs, ctx):
            raise OSError("engine crashed")

    fake = Crashing()
    files = _texts(tmp_path, ["a.txt", "b.txt"])
    results = dict(Engine([fake]).convert_many(files, "rtf", tmp_path / "out"))
    assert all(r.outputs[0].exists() for r in results.values())
    assert fake.singles == ["a.txt", "b.txt"]


# --- LibreOffice ------------------------------------------------------------------


def _count_starts(monkeypatch) -> list[int]:
    starts = []
    real = subprocess.Popen

    def popen(cmd, *args, **kwargs):
        starts.append(sum(Path(c).name.startswith("input") for c in cmd))  # files per start
        return real(cmd, *args, **kwargs)

    monkeypatch.setattr(office_mod.subprocess, "Popen", popen)
    return starts


def _pdf_text(path):
    with pymupdf.open(path) as doc:
        return "".join(page.get_text() for page in doc)


@needs_lo
def test_libreoffice_converts_a_batch_in_one_start_with_the_same_result(tmp_path, monkeypatch):
    files = [make_docx(tmp_path / f"report {i}.docx", f"Report number {i}") for i in range(3)]
    alone = Engine().convert(files[1], "pdf", tmp_path / "alone").outputs[0]
    starts = _count_starts(monkeypatch)
    results = dict(Engine().convert_many(files, "pdf", tmp_path / "out"))
    assert starts == [3]  # one LibreOffice for all three files
    for i, src in enumerate(files):
        [out] = results[i].outputs
        assert out.name == f"{src.stem}.pdf"
        assert f"Report number {i}" in _pdf_text(out)
    assert _pdf_text(results[1].outputs[0]) == _pdf_text(alone)


@needs_lo
def test_a_broken_file_in_a_libreoffice_batch_fails_alone(tmp_path):
    good = make_docx(tmp_path / "good.docx", "Good report")
    broken = tmp_path / "broken.rtf"
    broken.write_bytes(b"{\\rtf1 " + b"\x00\xff" * 50)
    other = make_docx(tmp_path / "other.docx", "Other report")
    results = dict(Engine().convert_many([good, broken, other], "pdf", tmp_path / "out"))
    assert "Good report" in _pdf_text(results[0].outputs[0])
    assert "Other report" in _pdf_text(results[2].outputs[0])
    # the same clear error as when it's converted alone
    assert isinstance(results[1], ConversionError)
    assert "LibreOffice could not convert the file" in str(results[1])
    with pytest.raises(ConversionError, match="LibreOffice could not convert the file"):
        Engine().convert(broken, "pdf", tmp_path / "alone")


def test_libreoffice_does_not_trust_the_last_file_after_a_crash(tmp_path, monkeypatch):
    """If LibreOffice stops abnormally, the file it was writing may be incomplete."""

    class FakeProcess:
        returncode = 1

        def __init__(self, cmd, *args, **kwargs):
            out_dir = Path(cmd[cmd.index("--outdir") + 1])
            for name in ("input0.pdf", "input1.pdf"):  # wrote two, crashed in the second
                (out_dir / name).write_bytes(b"%PDF")

        def poll(self):
            return 1

        def kill(self):
            pass

        def communicate(self):
            return b"", b"crashed"

    monkeypatch.setattr(office_mod.subprocess, "Popen", FakeProcess)
    conv = OfficeConverter()
    monkeypatch.setattr(OfficeConverter, "soffice", Path("soffice"))
    jobs = []
    for n in range(3):
        src = tmp_path / f"s{n}.docx"
        src.write_bytes(b"x")
        jobs.append((src, tmp_path / f"r{n}.pdf"))
    work = tmp_path / "work"
    work.mkdir()
    results = conv.convert_batch(jobs, ConversionContext(work_dir=work))
    assert results[0] is None and jobs[0][1].exists()
    assert isinstance(results[1], RetryAlone) and not jobs[1][1].exists()
    assert isinstance(results[2], RetryAlone)
