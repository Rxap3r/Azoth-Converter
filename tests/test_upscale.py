"""AI enlarging and enhancing (upscale.py, its use in resize.py, the converter and the CLI)."""

import io
import pickle
import sys
import threading
import zipfile
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageDraw

from azoth import resize, upscale
from azoth.cli import main
from azoth.converters import ConversionError
from azoth.engine import Engine
from azoth.resize import FIT, PERCENT, Resize, ResizeError

pytestmark = pytest.mark.usefixtures("upscale_ready")


@pytest.fixture(scope="module")
def engine():
    return Engine()


def _scene(size=(72, 56), seed=0) -> Image.Image:
    """A small made-up photo: soft colours, sharp shapes and a little noise."""
    w, h = size
    img = Image.new("RGB", size, (90, 140, 200))
    draw = ImageDraw.Draw(img)
    draw.ellipse((w // 6, h // 5, w // 2, h * 4 // 5), fill=(230, 180, 40))
    draw.rectangle((w // 2, h // 3, w - 4, h - 6), fill=(30, 40, 50))
    draw.line((0, h - 1, w, 0), fill=(250, 250, 250), width=2)
    noise = np.random.default_rng(seed).normal(0, 6, (h, w, 3))
    return Image.fromarray(np.clip(np.asarray(img) + noise, 0, 255).astype(np.uint8))


def _reference(rgb: np.ndarray, layers) -> np.ndarray:
    """The network in plain numpy (independent of OpenCV and of the ONNX file), as
    Real-ESRGAN's SRVGGNetCompact defines it."""
    x = rgb
    for w, b, slope in layers:
        h, wd, c = x.shape
        padded = np.pad(x, ((1, 1), (1, 1), (0, 0)))
        out = np.tile(b, (h, wd, 1)).astype(np.float64)
        for ky in range(3):
            for kx in range(3):
                out += padded[ky : ky + h, kx : kx + wd] @ w[:, :, ky, kx].T
        x = out if slope is None else np.where(out >= 0, out, out * slope)
    h, wd, _ = rgb.shape
    x = x.reshape(h, wd, 3, 4, 4).transpose(0, 3, 1, 4, 2).reshape(h * 4, wd * 4, 3)
    return x + rgb.repeat(4, 0).repeat(4, 1)


def _u8(a: np.ndarray) -> np.ndarray:
    return np.clip(a * 255 + 0.5, 0, 255).astype(np.uint8)


# --- the network ---------------------------------------------------------------------


def test_model_has_the_expected_layers():
    layers = upscale.load_weights()
    assert len(layers) == 34  # first conv, 32 middle convs, last conv
    assert layers[0][0].shape == (64, 3, 3, 3) and layers[-1][0].shape == (48, 64, 3, 3)
    assert all(slope is not None for _w, _b, slope in layers[:-1]) and layers[-1][2] is None


def test_network_matches_the_reference():
    rgb = np.asarray(_scene((23, 17)), np.float32) / 255
    layers = upscale.load_weights(0.5)
    net = upscale._net(0.5)
    got = upscale.upscale4(net, rgb)
    assert got.shape == (68, 92, 3)
    assert np.abs(got - _reference(rgb.astype(np.float64), layers)).max() < 1e-3


def test_noise_removal_levels_differ():
    # An even grey with noise: the higher the level, the smoother the result.
    noise = np.random.default_rng(1).normal(0, 10, (40, 48))
    noisy = Image.fromarray(np.clip(128 + noise, 0, 255).astype(np.uint8)).convert("RGB")
    spread = [
        np.asarray(upscale.enhance(noisy, (48, 40), level), float).std()
        for level in ("low", "medium", "high")
    ]
    assert spread[0] > spread[1] > spread[2]


def test_tiles_and_strips_fit_together_without_seams(monkeypatch):
    img = _scene((70, 54))
    whole = _u8(upscale.upscale4(upscale._net(0.5), np.asarray(img, np.float32) / 255))
    monkeypatch.setattr(upscale, "TILE", 24)  # many small tiles
    tiled = np.asarray(upscale.enhance(img, (280, 216)))
    assert np.abs(tiled.astype(int) - whole).max() <= 2
    # Other sizes: each strip is resized on its own, but must match one big resize.
    for size, method in (((150, 116), Image.LANCZOS), ((420, 324), Image.BICUBIC)):
        expected = np.asarray(Image.fromarray(whole).resize(size, method)).astype(int)
        got = np.asarray(upscale.enhance(img, size)).astype(int)
        assert np.abs(got - expected).max() <= 3, size


def test_ai_is_sharper_than_plain_enlarging():
    """Shrink a sharp picture, then enlarge it again: the AI result must be closer to the
    sharp original's edges than smooth (bicubic) enlarging."""
    sharp = Image.new("L", (192, 192), 255)
    draw = ImageDraw.Draw(sharp)
    for i in range(6):
        draw.rectangle((16 + 28 * i, 20, 28 + 28 * i, 172), fill=0)
    small = sharp.resize((48, 48), Image.LANCZOS)
    plain = small.resize((192, 192), Image.BICUBIC)
    ai = resize.apply(small, Resize(PERCENT, percent=400, ai=True))
    assert ai.mode == "L" and ai.size == (192, 192)

    def edge_strength(im):
        return np.abs(np.diff(np.asarray(im, float), axis=1)).max(axis=1).mean()

    assert edge_strength(ai) > 1.3 * edge_strength(plain)


# --- pictures of every kind ----------------------------------------------------------


@pytest.mark.parametrize("mode", ["RGB", "RGBA", "L", "LA", "P", "1", "CMYK"])
def test_every_normal_picture_mode_works(mode):
    img = _scene((20, 16)).convert(mode)
    out = resize.apply(img, Resize(PERCENT, percent=200, ai=True))
    assert out.size == (40, 32)
    assert ("A" in out.getbands()) == ("A" in img.getbands())


def test_16_bit_pictures_are_refused_with_a_clear_message():
    with pytest.raises(ResizeError, match="8 bits"):
        resize.apply(Image.new("I;16", (8, 8)), Resize(PERCENT, percent=200, ai=True))


def test_transparent_edges_get_no_dark_fringe():
    # A white disc on fully transparent black: the visible edge must stay white.
    img = Image.new("RGBA", (40, 40), (0, 0, 0, 0))
    ImageDraw.Draw(img).ellipse((8, 8, 32, 32), fill=(255, 255, 255, 255))
    out = np.asarray(resize.apply(img, Resize(PERCENT, percent=200, ai=True)))
    visible = out[..., 3] > 32
    assert out[visible][:, :3].min() >= 200


def test_smaller_pictures_dont_use_ai():
    spec = Resize(PERCENT, percent=50, ai=True)
    assert not resize.uses_ai(spec, 100, 80)
    assert resize.uses_ai(Resize(PERCENT, percent=100, ai=True), 100, 80)
    assert not resize.uses_ai(Resize(FIT, width=50, height=50, ai=True), 100, 80)
    # "Don't enlarge smaller pictures": they stay exactly as they are, no AI either.
    assert not resize.uses_ai(Resize(FIT, width=500, height=500, enlarge=False, ai=True), 100, 80)


def test_unknown_noise_level_is_refused():
    with pytest.raises(ResizeError):
        Resize(PERCENT, percent=200, ai=True, denoise="extreme")


def test_progress_and_cancel(monkeypatch):
    monkeypatch.setattr(upscale, "TILE", 16)
    seen = []
    stop = threading.Event()

    def cancelled():
        if stop.is_set():
            raise upscale.Cancelled

    def progress(f):
        seen.append(f)
        stop.set()

    with pytest.raises(upscale.Cancelled):
        upscale.enhance(_scene((60, 40)), (240, 160), progress=progress, cancelled=cancelled)
    assert seen and 0 < seen[0] < 1


def test_missing_model_gives_a_readable_message(monkeypatch, tmp_path):
    monkeypatch.setattr(upscale, "MODEL_FILE", tmp_path / "missing.npz")
    with pytest.raises(ResizeError, match="reinstall"):
        resize.apply(_scene((8, 8)), Resize(PERCENT, percent=200, ai=True))


# --- converting ----------------------------------------------------------------------


def test_enhance_in_the_same_size_and_format(engine, tmp_path):
    src = tmp_path / "p.png"
    _scene((40, 30)).save(src)
    before = src.read_bytes()
    spec = Resize(PERCENT, percent=100, ai=True)
    out = engine.convert(src, "png", options={"resize": spec})
    assert out.outputs == [tmp_path / "p (enhanced).png"]
    assert src.read_bytes() == before
    with Image.open(out.outputs[0]) as im:
        assert im.size == (40, 30)
    assert any("invented by the AI" in n for n in out.notes)


def test_cancel_stops_ai_while_converting(engine, tmp_path):
    src = tmp_path / "p.png"
    _scene((300, 60)).save(src)
    cancel = threading.Event()

    def progress(fraction, message):
        if message == "Enhancing with AI" and fraction > 0:
            cancel.set()

    spec = Resize(PERCENT, percent=200, ai=True)
    with pytest.raises(ConversionError, match="cancelled"):
        engine.convert(
            src, "jpg", tmp_path / "o", options={"resize": spec},
            progress=progress, cancel_event=cancel,
        )  # fmt: skip
    assert not any((tmp_path / "o").glob("*"))


def test_cli_ai(tmp_path, capsys):
    src = tmp_path / "p.jpg"
    _scene((30, 20)).save(src)
    assert main(["convert", str(src), "--to", "png", "--resize", "200%", "--ai", "-q"]) == 0
    with Image.open(tmp_path / "p.png") as im:
        assert im.size == (60, 40)
    args = ["convert", str(src), "--to", "jpg", "--ai", "--denoise", "high", "-q"]
    assert main(args) == 0
    with Image.open(tmp_path / "p (enhanced).jpg") as im:
        assert im.size == (30, 20)
    assert main(["convert", str(src), "--to", "png", "--denoise", "low"]) == 2
    assert "--denoise needs --ai" in capsys.readouterr().err


# --- the build script that makes the model file ----------------------------------------


def _fetch_script():
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "packaging"))
    try:
        import fetch_upscale_model
    finally:
        sys.path.pop(0)
    return fetch_upscale_model


def test_model_reader_runs_no_code_from_the_file(tmp_path):
    class Evil:
        def __reduce__(self):
            return (print, ("this must never run",))

    path = tmp_path / "evil.pth"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("archive/data.pkl", pickle.dumps({"params": Evil()}, protocol=2))
    with pytest.raises(pickle.UnpicklingError, match="not allowed"):
        _fetch_script().read_pth(path)


def test_model_reader_reads_plain_weights(tmp_path):
    """A file shaped like PyTorch's: tensors are rebuilt from raw little-endian floats."""
    data = np.arange(6, dtype="<f4")
    # Hand-written pickle: {"params": OrderedDict(w=_rebuild_tensor_v2(storage, 0, (2, 3),
    # (3, 1)))}, with the storage as a persistent id, as torch.save writes it.
    pkl = (
        b"\x80\x02}X\x06\x00\x00\x00paramsccollections\nOrderedDict\n)R(X\x01\x00\x00\x00w"
        b"ctorch._utils\n_rebuild_tensor_v2\n((X\x07\x00\x00\x00storagectorch\nFloatStorage\n"
        b"X\x01\x00\x00\x000X\x03\x00\x00\x00cpuK\x06tQK\x00K\x02K\x03\x86K\x03K\x01\x86\x89"
        b"ccollections\nOrderedDict\n)RtRus."
    )
    path = tmp_path / "ok.pth"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("archive/data.pkl", pkl)
        z.writestr("archive/data/0", data.tobytes())
    weights = _fetch_script().read_pth(path)
    assert np.array_equal(weights["w"], data.reshape(2, 3))


def test_model_file_holds_only_numbers():
    with np.load(upscale.MODEL_FILE, allow_pickle=False) as data:
        names = data.files
        assert all(data[n].dtype.kind in "fU" for n in names)
    assert {n.split("/")[0] for n in names} == {"strong", "grain", "sources"}
    assert upscale.MODEL_FILE.stat().st_size < 6_000_000  # keeps the download small


def test_onnx_file_is_valid_protobuf_shape():
    """Spot check of the hand-written ONNX: OpenCV reads it (the other tests run it) and
    it names the operators the network needs."""
    model = upscale.onnx_model(upscale.load_weights())
    for op in (b"Conv", b"PRelu", b"DepthToSpace", b"CRD"):
        assert op in model
    assert io.BytesIO(model).getbuffer().nbytes > 4_000_000
