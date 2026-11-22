"""PDF tools: compress and passwords. Safe with originals, honest about results."""

from __future__ import annotations

import hashlib
import io
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pymupdf
import pytest
from PIL import Image

from azoth import pdf_tools, quality
from azoth.cli import main as cli
from azoth.converters import ConversionError

SAMPLES = Path(__file__).resolve().parent.parent / "samples" / "pdf"


def _photo(width, height, seed=1):
    rng = np.random.default_rng(seed)
    x = np.linspace(0, 1, width)[None, :, None]
    y = np.linspace(0, 1, height)[:, None, None]
    pixels = np.sin(x * 20 + y * 7) * 80 + 120 + rng.normal(0, 25, (height, width, 3))
    return Image.fromarray(pixels.clip(0, 255).astype("uint8"))


def _encoded(image, fmt, **kw):
    buf = io.BytesIO()
    image.save(buf, fmt, **kw)
    return buf.getvalue()


BIG = pymupdf.Rect(50, 50, 250, 183)  # 3000 px on 200 pt = 1080 dpi
SMALL = pymupdf.Rect(50, 200, 350, 400)  # 300 px on 300 pt = 72 dpi
LOSSLESS = pymupdf.Rect(50, 420, 250, 553)  # 1500 px on 200 pt = 540 dpi


def make_photo_pdf(path, big=True):
    """A page with an oversized JPG photo, a small JPG, an oversized lossless picture,
    text, a link, a bookmark and a form field. ``big=False``: only the small JPG."""
    doc = pymupdf.open()
    page = doc.new_page()
    if big:
        page.insert_image(BIG, stream=_encoded(_photo(3000, 2000), "JPEG", quality=95))
    page.insert_image(SMALL, stream=_encoded(_photo(300, 200, 2), "JPEG", quality=90))
    if big:
        page.insert_image(LOSSLESS, stream=_encoded(_photo(1500, 1000, 3), "PNG"))
    page.insert_text((50, 600), "Annual report 2026", fontsize=14)
    page.insert_link({"kind": pymupdf.LINK_URI, "from": pymupdf.Rect(50, 620, 200, 640),
                      "uri": "https://example.com/"})  # fmt: skip
    widget = pymupdf.Widget()
    widget.field_name, widget.field_type = "name", pymupdf.PDF_WIDGET_TYPE_TEXT
    widget.rect, widget.field_value = pymupdf.Rect(50, 660, 250, 680), "Jane"
    page.add_widget(widget)
    doc.set_toc([[1, "Start", 1]])
    doc.set_metadata({"title": "Report", "author": "Example Author"})
    notes = doc.new_page()  # a page of text, saved unpacked like simple programs do
    for line in range(60):
        notes.insert_text((50, 40 + line * 12), f"Note {line}: " + "lorem ipsum " * 8, fontsize=9)
    doc.save(path)
    doc.close()
    return path


def pictures(path):
    """(position, kind, width, height, sha) of every picture, in drawing order."""
    with pymupdf.open(path) as doc:
        result = []
        for page in doc:
            for info in page.get_image_info(xrefs=True):
                data = doc.extract_image(info["xref"])
                sha = hashlib.sha256(data["image"]).hexdigest()
                result.append((tuple(round(v) for v in info["bbox"]), data["ext"],
                               info["width"], info["height"], sha))  # fmt: skip
        return result


def renders(path, dpi=50):
    with pymupdf.open(path) as doc:
        return [np.frombuffer(p.get_pixmap(dpi=dpi).samples, np.uint8).astype(int) for p in doc]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def everything_but_pictures(path):
    with pymupdf.open(path) as doc:
        page = doc[0]
        return (
            doc.page_count,
            page.get_text(),
            [link["uri"] for link in page.get_links()],
            doc.get_toc(),
            [(w.field_name, w.field_value) for w in page.widgets()],
            {k: doc.metadata[k] for k in ("title", "author")},
        )


@pytest.fixture
def photo_pdf(tmp_path):
    return make_photo_pdf(tmp_path / "report.pdf")


# --- compress ----------------------------------------------------------------------


@pytest.mark.parametrize("level", [lvl.id for lvl in quality.COMPRESS_LEVELS])
def test_compress_keeps_text_links_bookmarks_and_forms(photo_pdf, tmp_path, level, private_tmp):
    if level == "light":  # big photos leave little to tidy up; use a mostly-text PDF
        photo_pdf = make_photo_pdf(tmp_path / "text.pdf", big=False)
    original = sha(photo_pdf)
    out = pdf_tools.compress(photo_pdf, tmp_path / "out.pdf", level)
    assert out.stat().st_size < photo_pdf.stat().st_size
    assert everything_but_pictures(out) == everything_but_pictures(photo_pdf)
    assert sha(photo_pdf) == original  # the original is never touched
    assert list(private_tmp.iterdir()) == []  # temporary files are gone


