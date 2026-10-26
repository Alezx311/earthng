"""Conservative planning estimates; timings are observations, never fake progress."""
import json
import math
from pathlib import Path

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


def duration(seconds):
    seconds = max(0, seconds)
    if seconds < 60:
        return f'{max(1, round(seconds))} s'
    if seconds < 3600:
        return f'{math.ceil(seconds / 60)} min'
    return f'{seconds / 3600:.1f} h'


def signature(place_id, box, include, cached_pbf, cached_tiles):
    return json.dumps([place_id, box, include, cached_pbf, cached_tiles], sort_keys=True)


# Seconds per MB of source PBF, measured on Ukraine (841 MB, 16 cores, 2026-10-26): the cut
# reads the whole PBF once (SCAN) and writes the part kept (CUT); DEM is a first download.
KM2_PER_MB = 718        # Ukraine: 603 600 km2 in 841 MB
DOWNLOAD, SCAN, CUT, DEM, INDEX, EXPORT, INSTALL = .3, .65, 1.15, .45, 2.75, 3.3, .005


def estimate(size, box, include, cached_pbf=False, cached_tiles=False, previous=None):
    if isinstance(previous, (list, tuple)) and len(previous) == len(STAGES) and all(
            not isinstance(v, bool) and isinstance(v, (int, float)) and math.isfinite(v) and v >= 0 for v in previous):
        return list(previous), 'previous successful build'
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
             1 if cached_tiles else 20 + mb * SCAN + part * CUT,
             5 + part * DEM, 10 + part * INDEX,
             15 + part * EXPORT * layers, 3 + part * INSTALL]
    return times, 'rough estimate; network, disk and OSM density vary'


def load_history(path):
    try:
        value = json.loads(Path(path).read_text(encoding='utf-8'))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def save_history(path, history):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(dict(list(history.items())[-100:])), encoding='utf-8')
    temporary.replace(path)
