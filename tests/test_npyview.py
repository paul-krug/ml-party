import io
import struct
import zipfile

import pytest
from fastapi.testclient import TestClient

from mlparty.core import MlParty
from mlparty.http_api import build_app
from mlparty.npyview import NpyError, read_info, read_slice


def make_npy(shape: tuple[int, ...], values: list[float], descr: str = "<f4") -> bytes:
    header = f"{{'descr': '{descr}', 'fortran_order': False, 'shape': {shape!r}, }}"
    pad = 64 - (10 + len(header) + 1) % 64
    header = header + " " * pad + "\n"
    fmt = {"<f4": "f", "<f8": "d", "<i8": "q"}[descr]
    return (b"\x93NUMPY" + bytes([1, 0]) + struct.pack("<H", len(header))
            + header.encode() + struct.pack(f"<{len(values)}{fmt}", *values))


def test_read_info_and_1d_slice():
    raw = make_npy((6,), [0.0, 1.0, 2.0, 3.0, 4.0, 5.0])
    f = io.BytesIO(raw)
    info = read_info(f)
    assert info.shape == (6,) and info.descr == "<f4"
    out = read_slice(f, info, [])
    assert out["shape"] == [6] and out["values"][3] == pytest.approx(3.0)
    assert out["min"] == 0.0 and out["max"] == 5.0


def test_3d_prefix_slices():
    # shape (2, 3, 4), values = flat index, C-order
    vals = [float(i) for i in range(24)]
    raw = make_npy((2, 3, 4), vals)
    f = io.BytesIO(raw)
    info = read_info(f)

    line = read_slice(f, info, [1, 2])            # → 1-D row [20..23]
    assert line["values"] == pytest.approx([20.0, 21.0, 22.0, 23.0])

    heat = read_slice(f, info, [1])               # → 2-D (3, 4)
    assert heat["shape"] == [3, 4]
    assert heat["values"][2][3] == pytest.approx(23.0)

    with pytest.raises(NpyError):
        read_slice(f, info, [])                   # 3-D: must fix an axis
    with pytest.raises(NpyError):
        read_slice(f, info, [5])                  # out of range


def test_tensor_endpoints_npy_and_npz(tmp_path):
    src = tmp_path / "proj"
    src.mkdir()
    party = MlParty.init(src / ".mlparty")
    party.experiment_ensure("p", "e", created_by="test")

    npy = make_npy((2, 3), [float(i) for i in range(6)])
    ref = party.store.put_artifact_bytes(npy, "act.npy")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("weights.npy", npy)
    zref = party.store.put_artifact_bytes(buf.getvalue(), "bundle.npz")

    c = TestClient(build_app(src / ".mlparty"))

    meta = c.get(f"/api/artifacts/{ref.sha256}/tensor").json()
    assert meta["shape"] == [2, 3] and meta["dtype"] == "<f4"

    sl = c.get(f"/api/artifacts/{ref.sha256}/tensor/slice", params={"prefix": "1"}).json()
    assert sl["values"] == [3.0, 4.0, 5.0]

    listing = c.get(f"/api/artifacts/{zref.sha256}/tensor").json()
    assert listing == {"kind": "npz", "members": ["weights.npy"]}
    zsl = c.get(f"/api/artifacts/{zref.sha256}/tensor/slice",
                params={"prefix": "0", "member": "weights.npy"}).json()
    assert zsl["values"] == [0.0, 1.0, 2.0]

    r = c.get(f"/api/artifacts/{ref.sha256}/tensor/slice", params={"prefix": "9"})
    assert r.status_code == 422

    rng = c.get(f"/api/artifacts/{ref.sha256}/tensor/range").json()
    assert rng == {"min": 0.0, "max": 5.0, "exact": True}
    zrng = c.get(f"/api/artifacts/{zref.sha256}/tensor/range",
                 params={"member": "weights.npy"}).json()
    assert zrng["min"] == 0.0 and zrng["max"] == 5.0 and zrng["exact"]

    # inline serving for the media viewers
    r = c.get(f"/api/artifacts/{ref.sha256}",
              params={"inline": True, "media_type": "image/png", "name": "a.png"})
    assert r.headers["content-type"].startswith("image/png")
    assert r.headers["content-disposition"].startswith("inline")
