"""Changing the picture size (resize.py, the image converter, the engine and the CLI)."""

import pytest
from PIL import Image

from azoth import resize
from azoth.cli import main
from azoth.converters import ConversionError
from azoth.engine import Engine
from azoth.resize import FIT, HEIGHT, LONGEST, PERCENT, WIDTH, Resize, ResizeError, parse


@pytest.fixture(scope="module")
def engine():
    return Engine()


def _photo(path, size=(400, 300), **save):
    Image.new("RGB", size, (200, 30, 30)).save(path, **save)
    return path


# --- sizes ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "spec, size, expected",
    [
        (Resize(PERCENT, percent=50), (400, 300), (200, 150)),
        (Resize(PERCENT, percent=200), (400, 300), (800, 600)),  # a percentage says it all
        (Resize(LONGEST, width=200), (400, 300), (200, 150)),
        (Resize(LONGEST, width=200), (300, 400), (150, 200)),  # portrait
        (Resize(WIDTH, width=100), (400, 300), (100, 75)),
        (Resize(HEIGHT, height=100), (400, 300), (133, 100)),
        (Resize(FIT, width=100, height=100), (400, 300), (100, 75)),
        (Resize(FIT, width=1000, height=150), (400, 300), (200, 150)),
        (Resize(LONGEST, width=800), (400, 300), (800, 600)),  # smaller ones get bigger
        (Resize(LONGEST, width=2000, enlarge=False), (400, 300), (400, 300)),  # unless off
        (Resize(FIT, width=1920, height=1080), (3000, 4000), (1080, 1440)),  # portrait: box turned
        (Resize(WIDTH, width=1), (400, 3), (1, 1)),  # at least one pixel
    ],
)
def test_new_size_keeps_proportions(spec, size, expected):
    assert spec.new_size(*size) == expected


def test_would_enlarge():
    assert Resize(LONGEST, width=2000, enlarge=False).would_enlarge(400, 300)
    assert not Resize(LONGEST, width=400, enlarge=False).would_enlarge(400, 300)
    assert not Resize(LONGEST, width=2000).would_enlarge(400, 300)


@pytest.mark.parametrize(
    "text, expected",
    [
        ("50%", Resize(PERCENT, percent=50)),
        ("12.5 %", Resize(PERCENT, percent=12.5)),
        ("2000", Resize(LONGEST, width=2000)),
        ("1920x1080", Resize(FIT, width=1920, height=1080)),
        ("1920×1080", Resize(FIT, width=1920, height=1080)),
        ("1920x", Resize(WIDTH, width=1920)),
        ("x1080", Resize(HEIGHT, height=1080)),
    ],
)
def test_parse(text, expected):
    assert parse(text) == expected


@pytest.mark.parametrize("text", ["", "x", "big", "-5", "0", "0%", "900%", "70000", "10x0"])
def test_parse_rejects_bad_sizes(text):
    with pytest.raises(ResizeError):
        parse(text)


def test_too_many_pixels_is_refused():
    img = Image.new("L", (100, 100))
    with pytest.raises(ResizeError, match="too large"):
        resize.apply(img, Resize(FIT, width=60000, height=60000, enlarge=True))


def test_same_size_returns_the_same_picture():
    img = Image.new("RGB", (40, 30))
    assert resize.apply(img, Resize(LONGEST, width=40)) is img
    assert resize.apply(img, None) is img


def test_transparent_edges_get_no_dark_fringe():
    # Half transparent black, half opaque white: when made smaller, the edge must stay
    # white (premultiplied alpha), not turn grey from the invisible black pixels.
    img = Image.new("RGBA", (100, 100), (0, 0, 0, 0))
    img.paste(Image.new("RGBA", (50, 100), (255, 255, 255, 255)), (50, 0))
    small = resize.apply(img, Resize(PERCENT, percent=10))
    r, g, b, a = small.getpixel((5, 5))
    assert a > 0 and min(r, g, b) >= 250


@pytest.mark.parametrize("mode", ["P", "1", "L", "LA", "RGBA", "I;16", "CMYK"])
def test_every_picture_mode_can_be_resized(mode):
    img = Image.new(mode, (64, 48))
    assert resize.apply(img, Resize(PERCENT, percent=50)).size == (32, 24)


# --- converting ----------------------------------------------------------------------


def test_resize_while_converting(engine, tmp_path):
    src = _photo(tmp_path / "p.jpg", (4000, 3000))
    out = engine.convert(src, "png", tmp_path / "o", options={"resize": parse("1000")})
    with Image.open(out.outputs[0]) as im:
        assert im.size == (1000, 750)


def test_resize_in_the_same_format_makes_a_copy(engine, tmp_path):
    src = _photo(tmp_path / "p.jpg")
    before = src.read_bytes()
    out = engine.convert(src, "jpg", options={"resize": parse("50%")})
    assert out.outputs == [tmp_path / "p (resized).jpg"]
    assert src.read_bytes() == before  # the original is never touched
    with Image.open(out.outputs[0]) as im:
        assert im.size == (200, 150)
    assert any("saves the picture again" in n for n in out.notes)  # JPG is lossy: say so
    again = engine.convert(src, "jpg", options={"resize": parse("50%")})
    assert again.outputs == [tmp_path / "p (resized) (1).jpg"]  # never overwritten


def test_same_format_without_a_size_is_refused(engine, tmp_path):
    src = _photo(tmp_path / "p.png")
    with pytest.raises(ConversionError, match="The format of p.png is"):
        engine.convert(src, "png")