def test_light_keeps_every_picture_byte_for_byte(tmp_path):
    photo_pdf = make_photo_pdf(tmp_path / "text.pdf", big=False)
    out = pdf_tools.compress(photo_pdf, tmp_path / "out.pdf", "light")
    assert pictures(out) == pictures(photo_pdf)
    assert all((a == b).all() for a, b in zip(renders(out), renders(photo_pdf), strict=True))


def test_balanced_shrinks_only_oversized_pictures_and_keeps_png_lossless(photo_pdf, tmp_path):
    before = pictures(photo_pdf)
    out = pdf_tools.compress(photo_pdf, tmp_path / "out.pdf", "balanced")
    after = pictures(out)
    assert out.stat().st_size < photo_pdf.stat().st_size / 4
    big, small, lossless = after
    assert big[1] == "jpeg" and big[2] < 3000
    assert small == before[1]  # small photo: same bytes, not re-saved as a worse JPG
    assert lossless[1] == "png" and lossless[2] < 1500  # smaller, but still lossless
    assert big[0] == before[0][0] and lossless[0] == before[2][0]  # same place on the page


def test_strong_turns_lossless_pictures_into_jpg(photo_pdf, tmp_path):
    out = pdf_tools.compress(photo_pdf, tmp_path / "out.pdf", "strong")
    big, small, lossless = pictures(out)
    assert lossless[1] == "jpeg"
    assert small == pictures(photo_pdf)[1]
    assert out.stat().st_size < pdf_tools.compress(photo_pdf, tmp_path / "b.pdf").stat().st_size


@pytest.mark.parametrize("level", ["balanced", "strong"])
def test_compressed_pages_still_look_the_same(photo_pdf, tmp_path, level):
    out = pdf_tools.compress(photo_pdf, tmp_path / "out.pdf", level)
    for a, b in zip(renders(photo_pdf), renders(out), strict=True):
        assert np.abs(a - b).mean() < 3  # only tiny differences in the photos


def test_black_and_white_scans_are_not_touched(tmp_path):
    scan = Image.fromarray(np.random.default_rng(4).random((3300, 2550)) > 0.5).convert("1")
    src = tmp_path / "scan.pdf"
    doc = pymupdf.open()
    doc.new_page().insert_image(pymupdf.Rect(0, 0, 612, 792), stream=_encoded(scan, "PNG"))
    doc.save(src)
    doc.close()
    try:
        out = pdf_tools.compress(src, tmp_path / "out.pdf", "strong")
    except pdf_tools.NotSmaller:
        return
    [(_, _, width, height, _)] = pictures(out)
    assert (width, height) == (2550, 3300)


def test_pictures_with_transparency_keep_it(tmp_path):
    rgba = _photo(2000, 2000).convert("RGBA")
    rgba.putalpha(Image.linear_gradient("L").resize((2000, 2000)))
    src = tmp_path / "logo.pdf"
    doc = pymupdf.open()
    doc.new_page().insert_image(pymupdf.Rect(50, 50, 250, 250), stream=_encoded(rgba, "PNG"))
    doc.save(src)
    doc.close()
    out = pdf_tools.compress(src, tmp_path / "out.pdf", "strong")
    with pymupdf.open(out) as result:
        [image] = result[0].get_images(full=True)
        assert image[1] > 0  # still has its transparency mask
    for a, b in zip(renders(src), renders(out), strict=True):
        assert np.abs(a - b).mean() < 3


def test_nothing_is_saved_when_it_would_not_get_smaller(photo_pdf, tmp_path):
    once = pdf_tools.compress(photo_pdf, tmp_path / "once.pdf", "strong")
    with pytest.raises(pdf_tools.NotSmaller, match="Nothing was saved"):
        pdf_tools.compress(once, tmp_path / "twice.pdf", "strong")
    assert not (tmp_path / "twice.pdf").exists()


def test_not_smaller_suggests_a_stronger_level(tmp_path):
    src = tmp_path / "tiny.pdf"
    doc = pymupdf.open()
    doc.new_page()
    doc.save(src, garbage=4, deflate=True, use_objstms=1)
    doc.close()
    with pytest.raises(pdf_tools.NotSmaller, match="Try a stronger level"):
        pdf_tools.compress(src, tmp_path / "out.pdf", "light")


def test_compress_keeps_an_owners_restrictions(tmp_path):
    src = _restricted(tmp_path / "r.pdf")
    src.write_bytes(src.read_bytes() + b"\n%" + b"x" * 50_000 + b"\n")  # junk to tidy away
    out = pdf_tools.compress(src, tmp_path / "out.pdf", "light")
    assert pdf_tools.lock_state(out) == pdf_tools.RESTRICTED


