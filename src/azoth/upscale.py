"""AI enlarging ("Enhance with AI"): pictures get bigger with plausible new detail, or keep
their size and come out sharper and with less noise and fewer JPEG blocks.

The model is Real-ESRGAN "general x4v3" (BSD-3-Clause, by Xintao Wang et al.), a small
network that makes pictures four times bigger. Its weights are in
``resources/upscale/realesr-general-x4v3.npz`` (created at build time by
``packaging/fetch_upscale_model.py``; plain numbers, no code). Two weight sets are in the
file: one that removes noise strongly and one that keeps fine grain; mixing them gives the
"Noise removal" levels, as the authors' own program does.

Everything runs on this computer with OpenCV's network engine (OpenCV is already part of
the app). Nothing is downloaded. The picture is worked on in tiles with some overlap, so big
pictures need little memory and the tiles fit together without seams, and the result is
shrunk to the chosen size strip by strip.

"Best quality (slow)" uses the bigger Real-ESRGAN "x4plus" (BSD-3-Clause, same authors,
``resources/upscale/realesrgan-x4plus.npz``): about 17 times more work, but more natural
texture (hair, fur, grass) when tiny pictures are made four times bigger. It has one weight
set, so the noise removal level doesn't apply to it.

AI-added detail is invented: it looks real but isn't. Never the default.
"""

from __future__ import annotations

import math
import struct
import threading
from collections.abc import Callable
from pathlib import Path

import numpy as np
from PIL import Image

MODEL_DIR = Path(__file__).resolve().parent / "resources" / "upscale"
MODEL_FILE = MODEL_DIR / "realesr-general-x4v3.npz"
BEST_MODEL_FILE = MODEL_DIR / "realesrgan-x4plus.npz"
SCALE = 4
TILE = 256
"""Tile size in source pixels. Bigger tiles are a little faster but need more memory."""
BEST_TILE = 128
"""Smaller tiles for the big model: it keeps 64 layers of the ×4 picture in memory."""
CONTEXT = 24
"""Source pixels around each tile that the network sees but that are cut off afterwards,
so tiles fit together without visible seams."""

LOW, MEDIUM, HIGH = "low", "medium", "high"
DENOISE = {LOW: 0.0, MEDIUM: 0.5, HIGH: 1.0}
"""Noise removal level → share of the strongly denoising weights."""
DENOISE_LABELS = {LOW: "Low (keeps fine grain)", MEDIUM: "Medium", HIGH: "High (smoothest)"}

_lock = threading.Lock()  # one AI picture at a time: it already uses all processor cores
_nets: dict[tuple[bool, float], object] = {}


class UpscaleError(RuntimeError):
    """AI enlarging is not possible. The message is shown to the user."""


class Cancelled(Exception):
    """Raised by ``cancelled`` callbacks to stop between tiles."""


def available(best: bool = False) -> bool:
    """True if the model (``best``: the big one) is there and OpenCV can run it."""
    if not (BEST_MODEL_FILE if best else MODEL_FILE).is_file():
        return False
    try:
        import cv2  # noqa: F401
    except ImportError:  # pragma: no cover - part of the app's dependencies
        return False
    return True


# --- the network ---------------------------------------------------------------------


def load_weights(
    denoise: float = DENOISE[MEDIUM],
) -> list[tuple[np.ndarray, np.ndarray, np.ndarray | None]]:
    """The layers as (weight [out, in, 3, 3], bias, PReLU slope or None), with the two
    weight sets mixed: ``denoise`` 1 = strong noise removal, 0 = keep grain."""
    if not 0 <= denoise <= 1:
        raise ValueError("denoise must be between 0 and 1")
    try:
        with np.load(MODEL_FILE, allow_pickle=False) as data:
            arrays = {
                name: data[name].astype(np.float32)
                for name in data.files
                if name.startswith(("strong/", "grain/"))
            }
    except OSError as exc:
        raise UpscaleError("The AI model is missing. Install Azoth Converter again.") from exc
    layers = []
    i = 0
    while f"strong/body.{i}.weight" in arrays:

        def mix(name: str) -> np.ndarray:
            return denoise * arrays[f"strong/{name}"] + (1 - denoise) * arrays[f"grain/{name}"]

        slope = f"body.{i + 1}.weight"
        layers.append(
            (
                mix(f"body.{i}.weight"),
                mix(f"body.{i}.bias"),
                mix(slope) if f"strong/{slope}" in arrays else None,
            )
        )
        i += 2
    if not layers:
        raise UpscaleError("The AI model is damaged. Install Azoth Converter again.")
    return layers