def test_size_is_refused_where_it_cannot_apply(engine, tmp_path, sample_pdf):
    with pytest.raises(ConversionError, match="picture size"):
        engine.convert(_photo(tmp_path / "p.png"), "pdf", options={"resize": parse("50%")})
    with pytest.raises(ConversionError, match="picture size"):
        engine.convert(sample_pdf, "png", options={"resize": parse("50%")})
    assert engine.can_resize("png", "jpg") and engine.can_resize("png", "png")
    assert not engine.can_resize("pdf", "png") and not engine.can_resize("png", "pdf")


def test_smaller_pictures_stay_and_the_user_is_told(engine, tmp_path):
    src = _photo(tmp_path / "small.png", (300, 200))
    out = engine.convert(src, "webp", options={"resize": parse("1000", enlarge=False)})
    with Image.open(out.outputs[0]) as im:
        assert im.size == (300, 200)
    assert any("already smaller" in w for w in out.warnings)
    bigger = engine.convert(src, "webp", options={"resize": parse("1000")})
    with Image.open(bigger.outputs[0]) as im:
        assert im.size == (1000, 667)  # by default, smaller pictures get the size too


def test_width_means_the_upright_picture(engine, tmp_path):
    # Stored sideways (600 × 400) with EXIF "rotate 90°": the user sees 400 × 600.
    exif = Image.Exif()
    exif[0x0112] = 6
    src = _photo(tmp_path / "turned.jpg", (600, 400), exif=exif)
    out = engine.convert(src, "png", options={"resize": parse("200x")})
    with Image.open(out.outputs[0]) as im:
        assert im.size == (200, 300)


def test_metadata_still_removed_and_kept_exif_is_updated(engine, tmp_path):
    exif = Image.Exif()
    exif[0x010F] = "SecretCamera"
    exif.get_ifd(0x8769)[0xA002] = 400  # pixel width the camera wrote
    src = _photo(tmp_path / "p.jpg", exif=exif)
    out = engine.convert(src, "jpg", options={"resize": parse("50%")})
    with Image.open(out.outputs[0]) as im:
        assert not im.getexif()
    kept = engine.convert(src, "jpg", options={"resize": parse("50%"), "keep_metadata": True})
    with Image.open(kept.outputs[0]) as im:
        assert im.getexif()[0x010F] == "SecretCamera"
        assert 0xA002 not in im.getexif().get_ifd(0x8769)  # the old size would be wrong


def test_animated_gif_resizes_every_frame(engine, tmp_path):
    frames = [Image.new("RGB", (80, 60), c) for c in ("red", "green", "blue")]
    src = tmp_path / "anim.gif"
    frames[0].save(src, save_all=True, append_images=frames[1:], duration=100, loop=0)
    out = engine.convert(src, "webp", options={"resize": parse("50%")})
    with Image.open(out.outputs[0]) as im:
        assert im.size == (40, 30) and im.n_frames == 3


def test_resize_several_files_at_once(engine, tmp_path):
    sources = [_photo(tmp_path / f"p{i}.png", (100 * (i + 1), 100)) for i in range(4)]
    results = dict(engine.convert_many(sources, "jpg", options={"resize": parse("x50")}))
    for i in range(4):
        with Image.open(results[i].outputs[0]) as im:
            assert im.size == (50 * (i + 1), 50)


# --- command line --------------------------------------------------------------------


def test_cli_resize(tmp_path):
    src = _photo(tmp_path / "p.jpg")
    out = tmp_path / "o"
    assert main(["convert", str(src), "--to", "png", "--resize", "100", "-o", str(out), "-q"]) == 0
    with Image.open(out / "p.png") as im:
        assert im.size == (100, 75)
    args = ["convert", str(src), "--to", "jpg", "--resize", "800", "-q"]
    assert main(args) == 0
    with Image.open(tmp_path / "p (resized).jpg") as im:
        assert im.size == (800, 600)
    assert main([*args, "--only-shrink"]) == 0
    with Image.open(tmp_path / "p (resized) (1).jpg") as im:
        assert im.size == (400, 300)


def test_cli_rejects_bad_sizes(tmp_path, capsys):
    src = _photo(tmp_path / "p.jpg")
    assert main(["convert", str(src), "--to", "png", "--resize", "huge"]) == 2
    assert "not a size" in capsys.readouterr().err
    assert main(["convert", str(src), "--to", "png", "--only-shrink"]) == 2


def test_the_new_size_is_reported(engine, tmp_path):
    src = _photo(tmp_path / "p.png", (400, 300))
    out = engine.convert(src, "jpg", options={"resize": parse("200")})
    assert "New size: 200 × 150 px (was 400 × 300 px)." in out.notes


def test_all_image_readers_are_loaded_up_front():
    """Loading a format reader while photos are opened in parallel threads crashed the
    packaged app; images.py loads them all when it is imported."""
    from PIL import Image

    import azoth.converters.images  # noqa: F401

    assert Image._initialized == 2


def test_picture_size_as_shown(tmp_path):
    assert resize.picture_size(_photo(tmp_path / "p.png", (640, 480))) == (640, 480)
    exif = Image.Exif()
    exif[0x0112] = 6  # stored sideways: shown 300 × 400
    assert resize.picture_size(_photo(tmp_path / "t.jpg", (400, 300), exif=exif)) == (300, 400)
    # PNG: EXIF is found without decoding the picture (fast for big screenshots)
    assert resize.picture_size(_photo(tmp_path / "t.png", (400, 300), exif=exif)) == (300, 400)
    broken = tmp_path / "broken.jpg"
    broken.write_bytes(b"not a picture")
    assert resize.picture_size(broken) is None
