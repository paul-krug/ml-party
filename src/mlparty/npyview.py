"""Pure-python .npy/.npz slice reading for the artifact tensor viewer.

No numpy dependency: the npy header is a python dict literal, and slicing a
C-order array along leading axes is a seek + read. Deliberately bounded —
this serves plot-sized slices (1-D lines, 2-D heatmaps, strided down to
display resolution), never whole checkpoints.
"""
from __future__ import annotations

import ast
import math
import struct
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO

MAGIC = b"\x93NUMPY"

# descr -> (struct format char, itemsize)
_DTYPES = {
    "<f2": ("e", 2), "<f4": ("f", 4), "<f8": ("d", 8),
    "|i1": ("b", 1), "<i2": ("h", 2), "<i4": ("i", 4), "<i8": ("q", 8),
    "|u1": ("B", 1), "<u2": ("H", 2), "<u4": ("I", 4), "<u8": ("Q", 8),
    "|b1": ("?", 1),
}

MAX_1D_POINTS = 65536       # a line plot never needs more
MAX_2D_POINTS = 512         # per axis, for heatmaps
MAX_EAGER_BYTES = 32 << 20  # read-whole-block ceiling for non-seekable sources


class NpyError(ValueError):
    pass


@dataclass
class NpyInfo:
    shape: tuple[int, ...]
    descr: str
    fmt: str
    itemsize: int
    data_offset: int
    fortran: bool


def read_info(f: BinaryIO) -> NpyInfo:
    if f.read(6) != MAGIC:
        raise NpyError("not an .npy file")
    version = f.read(2)
    if version[0] == 1:
        (hlen,) = struct.unpack("<H", f.read(2))
        data_offset = 10 + hlen
    else:
        (hlen,) = struct.unpack("<I", f.read(4))
        data_offset = 12 + hlen
    try:
        header: dict[str, Any] = ast.literal_eval(f.read(hlen).decode("latin1"))
        descr, shape, fortran = header["descr"], header["shape"], header["fortran_order"]
    except (ValueError, SyntaxError, KeyError, UnicodeDecodeError) as e:
        raise NpyError(f"malformed npy header: {e}") from e
    if not isinstance(descr, str) or descr not in _DTYPES:
        raise NpyError(f"unsupported dtype {descr!r} — plain numeric arrays only")
    fmt, itemsize = _DTYPES[descr]
    return NpyInfo(tuple(int(d) for d in shape), descr, fmt, itemsize,
                   data_offset, bool(fortran))


def _read_elems(f: BinaryIO, info: NpyInfo, start: int, count: int) -> list:
    f.seek(start)
    buf = f.read(count * info.itemsize)
    if len(buf) != count * info.itemsize:
        raise NpyError("file truncated")
    return list(struct.unpack(f"<{count}{info.fmt}", buf))


