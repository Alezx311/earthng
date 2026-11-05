"""The native Map Builder (rust/): build steps rewritten in Rust, used when the executable is here.

A release ships it as bin/earthng-mapbuilder.exe; a checkout builds it with
`cargo build --release` in rust/. EARTHNG_NATIVE=0 keeps every step in Python.
Each native step writes exactly what the Python step it replaces writes (the cut: the same
objects in every tile, tests in rust/ and earthng/test_native_tool.py).
"""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NAME = 'earthng-mapbuilder.exe' if os.name == 'nt' else 'earthng-mapbuilder'
CANDIDATES = (ROOT / 'bin' / NAME, ROOT / 'rust' / 'target' / 'release' / NAME)


def tool():
    """Path of the native executable, or None (absent, or switched off by EARTHNG_NATIVE=0)."""
    if os.environ.get('EARTHNG_NATIVE', '1').strip() in ('0', 'no', 'off', 'false'):
        return None
    for path in CANDIDATES:
        if path.is_file():
            return path
    return None


LIBRARY = 'earthng_native.dll' if os.name == 'nt' else 'libearthng_native.so'
_kernels = []


class Kernels:
    """earthng_native.dll through ctypes: fast_profile.solve's conjugate gradients and its
    matrix-vector product (rust/crates/kernels). Arrays go by pointer, nothing is copied."""

    def __init__(self, path):
        import ctypes
        self.ctypes = ctypes
        self.lib = ctypes.CDLL(str(path))
        P = ctypes.c_void_p

        class System(ctypes.Structure):
            _fields_ = [('nvar', ctypes.c_size_t), ('nnz', ctypes.c_size_t), ('ptr', P), ('col', P), ('data', P),
                        ('diag0', P), ('ncross', ctypes.c_size_t), ('xv', P), ('xc', P), ('active', P),
                        ('clear_weight', ctypes.c_double)]
        self.System = System
        self.lib.earthng_profile_matvec.argtypes = [ctypes.POINTER(System), P, P, ctypes.c_int32]
        self.lib.earthng_profile_matvec.restype = ctypes.c_int32
        self.lib.earthng_profile_cg.argtypes = [ctypes.POINTER(System), P, ctypes.c_int64, ctypes.c_double,
                                                P, ctypes.POINTER(ctypes.c_int64), ctypes.POINTER(ctypes.c_double)]
        self.lib.earthng_profile_cg.restype = ctypes.c_int32

    def system(self, ptr, col, data, diag0, xv, xc, active, clear_weight):
        """The C view of a solve; the returned tuple keeps its arrays alive."""
        import numpy as np
        keep = [np.ascontiguousarray(ptr, dtype=np.int64), np.ascontiguousarray(col, dtype=np.int64),
                np.ascontiguousarray(data, dtype=np.float64), np.ascontiguousarray(diag0, dtype=np.float64),
                np.ascontiguousarray(np.reshape(np.stack([np.asarray(v, dtype=np.int64) for v in xv]), (4, -1))),
                np.ascontiguousarray(np.reshape(np.stack([np.asarray(c, dtype=np.float64) for c in xc]), (4, -1))),
                np.ascontiguousarray(active, dtype=np.float64)]
        s = self.System(len(keep[0]) - 1, len(keep[1]), keep[0].ctypes.data, keep[1].ctypes.data, keep[2].ctypes.data,
                        keep[3].ctypes.data, len(keep[6]), keep[4].ctypes.data, keep[5].ctypes.data,
                        keep[6].ctypes.data, float(clear_weight))
        return s, keep

    def matvec(self, system, h, springs=True):
        import numpy as np
        s, _ = system
        h = np.ascontiguousarray(h, dtype=np.float64)
        out = np.empty(s.nvar)
        self.lib.earthng_profile_matvec(self.ctypes.byref(s), h.ctypes.data, out.ctypes.data, int(bool(springs)))
        return out

    def cg(self, system, b, iterations, tol):
        import numpy as np
        s, _ = system
        b = np.ascontiguousarray(b, dtype=np.float64)
        x = np.empty(s.nvar)
        its, residual = self.ctypes.c_int64(), self.ctypes.c_double()
        self.lib.earthng_profile_cg(self.ctypes.byref(s), b.ctypes.data, int(iterations), float(tol), x.ctypes.data,
                                    self.ctypes.byref(its), self.ctypes.byref(residual))
        return x, its.value, residual.value


def kernels():
    """The loaded Kernels, or None (no library, or EARTHNG_NATIVE=0)."""
    if os.environ.get('EARTHNG_NATIVE', '1').strip() in ('0', 'no', 'off', 'false'):
        return None
    if not _kernels:
        found = None
        for folder in (ROOT / 'bin', ROOT / 'rust' / 'target' / 'release'):
            if (folder / LIBRARY).is_file():
                try:
                    found = Kernels(folder / LIBRARY)
                except OSError:
                    found = None
                break
        _kernels.append(found)
    return _kernels[0]


def cut_command(pbf, out, box=None, threads=None):
    """The native tile cut (osm_tiles_country.py's result in one process), or None."""
    exe = tool()
    if exe is None:
        return None
    command = [str(exe), 'cut', str(pbf), '--out', str(out)]
    if threads:
        command += ['--threads', str(threads)]
    if box:
        command += ['--package-box', *(repr(float(v)) for v in box)]
    return command
