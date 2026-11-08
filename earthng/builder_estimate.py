"""Conservative planning estimates; timings are observations, never fake progress."""
import math

STAGES = ('Sources', 'Cut tiles', 'Elevation', 'Region index', 'Export', 'Install')


def validate_box(box):
    if len(box) != 4 or any(isinstance(v, bool) or not isinstance(v, (int, float))
                            or not math.isfinite(v) for v in box):
        raise ValueError('The selection needs four finite coordinates.')
    w, s, e, n = box
    if not (-180 <= w < e <= 180 and -90 <= s < n <= 90):
        raise ValueError('Select a non-empty rectangle from west to east, within the map.')
    return list(box)


def area_km2(box):
    w, s, e, n = validate_box(box)
    return 6371.0088 ** 2 * math.radians(e - w) * (math.sin(math.radians(n)) - math.sin(math.radians(s)))


# Seconds per MB of source PBF, measured on Ukraine (841 MB, 16 cores, 2026-10-26): the cut
# reads the whole PBF once (SCAN) and writes the part kept (CUT); DEM is a first download.
KM2_PER_MB = 718        # Ukraine: 603 600 km2 in 841 MB
DOWNLOAD, SCAN, CUT, DEM, INDEX, EXPORT, INSTALL = .3, .65, 1.15, .45, 2.75, 3.3, .005
# The native cut (earthng-mapbuilder cut, docs/MAPBUILDER_RS.md) reads the PBF on every core: Kyiv's
# box from Ukraine's 843 MB in 12 s, the whole country in about a minute.
NATIVE_SCAN, NATIVE_CUT = .014, .07


def estimate(size, box, include, cached_pbf=False, cached_tiles=False, native=None):
    """Seconds per stage (timing.STAGES), or None without the source size. native: the Rust cut
    is there (default: native_tool finds it)."""
    if native is None:
        try:
            import native_tool
            native = native_tool.tool() is not None
        except ImportError:
            native = False
    scan, cut = (NATIVE_SCAN, NATIVE_CUT) if native else (SCAN, CUT)
    if not size:
        return None, 'waiting for source size'
    mb = size / 2**20
    # the part of the source a selection keeps: its area at Ukraine's density, at most all of it
    share = min(1., area_km2(box) / (mb * KM2_PER_MB)) if box else 1.
    part = mb * share
    layers = .55 + .45 * sum(include.values()) / max(1, len(include))
    # Broad planning baseline, deliberately displayed as a range (0.5–2.5x).
    # Even a tiny selection requires scanning the entire source PBF on first use.
    times = [2 if cached_pbf or cached_tiles else 5 + mb * DOWNLOAD,
             1 if cached_tiles else (2 if native else 20) + mb * scan + part * cut,
             5 + part * DEM, 10 + part * INDEX,
             15 + part * EXPORT * layers, 3 + part * INSTALL]
    return times, 'rough estimate; network, disk and OSM density vary'
