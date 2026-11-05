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

        D = ctypes.c_void_p
        lib = self.lib
        lib.earthng_dem_open.argtypes = [ctypes.c_char_p, ctypes.c_size_t, ctypes.c_int32, ctypes.c_uint32,
                                         ctypes.c_double, ctypes.c_double, ctypes.c_double]
        lib.earthng_dem_open.restype = D
        lib.earthng_dem_close.argtypes = [D]
        lib.earthng_dem_close.restype = None
        lib.earthng_dem_error.argtypes = [D, ctypes.c_char_p, ctypes.c_size_t]
        lib.earthng_dem_error.restype = ctypes.c_size_t
        lib.earthng_dem_sample.argtypes = [D, P, ctypes.c_size_t, ctypes.c_int32, P]
        lib.earthng_dem_despiked.argtypes = [D, P, ctypes.c_size_t, ctypes.c_double, ctypes.c_double, P]
        lib.earthng_dem_grid.argtypes = [D, P, ctypes.c_size_t, P, ctypes.c_size_t, ctypes.c_double, ctypes.c_double, P]
        for name in ('earthng_dem_sample', 'earthng_dem_despiked', 'earthng_dem_grid'):
            getattr(lib, name).restype = ctypes.c_int32

    def dem(self, cache, zoom, crs, cx, cy, lift):
        """A native fast_sources.Terrain (and Despiked) of the frame crs, or None for a CRS
        that is not a UTM zone."""
        code = str(crs).upper()
        if not code.startswith('EPSG:') or not code[5:].isdigit():
            return None
        path = str(cache).encode('utf-8')
        handle = self.lib.earthng_dem_open(path, len(path), int(zoom), int(code[5:]), float(cx), float(cy), float(lift))
        return Dem(self, handle) if handle else None

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


class Dem:
    """Terrain.sample, Despiked.sample and Despiked.grid in earthng_native.dll (rust/crates/kernels
    terrain.rs). Errors as the Python ones: FileNotFoundError('no_dem: ...') for a tile the cache
    lacks, ValueError('non-finite DEM')."""

    def __init__(self, kernels, handle):
        self.kernels, self.lib, self.handle = kernels, kernels.lib, handle

    def __del__(self):
        if self.handle:
            self.lib.earthng_dem_close(self.handle)
            self.handle = None

    def _check(self, code):
        if code == 0:
            return
        buf = self.kernels.ctypes.create_string_buffer(4096)
        n = self.lib.earthng_dem_error(self.handle, buf, len(buf))
        message = buf.raw[:min(n, len(buf))].decode('utf-8', 'replace')
        if code == 1:
            raise FileNotFoundError(message)
        raise ValueError(message)

    def sample(self, xy, smooth=False, missing=False, single=False):
        """Terrain.sample; missing and single as fast_profile.Mosaic.sample (NaN where a tile is
        not in the cache; a z13 grid's float32 pixels)."""
        import numpy as np
        xy = np.ascontiguousarray(np.asarray(xy, dtype=float).reshape(-1, 2))
        out = np.empty(len(xy))
        flags = int(bool(smooth)) | 2 * bool(missing) | 4 * bool(single)
        if len(xy):
            self._check(self.lib.earthng_dem_sample(self.handle, xy.ctypes.data, len(xy), flags, out.ctypes.data))
        return out

    def despiked(self, xy, spacing, spike):
        import numpy as np
        xy = np.ascontiguousarray(np.asarray(xy, dtype=float).reshape(-1, 2))
        out = np.empty(len(xy))
        if len(xy):
            self._check(self.lib.earthng_dem_despiked(self.handle, xy.ctypes.data, len(xy), float(spacing),
                                                      float(spike), out.ctypes.data))
        return out

    def grid(self, xs, ys, spacing, spike):
        import numpy as np
        xs, ys = np.ascontiguousarray(xs, dtype=float), np.ascontiguousarray(ys, dtype=float)
        out = np.empty(len(xs) * len(ys))
        if len(out):
            self._check(self.lib.earthng_dem_grid(self.handle, xs.ctypes.data, len(xs), ys.ctypes.data, len(ys),
                                                  float(spacing), float(spike), out.ctypes.data))
        return out


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


def routing(pack, emit=print, cancel=None):
    """[(region, routing file bytes)] of every region of a pack (build_routing.build_region's files,
    byte for byte), or None without the native tool."""
    import json
    import subprocess
    import tempfile
    exe = tool()
    if exe is None:
        return None
    with tempfile.TemporaryDirectory(prefix='earthng-routing-') as folder:
        process = subprocess.Popen([str(exe), 'routing', str(pack), '--out', folder], stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, text=True, encoding='utf-8',
                                   creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        lines = []
        try:
            for done, line in enumerate(process.stdout, 1):
                info = json.loads(line)
                lines.append(info)
                emit(f"routing {done}: {info['region']}, {info['nodes']} nodes")
                if cancel is not None and cancel.is_set():
                    process.kill()
                    raise InterruptedError('build stopped')
            error = process.stderr.read()
        finally:
            if process.poll() is None:
                process.wait()
        if process.returncode:
            raise RuntimeError(f'native routing failed: {error.strip()[-2000:]}')
        return [(info['region'], (Path(folder) / f"{info['region']}.bin").read_bytes())
                for info in sorted(lines, key=lambda i: i['region'])]


def map_source(pbf, emit=print):
    """What build_map.py's osmium pass reads, natively: (places, roads), places as
    [(lat, lon, [(key, value), ...])] and roads as [(rank, [(lon, lat), ...])] of roads with every
    node located, both in file order; None without the native tool. Raises RuntimeError on failure."""
    import json
    import struct
    import subprocess
    import tempfile
    exe = tool()
    if exe is None:
        return None
    with tempfile.TemporaryDirectory(prefix='earthng-map-source-') as folder:
        places_file, roads_file = Path(folder) / 'places.jsonl', Path(folder) / 'roads.bin'
        result = subprocess.run([str(exe), 'map-source', str(pbf), '--places', str(places_file),
                                 '--roads', str(roads_file)], capture_output=True, text=True, encoding='utf-8',
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if result.returncode:
            raise RuntimeError(f'native map source failed: {result.stderr.strip()[-2000:]}')
        for line in result.stderr.splitlines():
            emit(line)
        with places_file.open(encoding='utf-8') as stream:
            places = [(lat, lon, [tuple(pair) for pair in tags]) for lat, lon, tags in map(json.loads, stream)]
        data = roads_file.read_bytes()
    roads, at = [], 0
    while at < len(data):
        rank, count = struct.unpack_from('<BI', data, at)
        at += 5
        values = struct.unpack_from(f'<{2 * count}d', data, at)
        at += 16 * count
        roads.append((rank, list(zip(values[::2], values[1::2]))))
    return places, roads
