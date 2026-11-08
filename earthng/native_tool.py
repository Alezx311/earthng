"""The native Map Builder (rust/): build steps rewritten in Rust, used when the executable is here.

A release ships it as bin/earthng-mapbuilder.exe; a checkout builds it with
`cargo build --release` in rust/. EARTHNG_NATIVE=0 keeps every step in Python.
Each native step writes exactly what the Python step it replaces writes (the cut: the same
objects in every tile, tests in rust/ and earthng/test_native_tool.py).
"""
import ctypes
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


class IndexIn(ctypes.Structure):
    """rust/crates/kernels index.rs IndexIn, field for field."""
    _fields_ = [(name, ctypes.c_size_t if name in ('ns', 'nn', 'nj', 'path_len') else ctypes.c_void_p) for name in (
        'ns', 'layout', 'way', 'node_a', 'node_b', 'width', 'width_int', 'xy', 'xy_off', 'ps', 'ps_off', 'ph', 'ph_off',
        'cuts', 'text', 'text_off', 'raw', 'raw_off', 'nn', 'nid', 'node_xy', 'lift', 'h', 'mouth_sid', 'mouth_off',
        'nj', 'j_node', 'corners', 'corner_off', 'cz', 'wkb', 'wkb_off', 'j_bounds', 'path', 'path_len')]


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

        lib = self.lib
        # a library from before crossings.rs: fast_profile keeps its numpy crossings
        self.has_crossings = hasattr(lib, 'earthng_profile_crossings')
        if self.has_crossings:
            lib.earthng_profile_crossings.argtypes = [ctypes.c_size_t, P, P, P, P, P, P, P]
            lib.earthng_profile_crossings.restype = P
            lib.earthng_crossings_len.argtypes = [P]
            lib.earthng_crossings_len.restype = ctypes.c_size_t
            lib.earthng_crossings_take.argtypes = [P, P, P, P, P]
            lib.earthng_crossings_take.restype = None

        # csr / close_pairs (rust/crates/kernels solve.rs), absent from an older library
        self.has_solve = hasattr(lib, 'earthng_profile_csr')
        if self.has_solve:
            lib.earthng_profile_csr.argtypes = [ctypes.c_size_t, P, P, P, ctypes.c_int64]
            lib.earthng_profile_csr.restype = P
            lib.earthng_profile_close_pairs.argtypes = [ctypes.c_size_t, P, P, P, P, P]
            lib.earthng_profile_close_pairs.restype = P
            lib.earthng_out_len.argtypes = [P, ctypes.c_int32, ctypes.c_size_t]
            lib.earthng_out_len.restype = ctypes.c_size_t
            lib.earthng_out_copy.argtypes = [P, ctypes.c_int32, ctypes.c_size_t, P]
            lib.earthng_out_copy.restype = None
            lib.earthng_out_free.argtypes = [P]
            lib.earthng_out_free.restype = None
        self.has_index = hasattr(lib, 'earthng_write_index')
        if self.has_index:
            lib.earthng_write_index.argtypes = [P]
            lib.earthng_write_index.restype = ctypes.c_int32
            lib.earthng_float_repr.argtypes = [ctypes.c_double, ctypes.c_char_p, ctypes.c_size_t]
            lib.earthng_float_repr.restype = ctypes.c_size_t
        self.has_split = hasattr(lib, 'earthng_split_roads')
        if self.has_split:
            lib.earthng_split_roads.argtypes = [ctypes.c_size_t, P, ctypes.c_size_t, P, P, P]
            lib.earthng_split_roads.restype = P

        D = ctypes.c_void_p
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

    def _take(self, out, ints, floats):
        """The arrays of a kernel's Out (ints int64, then floats float64), freeing it."""
        import numpy as np
        try:
            got = []
            for float_, count, dtype in ((0, ints, np.int64), (1, floats, np.float64)):
                for k in range(count):
                    a = np.empty(self.lib.earthng_out_len(out, float_, k), dtype=dtype)
                    self.lib.earthng_out_copy(out, float_, k, a.ctypes.data)
                    got.append(a)
            return got
        finally:
            self.lib.earthng_out_free(out)

    def csr(self, rows, cols, vals, n):
        """fast_profile.csr: (ptr, col, data), the same bits (rust/crates/kernels solve.rs)."""
        import numpy as np
        keep = [np.ascontiguousarray(rows, dtype=np.int64), np.ascontiguousarray(cols, dtype=np.int64),
                np.ascontiguousarray(vals, dtype=np.float64)]
        assert len(keep[0]) == len(keep[1]) == len(keep[2])
        return tuple(self._take(self.lib.earthng_profile_csr(len(keep[0]), *[k.ctypes.data for k in keep], int(n)), 2, 1))

    def float_repr(self, x):
        """repr(float(x)) as the index writer writes it (for its tests)."""
        buf = ctypes.create_string_buffer(64)
        n = self.lib.earthng_float_repr(float(x), buf, 64)
        return buf.raw[:n].decode()

    def write_index(self, path, arrays):
        """fast_sources.write_index's rows into a new SQLite file at path (rust/crates/kernels
        index.rs); arrays by IndexIn's field names. False when it could not (reason on stderr)."""
        import numpy as np
        kinds = {'layout': np.uint8, 'width_int': np.uint8, 'text': np.uint8, 'wkb': np.uint8}
        floats = {'width', 'xy', 'ps', 'ph', 'cuts', 'raw', 'node_xy', 'lift', 'h', 'corners', 'cz', 'j_bounds'}
        keep, values = [], {}
        for name, _ in IndexIn._fields_:
            if name in ('ns', 'nn', 'nj', 'path', 'path_len'):
                continue
            dtype = kinds.get(name, np.float64 if name in floats else np.int64)
            a = arrays[name]
            a = np.frombuffer(a, dtype=np.uint8) if isinstance(a, bytes) else np.ascontiguousarray(a, dtype=dtype)
            if not len(a):
                a = np.zeros(1, dtype=dtype)        # a real pointer even for nothing
            keep.append(a)
            values[name] = a.ctypes.data
        encoded = str(path).encode()
        spec = IndexIn(ns=arrays['ns'], nn=arrays['nn'], nj=arrays['nj'], path=ctypes.cast(ctypes.c_char_p(encoded), ctypes.c_void_p),
                       path_len=len(encoded), **values)
        return self.lib.earthng_write_index(ctypes.byref(spec)) == 0

    def split_roads(self, lens, ids, x, y):
        """fast_sources._prepare's split (rust/crates/kernels split.rs): way, node a, node b,
        offsets, point rows (int64), then x y rounded (P x 2), arc lengths, piece lengths."""
        import numpy as np
        keep = [np.ascontiguousarray(lens, dtype=np.int64), np.ascontiguousarray(ids, dtype=np.int64),
                np.ascontiguousarray(x, dtype=np.float64), np.ascontiguousarray(y, dtype=np.float64)]
        assert len(keep[1]) == len(keep[2]) == len(keep[3]) == int(keep[0].sum())
        got = self._take(self.lib.earthng_split_roads(len(keep[0]), keep[0].ctypes.data, len(keep[1]),
                                                      *[k.ctypes.data for k in keep[1:]]), 5, 3)
        got[5] = got[5].reshape(-1, 2)
        return got

    def close_pairs(self, pos, seg_of, width, ground, same):
        """fast_profile.close_pairs: (a, e, t), the same arrays in the same order."""
        import numpy as np
        n = len(pos)
        keep = [np.ascontiguousarray(pos, dtype=np.float64).reshape(n, 2), np.ascontiguousarray(seg_of, dtype=np.int64),
                np.ascontiguousarray(width, dtype=np.float64), np.ascontiguousarray(ground, dtype=np.uint8),
                np.ascontiguousarray(same, dtype=np.uint8)]
        assert len(keep[4]) == max(0, n - 1) and all(len(k) == n for k in keep[1:4])
        return tuple(self._take(self.lib.earthng_profile_close_pairs(n, *[k.ctypes.data for k in keep]), 2, 1))

    def crossings(self, pos, seg_of, same, upper, lower, widths, levels):
        """fast_profile.crossings, the same arrays (rust/crates/kernels crossings.rs)."""
        import numpy as np
        n = len(pos)
        keep = [np.ascontiguousarray(pos, dtype=np.float64).reshape(n, 2), np.ascontiguousarray(seg_of, dtype=np.int64),
                np.ascontiguousarray(same, dtype=np.uint8), np.ascontiguousarray(upper, dtype=np.uint8),
                np.ascontiguousarray(lower, dtype=np.uint8), np.ascontiguousarray(widths, dtype=np.float64),
                np.ascontiguousarray(levels, dtype=np.float64)]
        assert len(keep[2]) == max(0, n - 1) and all(len(k) == n for k in keep[3:])
        handle = self.lib.earthng_profile_crossings(n, *[k.ctypes.data for k in keep])
        m = self.lib.earthng_crossings_len(handle)
        a, b = np.empty(m, dtype=np.int64), np.empty(m, dtype=np.int64)
        u, t = np.empty(m), np.empty(m)
        self.lib.earthng_crossings_take(handle, a.ctypes.data, b.ctypes.data, u.ctypes.data, t.ctypes.data)
        return a, b, u, t

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


