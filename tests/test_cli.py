from conftest import make_pdf

from azoth.cli import main


def test_convert_and_formats(sample_png, tmp_path, capsys):
    assert main(["convert", str(sample_png), "--to", "jpg", "-o", str(tmp_path / "o")]) == 0
    assert (tmp_path / "o" / "logo.jpg").exists()
    assert main(["formats", str(sample_png)]) == 0
    assert "webp" in capsys.readouterr().out


def test_convert_failure_exit_code(tmp_path):
    bad = tmp_path / "x.unknown"
    bad.write_bytes(b"nothing")
    assert main(["convert", str(bad), "--to", "pdf", "-q"]) == 1


def test_pdf_merge_split(tmp_path):
    a = make_pdf(tmp_path / "a.pdf", ["1"])
    b = make_pdf(tmp_path / "b.pdf", ["2"])
    out = tmp_path / "ab.pdf"
    assert main(["pdf", "merge", str(a), str(b), "-o", str(out)]) == 0
    assert main(["pdf", "split", str(out), "-o", str(tmp_path / "pages")]) == 0
    assert len(list((tmp_path / "pages").iterdir())) == 2