def onnx_model(layers) -> bytes:
    """The network as an ONNX file (the format OpenCV reads), written by hand so no extra
    library is needed: 3×3 convolutions with PReLU, then "depth to space" (×4)."""
    nodes, weights = [], []
    prev = "x"
    for i, (w, b, slope) in enumerate(layers):
        weights += [_tensor(f"w{i}", w), _tensor(f"b{i}", b)]
        nodes.append(
            _node(
                "Conv",
                [prev, f"w{i}", f"b{i}"],
                f"c{i}",
                [_ints("kernel_shape", [3, 3]), _ints("pads", [1, 1, 1, 1])],
            )  # fmt: skip
        )
        prev = f"c{i}"
        if slope is not None:
            weights.append(_tensor(f"a{i}", slope.reshape(-1, 1, 1)))
            nodes.append(_node("PRelu", [prev, f"a{i}"], f"p{i}"))
            prev = f"p{i}"
    nodes.append(
        _node("DepthToSpace", [prev], "y", [_int("blocksize", SCALE), _str("mode", b"CRD")])
    )
    return _model(nodes, weights)


def load_best_weights() -> dict[str, np.ndarray]:
    """The big model's arrays by their PyTorch names (``conv_first.weight`` …)."""
    try:
        with np.load(BEST_MODEL_FILE, allow_pickle=False) as data:
            arrays = {n: data[n].astype(np.float32) for n in data.files if n != "sources"}
    except OSError as exc:
        raise UpscaleError("The AI model is missing. Install Azoth Converter again.") from exc
    if "conv_first.weight" not in arrays or "body.0.rdb1.conv1.weight" not in arrays:
        raise UpscaleError("The AI model is damaged. Install Azoth Converter again.")
    return arrays


def best_onnx_model(arrays: dict[str, np.ndarray]) -> bytes:
    """The big model (RRDBNet: 23 blocks of densely connected convolutions, then two ×2
    enlargements) as an ONNX file, built the same way as the small one."""
    nodes, weights = [], []
    names = iter(range(10**9))

    def conv(x: str, name: str, lrelu: bool = False) -> str:
        weights.extend(
            [_tensor(f"{name}.weight", arrays[f"{name}.weight"]),
             _tensor(f"{name}.bias", arrays[f"{name}.bias"])]
        )  # fmt: skip
        out = f"t{next(names)}"
        attrs = [_ints("kernel_shape", [3, 3]), _ints("pads", [1, 1, 1, 1])]
        nodes.append(_node("Conv", [x, f"{name}.weight", f"{name}.bias"], out, attrs))
        if not lrelu:
            return out
        act = f"t{next(names)}"
        nodes.append(_node("LeakyRelu", [out], act, [_float("alpha", 0.2)]))
        return act

    def scaled_add(x: str, residual: str) -> str:  # x * 0.2 + residual
        mul, out = f"t{next(names)}", f"t{next(names)}"
        nodes.append(_node("Mul", [x, "k0.2"], mul))
        nodes.append(_node("Add", [mul, residual], out))
        return out

    def dense_block(x: str, name: str) -> str:
        parts = [x]  # each convolution sees the input and all earlier results
        for i in range(1, 6):
            if len(parts) == 1:
                joined = x
            else:
                joined = f"t{next(names)}"
                nodes.append(_node("Concat", parts, joined, [_int("axis", 1)]))
            parts.append(conv(joined, f"{name}.conv{i}", lrelu=i < 5))
        return scaled_add(parts[-1], x)

    def enlarge2(x: str) -> str:
        out = f"t{next(names)}"
        attrs = [_str("mode", b"nearest"), _str("coordinate_transformation_mode", b"asymmetric"),
                 _str("nearest_mode", b"floor")]  # fmt: skip
        nodes.append(_node("Resize", [x, "", "s2"], out, attrs))
        return out

    weights.append(_tensor("k0.2", np.array([0.2], np.float32)))
    weights.append(_tensor("s2", np.array([1, 1, 2, 2], np.float32)))
    feat = conv("x", "conv_first")
    body = feat
    i = 0
    while f"body.{i}.rdb1.conv1.weight" in arrays:
        block = body
        for r in (1, 2, 3):
            block = dense_block(block, f"body.{i}.rdb{r}")
        body = scaled_add(block, body)
        i += 1
    added = f"t{next(names)}"
    nodes.append(_node("Add", [feat, conv(body, "conv_body")], added))
    up = conv(enlarge2(added), "conv_up1", lrelu=True)
    up = conv(enlarge2(up), "conv_up2", lrelu=True)
    last = conv(conv(up, "conv_hr", lrelu=True), "conv_last")
    nodes.append(_node("Identity", [last], "y"))
    return _model(nodes, weights)