def cut_command(pbf, out, region=None, threads=None):
    """The native tile cut (osm_tiles_country.py's result in one process), or None. region: keep
    every tile whose cell overlaps it (osm_tiles.region_keys); default the PBF header's box."""
    exe = tool()
    if exe is None:
        return None
    command = [str(exe), 'cut', str(pbf), '--out', str(out)]
    if threads:
        command += ['--threads', str(threads)]
    if region:
        command += ['--region', *(repr(float(v)) for v in region)]
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


def geos_library():
    """shapely's own geos_c library (the cells must use the same GEOS build), or None."""
    import shapely
    folder = Path(shapely.__file__).resolve().parent
    names = ('geos_c*.dll',) if os.name == 'nt' else ('libgeos_c*.so*', 'libgeos_c*.dylib')
    for where in (folder.parent / 'shapely.libs', folder / '.libs', folder.parent / 'Shapely.libs', folder / '.dylibs'):
        for name in names:
            found = sorted(where.glob(name))
            if found:
                return found[0]
    return None


# compile's reason for a cell by the sea whose coastline tiles are not all read into scenes yet
COAST_SCENES = 'coast scenes'


def compile_cells(config, cells):
    """build_country.compile_cell + country_format.encode_cell of cells natively.

    config: {'index', 'scenes', 'dem': {cache, zoom, epsg, cx, cy, lift}, 'step', 'include'};
    cells: [(i, j, [(x0, y0, x1, y1, tile key), ...] scenery leaves[, coastline tile keys])]. Returns
    {(i, j): (payload bytes, road count)} of the cells done and {(i, j): reason} of those
    left to Python, or None without the native tool or shapely's GEOS."""
    import json
    import struct
    import subprocess
    import tempfile
    exe, geos = tool(), geos_library()
    if exe is None or geos is None:
        return None
    task = dict(config, geos=str(geos), cells=[{'i': i, 'j': j, 'scenery': [list(leaf) for leaf in leaves],
                                                'coast': list(coast[0]) if coast else []}
                                               for i, j, leaves, *coast in cells])
    with tempfile.TemporaryDirectory(prefix='earthng-cells-') as folder:
        path, out = Path(folder) / 'task.json', Path(folder) / 'cells.bin'
        path.write_text(json.dumps(task), encoding='utf-8')
        result = subprocess.run([str(exe), '--threads', '1', 'compile', str(path), '--out', str(out)],
                                capture_output=True, text=True, encoding='utf-8',
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if result.returncode:
            raise RuntimeError(f'native cells failed: {result.stderr.strip()[-2000:]}')
        if os.environ.get('EARTHNG_CELLS_PROFILE'):
            print(result.stderr.strip())
        data = out.read_bytes()
    done, left, at = {}, {}, 0
    while at < len(data):
        i, j, status, roads, n = struct.unpack_from('<qqBII', data, at)
        at += 25
        body = data[at:at + n]
        at += n
        if status == 0:
            done[i, j] = (body, roads)
        else:
            left[i, j] = body.decode('utf-8', 'replace')
    return done, left


def proj_library():
    """pyproj's own PROJ library and its data folder (scenes must use the same PROJ), or None."""
    import pyproj
    import pyproj.datadir
    folder = Path(pyproj.__file__).resolve().parent
    names = ('proj_*.dll', 'proj*.dll') if os.name == 'nt' else ('libproj*.so*', 'libproj*.dylib')
    for where in (folder.parent / 'pyproj.libs', folder / '.libs', folder / '.dylibs'):
        for name in names:
            found = sorted(where.glob(name))
            if found:
                return found[0], Path(pyproj.datadir.get_data_dir())
    return None


# The Python sources rust/crates/cells (rules.rs, scenebuild.rs) mirrors: when one of them
# changes, rules_fingerprint() no longer equals RULES and every scene is read in Python again
# until the Rust side follows (test_native_tool says so).
RULES = '18eed95425adb62e'


def rules_fingerprint():
    """sha256 of the functions Store.build_scene runs, or None where their source is not here."""
    import hashlib
    import inspect
    import fast_sources
    import fast_style
    import nature
    import retail
    import venues
    functions = (retail._key, retail._recognized, retail._named.__wrapped__, retail.post_type, retail.kind,
                 retail.brand, retail.enriched, fast_style.ground_kind, fast_style.rail_tags, fast_style.line_kind,
                 fast_style.point_kind, fast_style.poi, fast_style.point_keys, nature.ground_kind,
                 fast_sources.number, fast_sources.lifted, fast_sources.link_parts, fast_sources.Store.build_scene,
                 fast_sources.write_scene, venues.point_tags)
    digest = hashlib.sha256()
    try:
        for f in functions:
            digest.update(inspect.getsource(f).encode('utf-8'))
    except (OSError, TypeError):
        return None
    return digest.hexdigest()[:16]


def scene_rules():
    """The sets and tables of the scene rules, as rules.rs reads them."""
    import fast_sources
    import fast_style as fs
    import retail
    return {
        'lookup': retail._LOOKUP, 'wikidata': retail.WIKIDATA, 'fuel': sorted(retail.FUEL),
        'networks': sorted(retail.SERVICE_NETWORKS), 'food_shops': sorted(retail.FOOD_SHOPS),
        'service_amenity': sorted(retail.SERVICE_AMENITY), 'service_shops': sorted(retail.SERVICE_SHOPS),
        'names': list(retail.NAMES), 'says': sorted(retail._SAYS),
        'point_keys': list(fs.point_keys()), 'islands': list(fs.ISLANDS.items()), 'fields': sorted(fs.FIELDS),
        'hard_fields': sorted(fs.HARD_FIELDS), 'sites': sorted(fs.SITES), 'paved': sorted(fs.PAVED),
        'woods': sorted(fs.WOODS), 'parks': sorted(fs.PARKS), 'paths': sorted(fs.PATHS), 'rails': list(fs.RAILS),
        'rail_tags': list(fs.RAIL_TAGS), 'unmarked': list(fs.UNMARKED), 'entrances': list(fs.ENTRANCES),
        'pois': fs.POIS, 'poi_amenity': sorted(fs.POI_AMENITY), 'poi_not': list(fs.POI_NOT), 'doors': list(fs.DOORS),
        'part_tags': list(fast_sources.PART_TAGS),
    }


def scene_venues():
    """(fid, write_scene tags JSON, lon, lat) of the venue points every scene holds."""
    import json
    import venues
    return [(-(4 * 10**12 + n), json.dumps(list(venues.point_tags(venue, record).items()), ensure_ascii=False,
                                           separators=(',', ':')), float(record['lon']), float(record['lat']))
            for n, (venue, record) in enumerate(venues.located())]


def scene_areas(pbf):
    """osmium's areas of a raw tile in its callback order, for the scene command: a way area of
    one outer ring as its id (Rust builds that ring from the way), else osmium's tags and WKB, or
    a mark that create_multipolygon raised. One osmium pass with the area callback only."""
    import json
    import struct
    import osmium
    factory = osmium.geom.WKBFactory()
    out = []

    class Areas(osmium.SimpleHandler):
        def area(self, a):
            if a.from_way() and a.num_rings() == (1, 0):
                out.append(struct.pack('<qB', a.id, 0))
                return
            try:
                wkb = factory.create_multipolygon(a)
            except RuntimeError:
                out.append(struct.pack('<qB', a.id, 2))
                return
            wkb = bytes.fromhex(wkb) if isinstance(wkb, str) else bytes(wkb)
            tags = json.dumps([(t.k, t.v) for t in a.tags], ensure_ascii=False).encode('utf-8')
            out.append(struct.pack('<qBI', a.id, 1, len(tags)) + tags + struct.pack('<I', len(wkb)) + wkb)

    Areas().apply_file(str(pbf), locations=True)
    return b'EAR1' + struct.pack('<I', len(out)) + b''.join(out)


_scene_parts = {}


def build_scene(store, entry, out):
    """Store.build_scene + write_scene of a raw tile into out, natively. None when written, else
    why not (no tool or library, the rules changed, or a tile the Rust side leaves to Python)."""
    import json
    import struct
    import subprocess
    exe, geos, proj = tool(), geos_library(), proj_library()
    if exe is None or geos is None or proj is None:
        return 'no native tool, GEOS or PROJ'
    if 'rules' not in _scene_parts:
        fingerprint = rules_fingerprint()
        _scene_parts['ok'] = fingerprint is None or fingerprint == RULES
        _scene_parts['rules'] = scene_rules()
        _scene_parts['venues'] = scene_venues()
    if not _scene_parts['ok']:
        return 'scene rules changed in Python (native_tool.RULES)'
    pbf = Path(store.meta['source']) / entry['file']
    task = {'geos': str(geos), 'proj': str(proj[0]), 'proj_data': str(proj[1]), 'pbf': str(pbf),
            'crs': store.frame.crs, 'origin': [store.frame.cx, store.frame.cy],
            'rules': _scene_parts['rules'], 'venues': _scene_parts['venues']}
    data = json.dumps(task, ensure_ascii=False).encode('utf-8')
    stdin = struct.pack('<I', len(data)) + data + scene_areas(pbf)
    result = subprocess.run([str(exe), '--threads', '1', 'scene', '--out', str(out)], input=stdin,
                            capture_output=True, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    said = result.stdout.decode('utf-8', 'replace').strip()
    if os.environ.get('EARTHNG_SCENE_PROFILE'):
        print(entry['file'], said, result.stderr.decode('utf-8', 'replace').strip())
    if result.returncode:
        return 'native scene failed: ' + result.stderr.decode('utf-8', 'replace').strip()[-500:]
    return None if said.startswith('ok') else said.removeprefix('python ').strip()


# ways_fingerprint() of the read_ways osm/src/ways.rs follows; a change in Python turns it off
WAYS = 'c35e1433d79fc412'


def ways_fingerprint():
    """sha256 of fast_sources.read_ways and foot_bridge, or None where their source is not here."""
    import hashlib
    import inspect
    import fast_sources
    digest = hashlib.sha256()
    try:
        for f in (fast_sources.read_ways, fast_sources.foot_bridge):
            digest.update(inspect.getsource(f).encode('utf-8'))
    except (OSError, TypeError):
        return None
    return digest.hexdigest()[:16]


def read_ways(files, shas):
    """[fast_sources.read_ways(file, sha) for each file], read by earthng-mapbuilder ways (all
    tiles at once, in threads), or None where it cannot (no tool, read_ways changed in Python,
    a tile it leaves to Python: Python reads them all again and raises its own errors)."""
    import hashlib
    import json
    import subprocess
    import tempfile
    import numpy as np
    import fast_sources
    exe = tool()
    if exe is None or not files:
        return None
    fingerprint = ways_fingerprint()
    if fingerprint is not None and fingerprint != WAYS:
        return None
    for path, sha in zip(files, shas):
        if hashlib.sha256(Path(path).read_bytes()).hexdigest() != sha:
            raise ValueError(f'OSM checksum mismatch: {path}')
    task = {'files': [str(f) for f in files], 'drivable': sorted(fast_sources.DRIVABLE),
            'foot': sorted(fast_sources.FOOT_WIDTH)}
    with tempfile.TemporaryDirectory(prefix='earthng-ways-') as folder:
        out = Path(folder) / 'ways.bin'
        result = subprocess.run([str(exe), 'ways', '--out', str(out)], input=json.dumps(task).encode('utf-8'),
                                capture_output=True, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if result.returncode or not result.stdout.startswith(b'ok'):
            return None
        data = out.read_bytes()
    if data[:4] != b'EWY1':
        return None
    count = int.from_bytes(data[4:8], 'little')
    at = 8

    def take(dtype, n):
        nonlocal at
        array = np.frombuffer(data, dtype=dtype, count=n, offset=at)
        at += array.nbytes
        return array
    tile, kind, ident, nodes = take('<u4', count).tolist(), take('u1', count).tolist(), take('<i8', count).tolist(), take('<u4', count)
    total = int(take('<u8', 1)[0])
    refs = take('<i8', total).tolist()
    lon = (take('<i4', total).astype(np.float64) / 1e7).tolist()
    lat = (take('<i4', total).astype(np.float64) / 1e7).tolist()
    tags = json.loads(data[at:])
    start = np.concatenate([[0], np.cumsum(nodes, dtype=np.int64)]).tolist()
    parts = [({}, {}, {}) for _ in files]
    for k in range(count):
        a, b = start[k], start[k + 1]
        roads, feet, decks = parts[tile[k]]
        if kind[k] == 2:
            decks[ident[k]] = list(zip(lon[a:b], lat[a:b]))
        else:
            (roads if kind[k] == 0 else feet)[ident[k]] = (dict(tags[k]), list(zip(refs[a:b], lon[a:b], lat[a:b])))
    return parts
