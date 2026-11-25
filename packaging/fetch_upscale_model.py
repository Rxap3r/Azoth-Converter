"""Download the AI enlarging model and store its weights in src/azoth/resources/upscale.

The model is Real-ESRGAN "general x4v3" (BSD-3-Clause, https://github.com/xinntao/Real-ESRGAN),
in two variants that the app mixes for its "Noise removal" levels, and the bigger
"RealESRGAN_x4plus" for "Best quality (slow)". All files are pinned to one release and
checked against their SHA-256. They are PyTorch files; this script reads
them without PyTorch and without running any code from them (only plain number arrays are
accepted) and saves the weights as a numpy ``.npz`` file, which the app reads with
``allow_pickle=False``. The app itself never downloads anything: this runs only on a
developer's machine and in the automatic build (called by fetch_tessdata.py).

    python packaging/fetch_upscale_model.py
"""

from __future__ import annotations

import collections
import pickle
import sys
import tempfile
import zipfile
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetch_tessdata import _download, _sha256  # noqa: E402

URL = "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.5.0/{name}"
FILES = {
    # weight set in the app → (file, SHA-256)
    "strong": (
        "realesr-general-x4v3.pth",
        "8dc7edb9ac80ccdc30c3a5dca6616509367f05fbc184ad95b731f05bece96292",
    ),
    "grain": (
        "realesr-general-wdn-x4v3.pth",
        "1641f8c4464b9f097c9fdda5589273713f67cf59f3d909e0bd688f0cee269dca",
    ),
}
TARGET = (
    Path(__file__).resolve().parent.parent
    / "src" / "azoth" / "resources" / "upscale" / "realesr-general-x4v3.npz"
)  # fmt: skip
BEST_URL = "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.1.0/RealESRGAN_x4plus.pth"
BEST_SHA = "4fa0d38905f75ac06eb49a7951b426670021be3018265fd191d2125df9d682f1"
BEST_TARGET = TARGET.with_name("realesrgan-x4plus.npz")
SOURCES = "sources"
"""Array in the .npz with the hashes of the files it was made from (a new pin rebuilds it)."""


def read_pth(path: Path) -> dict[str, np.ndarray]:
    """The weight arrays of a PyTorch ``.pth`` file (a zip with a pickle), read safely:
    only ordered dicts and float tensors are allowed, nothing else can be loaded."""
    archive = zipfile.ZipFile(path)
    pkl = next(n for n in archive.namelist() if n.endswith("/data.pkl"))
    root = pkl.rsplit("/", 1)[0]
    dtypes = {"FloatStorage": "<f4", "HalfStorage": "<f2"}

    def rebuild(storage, offset, shape, stride, *_):
        dtype, key = storage
        data = np.frombuffer(archive.read(f"{root}/data/{key}"), dtype=dtype)
        count = int(np.prod(shape))
        expected = tuple(int(np.prod(shape[i + 1 :])) for i in range(len(shape)))
        if tuple(stride) != expected:
            raise ValueError("unexpected memory layout in the model file")
        return data[offset : offset + count].reshape(shape).astype(np.float32)

    class SafeUnpickler(pickle.Unpickler):
        def find_class(self, module, name):
            if (module, name) == ("collections", "OrderedDict"):
                return collections.OrderedDict
            if (module, name) == ("torch._utils", "_rebuild_tensor_v2"):
                return rebuild
            if module == "torch" and name in dtypes:
                return dtypes[name]
            raise pickle.UnpicklingError(f"not allowed in a model file: {module}.{name}")

        def persistent_load(self, pid):
            kind, dtype, key, _location, _size = pid
            if kind != "storage" or dtype not in dtypes.values():
                raise pickle.UnpicklingError("not allowed in a model file")
            return dtype, key

    try:  # closed right away: Windows can't delete a file that is still open
        with archive.open(pkl) as fh:
            state = SafeUnpickler(fh).load()
    finally:
        archive.close()
    # Training snapshots hold the averaged ("EMA") weights, which the authors use for
    # their results, under "params_ema"; the other files only "params".
    params = state.get("params_ema", state.get("params", state))
    return {k: np.ascontiguousarray(v) for k, v in params.items()}


def _up_to_date(target: Path, hashes: list[str]) -> bool:
    if target.is_file():
        try:
            with np.load(target, allow_pickle=False) as data:
                if list(data[SOURCES]) == hashes:
                    print(f"{target.name}: already there")
                    return True
        except (OSError, KeyError, ValueError):
            pass  # damaged or old: make it again
    return False


def _save(target: Path, arrays: dict[str, np.ndarray], hashes: list[str]) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_suffix(".part.npz")
    np.savez_compressed(temp, **arrays, **{SOURCES: np.array(hashes)})
    temp.replace(target)
    print(f"{target.name}: saved ({target.stat().st_size // 1024} KB)")


def main() -> int:
    return fetch_general() or fetch_best()


def fetch_best() -> int:
    """The big model for "Best quality (slow)"."""
    if _up_to_date(BEST_TARGET, [BEST_SHA]):
        return 0
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "RealESRGAN_x4plus.pth"
        print(f"{path.name}: downloading")
        _download(BEST_URL, path)
        actual = _sha256(path)
        if actual != BEST_SHA:
            print(f"{path.name}: wrong checksum {actual}", file=sys.stderr)
            return 1
        arrays = {k: v.astype(np.float16) for k, v in read_pth(path).items()}
    _save(BEST_TARGET, arrays, [BEST_SHA])
    return 0


def fetch_general() -> int:
    """The small model's two weight sets."""
    hashes = [sha for _name, sha in FILES.values()]
    if _up_to_date(TARGET, hashes):
        return 0
    arrays: dict[str, np.ndarray] = {}
    with tempfile.TemporaryDirectory() as tmp:
        for prefix, (name, expected) in FILES.items():
            path = Path(tmp) / name
            print(f"{name}: downloading")
            _download(URL.format(name=name), path)
            actual = _sha256(path)
            if actual != expected:
                print(f"{name}: wrong checksum {actual}", file=sys.stderr)
                return 1
            for key, value in read_pth(path).items():
                arrays[f"{prefix}/{key}"] = value.astype(np.float16)  # half the size, same result
    if set(k.split("/", 1)[1] for k in arrays if k.startswith("strong/")) != set(
        k.split("/", 1)[1] for k in arrays if k.startswith("grain/")
    ):
        print("The two model files don't match", file=sys.stderr)
        return 1
    _save(TARGET, arrays, hashes)
    return 0


if __name__ == "__main__":
    sys.exit(main())
