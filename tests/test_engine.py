import threading

import pytest

from fileconv.converters import ConversionCancelled, ConversionError
from fileconv.engine import Engine, unique_path


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
    with pytest.raises(ConversionError, match="Unknown file type"):
        Engine().convert(junk, "pdf")
    with pytest.raises(ConversionError, match="already"):
        Engine().convert(sample_png, "png")


def test_routes():
    engine = Engine()
    assert [(s.src, s.dst) for s in engine.find_route("png", "jpg")] == [("png", "jpg")]
    # PDF pages → images can only be the last step, so no PDF → GIF via TIFF.
    assert engine.find_route("pdf", "gif") is None
    assert "docx" in {f.id for f in engine.targets_for("pdf")}


def test_missing_engine_explains_itself(sample_docx, tmp_path, monkeypatch):
    from fileconv.converters import office

    monkeypatch.setattr(office, "find_soffice", lambda: None)
    with pytest.raises(ConversionError, match="LibreOffice"):
        Engine().convert(sample_docx, "pdf", tmp_path)


def test_unique_path(tmp_path):
    p = tmp_path / "a.txt"
    assert unique_path(p) == p
    p.write_text("x")
    (tmp_path / "a (1).txt").write_text("x")
    assert unique_path(p).name == "a (2).txt"