def test_compress_never_overwrites(photo_pdf, tmp_path):
    existing = tmp_path / "out.pdf"
    existing.write_bytes(b"keep me")
    out = pdf_tools.compress(photo_pdf, existing)
    assert out != existing and existing.read_bytes() == b"keep me"
    assert pdf_tools.compress(photo_pdf, photo_pdf, overwrite=True) != photo_pdf


def test_compress_errors_are_readable(tmp_path):
    with pytest.raises(ConversionError, match="password"):
        pdf_tools.compress(SAMPLES / "password_protected_test123.pdf", tmp_path / "o.pdf")
    with pytest.raises(ConversionError, match="Unknown compression level"):
        pdf_tools.compress(SAMPLES / "invoice.pdf", tmp_path / "o.pdf", "extreme")


@pytest.mark.parametrize(
    "sample", sorted(p.name for p in SAMPLES.glob("*.pdf") if "pass" not in p.name)
)
def test_compress_sample_pdfs_without_visible_change(sample, tmp_path):
    src = SAMPLES / sample
    for level in ("light", "balanced"):
        try:
            out = pdf_tools.compress(src, tmp_path / f"{level}.pdf", level)
        except pdf_tools.NotSmaller:
            continue
        for a, b in zip(renders(src), renders(out), strict=True):
            assert np.abs(a - b).mean() < 1


def test_cli_compress(photo_pdf, capsys):
    assert cli(["pdf", "compress", str(photo_pdf), "--level", "strong"]) == 0
    out = photo_pdf.with_name("report (compressed).pdf")
    assert out.exists() and "smaller" in capsys.readouterr().out
    assert cli(["pdf", "compress", str(out), "--level", "strong", "-o", str(out)]) == 1
    assert "Nothing was saved" in capsys.readouterr().err


# --- passwords ---------------------------------------------------------------------

PASSWORD = "Grüezi Welt 2026!"


def test_add_password_locks_with_aes_256(photo_pdf, tmp_path, private_tmp):
    original = sha(photo_pdf)
    out = pdf_tools.add_password(photo_pdf, tmp_path / "locked.pdf", PASSWORD)
    assert pdf_tools.lock_state(out) == pdf_tools.NEEDS_PASSWORD
    with pymupdf.open(out) as doc:
        assert not doc.authenticate("wrong") and not doc.authenticate("")
    with pymupdf.open(out) as doc:
        assert doc.authenticate(PASSWORD)
        assert "AES" in doc.metadata["encryption"] and "256" in doc.metadata["encryption"]
        assert doc.permissions & pdf_tools._ALL_PERMISSIONS == pdf_tools._ALL_PERMISSIONS
    assert sha(photo_pdf) == original
    assert PASSWORD.encode() not in out.read_bytes()
    assert list(private_tmp.iterdir()) == []


def test_password_round_trip_keeps_everything(photo_pdf, tmp_path):
    locked = pdf_tools.add_password(photo_pdf, tmp_path / "locked.pdf", PASSWORD)
    unlocked = pdf_tools.remove_password(locked, tmp_path / "open.pdf", PASSWORD)
    assert pdf_tools.lock_state(unlocked) == pdf_tools.UNLOCKED
    assert everything_but_pictures(unlocked) == everything_but_pictures(photo_pdf)
    assert pictures(unlocked) == pictures(photo_pdf)  # photos byte for byte
    assert pdf_tools.lock_state(locked) == pdf_tools.NEEDS_PASSWORD  # original stays locked


@pytest.mark.skipif(not shutil.which("pdfinfo"), reason="poppler's pdfinfo not installed")
def test_other_pdf_readers_accept_the_password(photo_pdf, tmp_path):
    out = pdf_tools.add_password(photo_pdf, tmp_path / "locked.pdf", PASSWORD)
    good = subprocess.run(["pdfinfo", "-upw", PASSWORD, str(out)], capture_output=True, text=True)
    assert good.returncode == 0 and "AES-256" in good.stdout
    bad = subprocess.run(["pdfinfo", "-upw", "wrong", str(out)], capture_output=True, text=True)
    assert bad.returncode != 0


def test_wrong_password_saves_nothing(photo_pdf, tmp_path):
    locked = pdf_tools.add_password(photo_pdf, tmp_path / "locked.pdf", PASSWORD)
    with pytest.raises(ConversionError, match="isn't right"):
        pdf_tools.remove_password(locked, tmp_path / "open.pdf", "grüezi welt 2026!")
    with pytest.raises(ConversionError, match="Enter"):
        pdf_tools.remove_password(locked, tmp_path / "open.pdf", "")
    assert not (tmp_path / "open.pdf").exists()


