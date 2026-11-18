import pytest
from PIL import Image

from azoth.converters.images import AVIF_SUPPORTED, HEIF_SUPPORTED
from azoth.engine import Engine

TARGETS = ["jpg", "png", "webp", "bmp", "tiff", "gif", "ico", "pdf"]
if HEIF_SUPPORTED:
    TARGETS.append("heic")
if AVIF_SUPPORTED:
    TARGETS.append("avif")


@pytest.mark.parametrize("target", [t for t in TARGETS if t != "png"])
def test_png_to_everything(sample_png, tmp_path, target):
    result = Engine().convert(sample_png, target, tmp_path / "out")
    [out] = result.outputs
    assert out.suffix == f".{'jpg' if target == 'jpg' else target}"
    assert out.stat().st_size > 0
    if target != "pdf":
        with Image.open(out) as im:
            assert im.size[0] > 0


def test_jpg_has_white_background(sample_png, tmp_path):
    [out] = Engine().convert(sample_png, "jpg", tmp_path).outputs
    with Image.open(out) as im:
        r, g, b = im.convert("RGB").getpixel((5, 5))
        assert min(r, g, b) > 240  # transparent corner became white


def _photo_with_gps(path, orientation=6):
    img = Image.new("RGB", (60, 30), "green")
    exif = Image.Exif()
    exif[0x010F] = "PhoneMaker"  # camera make
    exif[0x0112] = orientation  # rotate 90° when displayed
    gps = exif.get_ifd(0x8825)
    gps[2] = (47.0, 22.0, 0.0)  # latitude
    gps[4] = (8.0, 32.0, 0.0)  # longitude
    img.save(path, exif=exif)
    return path


@pytest.mark.parametrize("target", ["jpg", "png", "webp", "tiff"])
def test_metadata_removed_by_default(tmp_path, target):
    src = _photo_with_gps(tmp_path / "photo.jpg")
    [out] = Engine().convert(src, target if target != "jpg" else "png", tmp_path / "o").outputs
    if target == "jpg":  # also check jpg → png → jpg style re-encoding of a jpg
        [out] = Engine().convert(out, "jpg", tmp_path / "o2").outputs
    with Image.open(out) as im:
        exif = im.getexif()
        assert 0x8825 not in exif, "GPS data must be removed"
        assert 0x010F not in exif
        # EXIF orientation 6 is applied to the pixels, so width/height swap.
        assert im.size == (30, 60)


def test_metadata_kept_when_asked(tmp_path):
    src = _photo_with_gps(tmp_path / "photo.jpg")
    [out] = Engine().convert(src, "webp", tmp_path, options={"keep_metadata": True}).outputs
    with Image.open(out) as im:
        exif = im.getexif()
        assert exif.get(0x010F) == "PhoneMaker"
        assert exif.get(0x0112) == 1
        assert im.size == (30, 60)


def test_animated_gif_to_webp_keeps_frames(tmp_path):
    src = tmp_path / "anim.gif"
    frames = [Image.new("RGB", (20, 20), c) for c in ("red", "green", "blue")]
    frames[0].save(src, save_all=True, append_images=frames[1:], duration=100, loop=0)
    [out] = Engine().convert(src, "webp", tmp_path).outputs
    with Image.open(out) as im:
        assert im.n_frames == 3


@pytest.mark.skipif(not HEIF_SUPPORTED, reason="pillow-heif not installed")
def test_heic_to_jpg(sample_png, tmp_path):
    [heic] = Engine().convert(sample_png, "heic", tmp_path / "a").outputs
    [jpg] = Engine().convert(heic, "jpg", tmp_path / "b").outputs
    with Image.open(jpg) as im:
        assert im.format == "JPEG"
        assert im.size == (120, 80)
