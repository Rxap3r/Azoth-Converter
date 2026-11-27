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


def _ico_sizes(path):
    """The sizes in the icon's list, in the order they are stored."""
    data = path.read_bytes()
    count = int.from_bytes(data[4:6], "little")
    return [data[6 + 16 * i] or 256 for i in range(count)]


@pytest.mark.parametrize("size", [(300, 200), (1000, 20), (20, 1000)])
def test_ico_from_non_square_picture_is_square_with_all_sizes(tmp_path, size):
    src = tmp_path / "logo.png"
    Image.new("RGB", size, "red").save(src)
    [out] = Engine().convert(src, "ico", tmp_path / "out").outputs
    assert _ico_sizes(out) == [256, 128, 64, 48, 32, 24, 16]  # largest first
    with Image.open(out) as im:
        assert im.size == (256, 256)
        rgba = im.convert("RGBA")
        assert rgba.getpixel((0, 0))[3] == 0  # transparent border, nothing distorted
        assert rgba.getpixel((128, 128))[:3] == (255, 0, 0)  # the picture in the centre


def test_ico_from_small_picture_keeps_its_size(tmp_path):
    for side, expected in ((100, [100, 64, 48, 32, 24, 16]), (10, [10])):
        src = tmp_path / f"small{side}.png"
        Image.new("RGB", (side, side), "red").save(src)
        result = Engine().convert(src, "ico", tmp_path / "out")
        assert _ico_sizes(result.outputs[0]) == expected
        assert any("Picture size" in n for n in result.notes)


def test_ico_can_be_made_larger(tmp_path):
    from azoth import resize

    src = tmp_path / "small.ico"
    Image.new("RGBA", (16, 16), "red").save(src)
    out_dir = tmp_path / "out"
    result = Engine().convert(src, "ico", out_dir, options={"resize": resize.parse("256")})
    assert _ico_sizes(result.outputs[0]) == [256, 128, 64, 48, 32, 24, 16]


def test_ico_is_written_like_windows_icons(tmp_path):
    """Largest first (in the list and in the file), 1 plane, 32 bits, classic bitmaps
    below 256 px and PNG for 256 px, so that each program (also the Photos app) can read it."""
    src = tmp_path / "pic.png"
    Image.new("RGBA", (300, 300), (200, 30, 30, 255)).save(src)
    [out] = Engine().convert(src, "ico", tmp_path / "out").outputs
    data = out.read_bytes()
    offsets = []
    for i, side in enumerate([256, 128, 64, 48, 32, 24, 16]):
        entry = data[6 + 16 * i : 22 + 16 * i]
        assert (entry[0] or 256) == side
        assert int.from_bytes(entry[4:6], "little") == 1  # planes
        assert int.from_bytes(entry[6:8], "little") == 32  # bits per pixel
        offset = int.from_bytes(entry[12:16], "little")
        offsets.append(offset)
        start = data[offset : offset + 4]
        assert start == (b"\x89PNG" if side == 256 else (40).to_bytes(4, "little"))
    assert offsets == sorted(offsets)
    with Image.open(out) as im:
        for side in (16, 48, 256):
            im.size = (side, side)
            im.load()
            assert im.convert("RGBA").getpixel((side // 2, side // 2)) == (200, 30, 30, 255)