def test_remove_password_from_sample_file(tmp_path):
    src = shutil.copy(SAMPLES / "password_protected_test123.pdf", tmp_path / "s.pdf")
    out = pdf_tools.remove_password(Path(src), pdf_tools.unlocked_path(Path(src)), "test123")
    assert out.name == "s (unlocked).pdf" and pdf_tools.lock_state(out) == pdf_tools.UNLOCKED
    assert pdf_tools.page_count(out) == pdf_tools.page_count(SAMPLES / "invoice.pdf")


def _restricted(path, user=""):
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), "Contract")
    doc.save(path, encryption=pymupdf.PDF_ENCRYPT_AES_256, owner_pw="boss", user_pw=user,
             permissions=pymupdf.PDF_PERM_ACCESSIBILITY)  # fmt: skip
    doc.close()
    return path


def test_restrictions_need_the_owner_password(tmp_path):
    src = _restricted(tmp_path / "r.pdf")
    assert pdf_tools.lock_state(src) == pdf_tools.RESTRICTED
    with pytest.raises(ConversionError, match="isn't right"):
        pdf_tools.remove_password(src, tmp_path / "o.pdf", "guess")
    out = pdf_tools.remove_password(src, tmp_path / "o.pdf", "boss")
    assert pdf_tools.lock_state(out) == pdf_tools.UNLOCKED


def test_open_password_alone_does_not_lift_owner_restrictions(tmp_path):
    src = _restricted(tmp_path / "r.pdf", user="reader")
    with pytest.raises(ConversionError, match="owner password"):
        pdf_tools.remove_password(src, tmp_path / "o.pdf", "reader")
    assert not (tmp_path / "o.pdf").exists()
    assert pdf_tools.lock_state(pdf_tools.remove_password(src, tmp_path / "o.pdf", "boss")) == (
        pdf_tools.UNLOCKED
    )


def test_password_tools_refuse_the_wrong_kind_of_file(photo_pdf, tmp_path):
    with pytest.raises(ConversionError, match="has no password"):
        pdf_tools.remove_password(photo_pdf, tmp_path / "o.pdf", "x")
    locked = pdf_tools.add_password(photo_pdf, tmp_path / "locked.pdf", PASSWORD)
    with pytest.raises(ConversionError, match="already has a password"):
        pdf_tools.add_password(locked, tmp_path / "twice.pdf", "another one 99!")
    with pytest.raises(ConversionError, match="already has a password"):
        pdf_tools.add_password(_restricted(tmp_path / "r.pdf"), tmp_path / "x.pdf", PASSWORD)
    with pytest.raises(ConversionError, match="damaged"):
        pdf_tools.lock_state(SAMPLES.parent / "other" / "broken_not_really.pdf")


def test_password_rules():
    assert pdf_tools.password_problem("") == "Enter a password."
    assert "space" in pdf_tools.password_problem(" secret")
    assert "too long" in pdf_tools.password_problem("ü" * 64)  # 128 bytes
    assert pdf_tools.password_problem("ü" * 63) is None
    for weak in ("1234", "password", "sommer26", "abcdefghijk"):
        assert pdf_tools.password_warning(weak), weak
    for good in ("Sommer2026!", "correct horse battery", PASSWORD):
        assert pdf_tools.password_warning(good) is None, good
    with pytest.raises(ConversionError, match="Enter a password"):
        pdf_tools.add_password(SAMPLES / "invoice.pdf", Path("never.pdf"), "")


def test_signed_pdfs_are_recognised(tmp_path):
    src = make_photo_pdf(tmp_path / "signed.pdf")
    with pymupdf.open(src) as doc:
        assert doc.get_sigflags() <= 0
        doc.xref_set_key(doc.pdf_catalog(), "AcroForm/SigFlags", "3")
        doc.save(tmp_path / "s2.pdf")
    assert not pdf_tools.is_signed(src)
    assert pdf_tools.is_signed(tmp_path / "s2.pdf")
    assert not pdf_tools.is_signed(SAMPLES / "password_protected_test123.pdf")


def test_cli_password_add_and_remove(photo_pdf, monkeypatch, capsys):
    answers = iter([PASSWORD, PASSWORD])
    monkeypatch.setattr("getpass.getpass", lambda prompt="": next(answers))
    assert cli(["pdf", "password", "add", str(photo_pdf)]) == 0
    locked = photo_pdf.with_name("report (protected).pdf")
    assert pdf_tools.lock_state(locked) == pdf_tools.NEEDS_PASSWORD
    assert PASSWORD not in capsys.readouterr().out

    answers = iter([PASSWORD, "typo"])
    assert cli(["pdf", "password", "add", str(photo_pdf)]) == 1
    assert "don't match" in capsys.readouterr().err

    answers = iter([PASSWORD])
    assert cli(["pdf", "password", "remove", str(locked)]) == 0
    assert pdf_tools.lock_state(locked.with_name("report (protected) (unlocked).pdf")) == (
        pdf_tools.UNLOCKED
    )
