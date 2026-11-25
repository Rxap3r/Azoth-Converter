import threading

import pytest

from azoth.converters import ConversionCancelled, ConversionError
from azoth.engine import Engine, unique_path


def test_never_overwrites_existing_output(sample_png, tmp_path):
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    existing = out_dir / "logo.jpg"
    existing.write_bytes(b"keep me")
    [out] = Engine().convert(sample_png, "jpg", out_dir).outputs
    assert out.name == "logo (1).jpg"
    assert existing.read_bytes() == b"keep me"


def test_overwrite_when_asked(sample_png, tmp_path):
    existing = tmp_path / "logo.jpg"
    existing.write_bytes(b"old")
    [out] = Engine().convert(sample_png, "jpg", tmp_path, overwrite=True).outputs
    assert out == existing
    assert existing.read_bytes() != b"old"


def test_custom_name(sample_png, sample_pdf, tmp_path):
    engine = Engine()
    [out] = engine.convert(sample_png, "jpg", tmp_path, name="  Holiday 2026.jpg ").outputs
    assert out.name == "Holiday 2026.jpg"  # typed extension and spaces are dropped
    [again] = engine.convert(sample_png, "jpg", tmp_path, name="Holiday 2026").outputs
    assert again.name == "Holiday 2026 (1).jpg"  # never overwrites
    pages = engine.convert(sample_pdf, "jpg", tmp_path / "p", name="Scan").outputs
    assert [p.name for p in pages][:2] == ["Scan_page001.jpg", "Scan_page002.jpg"]


@pytest.mark.parametrize("bad", ["../escape", "a/b", "c:\\x", "what?", "", "  ", "CON", "nul.txt"])
def test_unsafe_names_are_refused(sample_png, tmp_path, bad):
    with pytest.raises(ConversionError):
        Engine().convert(sample_png, "jpg", tmp_path / "out", name=bad)
    assert not (tmp_path / "out").exists() or not any((tmp_path / "out").iterdir())
    assert not (tmp_path / "escape.jpg").exists()


def test_original_is_untouched(sample_png, tmp_path):
    before = sample_png.read_bytes()
    Engine().convert(sample_png, "webp", tmp_path / "o")
    assert sample_png.read_bytes() == before


def test_temp_files_removed_after_success(sample_pdf, tmp_path, private_tmp):
    Engine().convert(sample_pdf, "png", tmp_path / "o")
    assert list(private_tmp.iterdir()) == []


def test_temp_files_removed_after_failure(tmp_path, private_tmp):
    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"%PDF-1.7\nthis is not really a pdf")
    with pytest.raises(ConversionError):
        Engine().convert(broken, "png", tmp_path / "o")
    assert list(private_tmp.iterdir()) == []


def test_cancel(sample_pdf, tmp_path, private_tmp):
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(ConversionCancelled):
        Engine().convert(sample_pdf, "png", tmp_path / "o", cancel_event=cancel)
    assert list(private_tmp.iterdir()) == []
    assert not (tmp_path / "o").exists() or list((tmp_path / "o").iterdir()) == []


def test_unknown_and_same_format(tmp_path, sample_png):
    junk = tmp_path / "junk.xyz"
    junk.write_bytes(b"\x00\x01")
    with pytest.raises(ConversionError, match="does not know the file type"):
        Engine().convert(junk, "pdf")
    with pytest.raises(ConversionError, match="The format of logo.png is"):
        Engine().convert(sample_png, "png")


def test_routes():
    engine = Engine()
    assert [(s.src, s.dst) for s in engine.find_route("png", "jpg")] == [("png", "jpg")]
    # PDF pages → images can only be the last step, so no PDF → GIF via TIFF.
    assert engine.find_route("pdf", "gif") is None
    assert "docx" in {f.id for f in engine.targets_for("pdf")}


def test_missing_engine_explains_itself(sample_docx, tmp_path, monkeypatch):
    from azoth.converters import office

    monkeypatch.setattr(office, "find_soffice", lambda: None)
    with pytest.raises(ConversionError, match="LibreOffice"):
        Engine().convert(sample_docx, "pdf", tmp_path)


def test_unique_path(tmp_path):
    p = tmp_path / "a.txt"
    assert unique_path(p) == p
    p.write_text("x")
    (tmp_path / "a (1).txt").write_text("x")
    assert unique_path(p).name == "a (2).txt"


def test_pdf_to_word_only_for_real_pdfs():
    engine = Engine()
    # PDF → DOCX → DOC is fine: the PDF step works on the original file.
    if engine.find_route("docx", "doc") is not None:
        assert [(s.src, s.dst) for s in engine.find_route("pdf", "doc")] == [
            ("pdf", "docx"),
            ("docx", "doc"),
        ]
    # Excel → PDF → Word would give a poor Word file, so it isn't offered.
    assert engine.find_route("xlsx", "docx") is None
    assert engine.find_route("pptx", "txt") is None


def test_stale_temp_folders_are_cleaned_up(private_tmp):
    import os
    import time

    from azoth.engine import cleanup_stale_temp_folders

    old = private_tmp / "azoth-crashed"
    old.mkdir()
    (old / "leftover.tmp").write_text("x")
    week_ago = time.time() - 7 * 24 * 3600
    os.utime(old, (week_ago, week_ago))
    running = private_tmp / "azoth-running-now"  # e.g. a conversion in another window
    running.mkdir()
    other = private_tmp / "someone-else"  # not ours: never touched
    other.mkdir()
    os.utime(other, (week_ago, week_ago))

    assert cleanup_stale_temp_folders() == 1
    assert not old.exists()
    assert running.exists() and other.exists()


def test_routes_and_targets_are_worked_out_once(monkeypatch):
    engine = Engine()
    first = engine.targets_for("png")
    assert engine.find_route("png", "pdf") is not None
    calls = []
    monkeypatch.setattr(engine, "_search_route", lambda *a: calls.append(a))
    monkeypatch.setattr(engine, "_search_targets", lambda *a: calls.append(a))
    assert engine.targets_for("png") == first
    assert engine.find_route("png", "pdf") is not None
    assert calls == []  # remembered, not searched again
    engine.targets_for("png").clear()  # changing a returned list doesn't change the memory
    assert engine.targets_for("png") == first