def read_slice(f: BinaryIO, info: NpyInfo, prefix: list[int],
               cheap_seek: bool = True) -> dict:
    """Slice fixed by `prefix` indices on the leading axes; the remaining
    1 or 2 axes are strided down to display resolution."""
    if info.fortran:
        raise NpyError("fortran-order arrays are not supported")
    shape = info.shape
    if len(prefix) > len(shape):
        raise NpyError("more indices than axes")
    rest = shape[len(prefix):]
    if len(rest) > 2:
        raise NpyError("fix more leading indices — slices render as 1-D or 2-D")
    for axis, (ix, dim) in enumerate(zip(prefix, shape)):
        if not 0 <= ix < dim:
            raise NpyError(f"index {ix} out of range for axis {axis} (size {dim})")

    flat = 0
    for k, ix in enumerate(prefix):
        stride = 1
        for d in shape[k + 1:]:
            stride *= d
        flat += ix * stride
    start = info.data_offset + flat * info.itemsize

    if len(rest) <= 1:  # scalar or 1-D line
        n = rest[0] if rest else 1
        step = -(-n // MAX_1D_POINTS)
        if step == 1:
            vals = _read_elems(f, info, start, n)
        elif cheap_seek:
            vals = [
                _read_elems(f, info, start + i * info.itemsize, 1)[0]
                for i in range(0, n, step)
            ]
        elif n * info.itemsize <= MAX_EAGER_BYTES:
            vals = _read_elems(f, info, start, n)[::step]
        else:
            raise NpyError("slice too large to read from a compressed archive")
        out_shape, steps = [len(vals)], [step]
    else:  # 2-D heatmap
        r, c = rest
        rstep = -(-r // MAX_2D_POINTS)
        cstep = -(-c // MAX_2D_POINTS)
        rows: list[list] = []
        if cheap_seek or r * c * info.itemsize <= MAX_EAGER_BYTES:
            if cheap_seek:
                for i in range(0, r, rstep):
                    row = _read_elems(f, info, start + i * c * info.itemsize, c)
                    rows.append(row[::cstep])
            else:
                flat_vals = _read_elems(f, info, start, r * c)
                for i in range(0, r, rstep):
                    rows.append(flat_vals[i * c:(i + 1) * c:cstep])
        else:
            raise NpyError("slice too large to read from a compressed archive")
        vals = [v for row in rows for v in row]
        out_shape, steps = [len(rows), len(rows[0]) if rows else 0], [rstep, cstep]

    finite = [v for v in vals if isinstance(v, (int, float)) and math.isfinite(v)]
    return {
        "shape": out_shape,
        "steps": steps,
        "values": rows if len(rest) == 2 else vals,  # type: ignore[possibly-undefined]
        "min": min(finite) if finite else None,
        "max": max(finite) if finite else None,
    }


_CHUNK_ELEMS = 1 << 20
_EXACT_BYTES = 32 << 20   # full scan below this
_SAMPLE_BLOCKS = 128
_SAMPLE_BLOCK_ELEMS = 32768


def _minmax(vals: tuple) -> tuple[float | None, float | None]:
    finite = [v for v in vals if math.isfinite(v)]
    if not finite:
        return None, None
    return min(finite), max(finite)


def tensor_range(f: BinaryIO, info: NpyInfo, cheap_seek: bool = True) -> dict:
    """Whole-tensor min/max: exact below 32 MiB, evenly-strided sample above
    (never reads the whole of a huge file)."""
    n = 1
    for d in info.shape:
        n *= d
    total_bytes = n * info.itemsize
    lo: float | None = None
    hi: float | None = None

    def fold(vals: tuple) -> None:
        nonlocal lo, hi
        vlo, vhi = _minmax(vals)
        if vlo is None:
            return
        lo = vlo if lo is None else min(lo, vlo)
        hi = vhi if hi is None else max(hi, vhi)

    if total_bytes <= _EXACT_BYTES:
        f.seek(info.data_offset)
        left = n
        while left > 0:
            k = min(_CHUNK_ELEMS, left)
            buf = f.read(k * info.itemsize)
            if len(buf) < k * info.itemsize:
                raise NpyError("file truncated")
            fold(struct.unpack(f"<{k}{info.fmt}", buf))
            left -= k
        return {"min": lo, "max": hi, "exact": True}

    if not cheap_seek:
        raise NpyError("tensor too large to range-scan inside a compressed archive")
    block = min(_SAMPLE_BLOCK_ELEMS, n)
    stride = max(1, (n - block) // (_SAMPLE_BLOCKS - 1))
    for start in range(0, n - block + 1, stride):
        fold(_read_elems_tuple(f, info, info.data_offset + start * info.itemsize, block))
    return {"min": lo, "max": hi, "exact": False,
            "sampled_fraction": round(min(1.0, _SAMPLE_BLOCKS * block / n), 4)}


def _read_elems_tuple(f: BinaryIO, info: NpyInfo, start: int, count: int) -> tuple:
    f.seek(start)
    buf = f.read(count * info.itemsize)
    if len(buf) != count * info.itemsize:
        raise NpyError("file truncated")
    return struct.unpack(f"<{count}{info.fmt}", buf)


# ------------------------------------------------------------- file-level API

def tensor_meta(path: Path, member: str | None = None) -> dict:
    """Metadata for an .npy file, or member listing / member metadata for .npz."""
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as z:
            names = [n for n in z.namelist() if n.endswith(".npy")]
            if member is None:
                return {"kind": "npz", "members": names}
            if member not in names:
                raise NpyError(f"no member {member!r} in archive")
            with z.open(member) as f:
                info = read_info(f)  # type: ignore[arg-type]
    else:
        with open(path, "rb") as f:
            info = read_info(f)
    return {"kind": "npy", "member": member, "shape": list(info.shape),
            "dtype": info.descr, "fortran": info.fortran}


def tensor_slice(path: Path, prefix: list[int], member: str | None = None) -> dict:
    if zipfile.is_zipfile(path):
        if member is None:
            raise NpyError("archive: pass member=<name.npy>")
        with zipfile.ZipFile(path) as z, z.open(member) as f:
            info = read_info(f)  # type: ignore[arg-type]
            return read_slice(f, info, prefix, cheap_seek=False)  # type: ignore[arg-type]
    with open(path, "rb") as f:
        info = read_info(f)
        return read_slice(f, info, prefix, cheap_seek=True)


def tensor_full_range(path: Path, member: str | None = None) -> dict:
    if zipfile.is_zipfile(path):
        if member is None:
            raise NpyError("archive: pass member=<name.npy>")
        with zipfile.ZipFile(path) as z, z.open(member) as f:
            info = read_info(f)  # type: ignore[arg-type]
            return tensor_range(f, info, cheap_seek=False)  # type: ignore[arg-type]
    with open(path, "rb") as f:
        info = read_info(f)
        return tensor_range(f, info, cheap_seek=True)