def _model(nodes: list[bytes], weights: list[bytes]) -> bytes:
    graph = (
        b"".join(_field(1, n) for n in nodes)
        + _field(2, b"upscale")
        + b"".join(_field(5, t) for t in weights)
        + _field(11, _value_info("x"))
        + _field(12, _value_info("y"))
    )
    opset = _field(1, b"") + _varint_field(2, 13)
    return _varint_field(1, 8) + _field(2, b"azoth") + _field(7, graph) + _field(8, opset)


def _varint(n: int) -> bytes:
    out = bytearray()
    while True:
        byte = n & 0x7F
        n >>= 7
        if n:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def _field(number: int, payload: bytes) -> bytes:  # length-delimited (text, bytes, message)
    return _varint(number << 3 | 2) + _varint(len(payload)) + payload


def _varint_field(number: int, value: int) -> bytes:
    return _varint(number << 3) + _varint(value)


def _tensor(name: str, array: np.ndarray) -> bytes:
    array = np.ascontiguousarray(array, dtype="<f4")
    dims = b"".join(_varint_field(1, d) for d in array.shape)
    return dims + _varint_field(2, 1) + _field(8, name.encode()) + _field(9, array.tobytes())


def _node(op: str, inputs: list[str], output: str, attributes=()) -> bytes:
    return (
        b"".join(_field(1, i.encode()) for i in inputs)
        + _field(2, output.encode())
        + _field(4, op.encode())
        + b"".join(_field(5, a) for a in attributes)
    )


def _int(name: str, value: int) -> bytes:
    return _field(1, name.encode()) + _varint_field(3, value) + _varint_field(20, 2)


def _ints(name: str, values: list[int]) -> bytes:
    return (
        _field(1, name.encode())
        + b"".join(_varint_field(8, v) for v in values)
        + _varint_field(20, 7)
    )


def _float(name: str, value: float) -> bytes:
    return (
        _field(1, name.encode())
        + _varint(2 << 3 | 5)
        + struct.pack("<f", value)
        + _varint_field(20, 1)
    )


def _str(name: str, value: bytes) -> bytes:
    return _field(1, name.encode()) + _field(4, value) + _varint_field(20, 3)


def _value_info(name: str) -> bytes:
    dims = _field(1, _varint_field(1, 1)) + _field(1, _varint_field(1, 3))
    dims += _field(1, _field(2, b"height")) + _field(1, _field(2, b"width"))
    tensor_type = _varint_field(1, 1) + _field(2, dims)
    return _field(1, name.encode()) + _field(2, _field(1, tensor_type))


def _net(denoise: float, best: bool = False):
    key = (best, 0.0 if best else denoise)
    net = _nets.get(key)
    if net is None:
        import cv2

        model = best_onnx_model(load_best_weights()) if best else onnx_model(load_weights(denoise))
        try:
            net = cv2.dnn.readNetFromONNX(np.frombuffer(model, dtype=np.uint8))
        except cv2.error as exc:  # pragma: no cover - would be a packaging problem
            raise UpscaleError(f"Cannot start the AI model ({exc}).") from exc
        _nets.clear()  # keep only one in memory
        _nets[key] = net
    return net


def upscale4(net, rgb: np.ndarray, best: bool = False) -> np.ndarray:
    """One tile: ``rgb`` (height × width × 3, values 0…1, float32) four times bigger."""
    net.setInput(np.ascontiguousarray(rgb.transpose(2, 0, 1)[None]))
    out = net.forward()[0].transpose(1, 2, 0)
    if best:
        return out
    # The small network predicts the difference to a plain (nearest-neighbour) enlargement.
    return out + rgb.repeat(SCALE, axis=0).repeat(SCALE, axis=1)


# --- whole pictures ------------------------------------------------------------------


def enhance(
    img: Image.Image,
    size: tuple[int, int],
    denoise: str = MEDIUM,
    progress: Callable[[float], None] | None = None,
    cancelled: Callable[[], None] | None = None,
    best: bool = False,
) -> Image.Image:
    """``img`` at ``size`` (width, height), enlarged by the AI four times and then brought
    to the exact size. ``cancelled`` is called between tiles and may raise to stop.
    ``best`` uses the big, slow model (``denoise`` then doesn't apply).

    Colours are worked on with 8 bits per channel; transparency (alpha) is enlarged
    smoothly the normal way. The result has the same mode as ``img`` where possible."""
    if denoise not in DENOISE:
        raise ValueError(f"Unknown noise removal level: {denoise}")
    if not available(best):
        raise UpscaleError(
            "AI enlargement is not available because the AI model is missing. Install "
            "Azoth Converter again."
        )
    mode = img.mode
    alpha = img.getchannel("A") if "A" in img.getbands() else None
    gray = mode in ("L", "LA", "1")
    rgb = np.asarray(img.convert("RGB"), dtype=np.uint8)
    if alpha is not None:
        rgb = _fill_transparent(rgb, np.asarray(alpha))
    with _lock:
        net = _net(DENOISE[denoise], best)
        result = _enhance_rgb(rgb, size, net, progress, cancelled, best)
    out = Image.fromarray(result, "RGB")
    if gray:
        out = out.convert("L")
    if alpha is not None:
        smaller = size[0] * size[1] < img.width * img.height
        method = Image.Resampling.LANCZOS if smaller else Image.Resampling.BICUBIC
        out.putalpha(alpha.resize(size, method))
    return out


def _fill_transparent(rgb: np.ndarray, alpha: np.ndarray) -> np.ndarray:
    """Give fully transparent pixels the colour of the visible pixels near them. Their
    colour is hidden (often black), but the AI would blend it into the edges, which then
    get dark fringes."""
    hidden = alpha == 0
    if not hidden.any() or hidden.all():
        return rgb
    import cv2

    weight = (~hidden).astype(np.float32)
    colour = rgb.astype(np.float32) * weight[..., None]
    filled = rgb.copy()
    todo = hidden
    size = 3
    while todo.any() and size < 2 * max(rgb.shape[:2]) + 3:
        w = cv2.blur(weight, (size, size), borderType=cv2.BORDER_CONSTANT)
        c = cv2.blur(colour, (size, size), borderType=cv2.BORDER_CONSTANT)
        found = todo & (w > 1e-6)
        filled[found] = np.clip(c[found] / w[found][:, None] + 0.5, 0, 255).astype(np.uint8)
        todo = todo & ~found
        size = size * 3
    return filled


def _enhance_rgb(rgb, size, net, progress, cancelled, best=False) -> np.ndarray:
    tile_size = BEST_TILE if best else TILE
    h, w = rgb.shape[:2]
    out_w, out_h = size
    big_w, big_h = w * SCALE, h * SCALE
    exact = (out_w, out_h) == (big_w, big_h)
    sy = out_h / big_h
    shrink = out_w * out_h < big_w * big_h
    method = Image.Resampling.LANCZOS if shrink else Image.Resampling.BICUBIC
    # Pixels (in the ×4 picture) the final resize looks at beyond a strip's own rows.
    margin = 0 if exact else math.ceil((3 if shrink else 2) * max(1.0, 1 / sy)) + 2

    # Output strips of about one tile of source rows each.
    rows_per_strip = max(1, round(tile_size * SCALE * sy))
    strips = []
    for o0 in range(0, out_h, rows_per_strip):
        o1 = min(out_h, o0 + rows_per_strip)
        a = max(0, math.floor((o0 / sy - margin) / SCALE))
        b = min(h, math.ceil((o1 / sy + margin) / SCALE))
        strips.append((o0, o1, a, b))
    tiles_per_strip = math.ceil(w / tile_size)
    total = len(strips) * tiles_per_strip
    done = 0

    result = np.empty((out_h, out_w, 3), dtype=np.uint8)
    for o0, o1, a, b in strips:
        big = np.empty(((b - a) * SCALE, big_w, 3), dtype=np.uint8)
        ra, rb = max(0, a - CONTEXT), min(h, b + CONTEXT)
        for c0 in range(0, w, tile_size):
            if cancelled:
                cancelled()
            c1 = min(w, c0 + tile_size)
            ca, cb = max(0, c0 - CONTEXT), min(w, c1 + CONTEXT)
            tile = upscale4(net, rgb[ra:rb, ca:cb].astype(np.float32) / 255, best)
            tile = tile[(a - ra) * SCALE : (b - ra) * SCALE, (c0 - ca) * SCALE : (c1 - ca) * SCALE]
            big[:, c0 * SCALE : c1 * SCALE] = np.clip(tile * 255 + 0.5, 0, 255).astype(np.uint8)
            done += 1
            if progress:
                progress(done / total)
        if exact:
            result[o0:o1] = big[(o0 - a * SCALE) : (o1 - a * SCALE)]
            continue
        # Resize only this strip, but with its neighbours' pixels around it (Pillow's
        # "box"), so the strips join exactly as if the whole picture was resized at once.
        top = o0 / sy - a * SCALE
        bottom = o1 / sy - a * SCALE
        strip = Image.fromarray(big, "RGB").resize(
            (out_w, o1 - o0), method, box=(0, top, big_w, bottom)
        )
        result[o0:o1] = np.asarray(strip)
    return result
