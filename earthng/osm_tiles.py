"""Cut an OSM package into a static tile archive for streaming (docs/NATIVE_MODS.md, «Дані»).

    C:/js/Earth2Road/.venv/Scripts/python.exe earthng/osm_tiles.py C:/js/Earth2Road/out/districts/.inputs/geofabrik/ukraine-260918-kyiv.osm.pbf --out data/osm_tiles/kyiv-260918

A fixed global grid of CELL x CELL degrees; tile (ix, iy) covers its cell grown by BUFFER degrees
on every side and is written as ``<ix>_<iy>.osm.pbf``. The selection per tile is the one of
Earth2Road's OSM extraction (earthng/osm_select.py) for the buffered box (ways with a node inside, complete;
restriction/multipolygon/landmark relations with a member inside, completed; POI nodes inside),
so a window that lies inside a tile's coverage cuts the same data from the tile as from the
whole package. One read for all tiles instead of three passes per tile.

index.json lists every tile with its cell, coverage (the buffered box: what the tile may be
declared to cover in ``earth2road data import --coverage``), size, SHA-256 and counts.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import sys
import time

import osmium

sys.path.insert(0, str(Path(__file__).resolve().parent))
from osm_select import VERSION as SELECT, landmark_category, poi  # noqa: E402

CELL = 0.05
BUFFER = 0.01


def cells_of(lon, lat):
    """Tile keys whose buffered box contains the point."""
    xs = range(math.floor((lon - BUFFER) / CELL), math.floor((lon + BUFFER) / CELL) + 1)
    ys = range(math.floor((lat - BUFFER) / CELL), math.floor((lat + BUFFER) / CELL) + 1)
    return [(x, y) for x in xs for y in ys]


def cell_box(key):
    x, y = key
    return [round(x * CELL, 6), round(y * CELL, 6), round((x + 1) * CELL, 6), round((y + 1) * CELL, 6)]


def coverage(key):
    w, s, e, n = cell_box(key)
    return [round(w - BUFFER, 6), round(s - BUFFER, 6), round(e + BUFFER, 6), round(n + BUFFER, 6)]


def region_keys(region):
    """Tile keys whose cell overlaps the region (west, south, east, north) with positive area.

    A tile keeps everything the source has within its coverage, so a tile at the edge of the
    source is as complete as the source is. Cuts used to keep only tiles whose whole coverage lay
    inside the package box: every cell an extract's box cut through was dropped with its data
    (Narva at Estonia's edge, 13-43 % of the London and Tokyo spot extracts)."""
    rw, rs, re, rn = region
    keys = []
    for x in range(math.floor(rw / CELL) - 1, math.floor(re / CELL) + 2):
        for y in range(math.floor(rs / CELL) - 1, math.floor(rn / CELL) + 2):
            w, s, e, n = cell_box((x, y))
            if w < re and rw < e and s < rn and rs < n:
                keys.append((x, y))
    return keys


def package_of(keys, region):
    """The box the tiles of keys cover (their buffered cells); the region when there are none."""
    if not keys:
        return list(region)
    c = [coverage(k) for k in keys]
    return [min(v[0] for v in c), min(v[1] for v in c), max(v[2] for v in c), max(v[3] for v in c)]


def region(selection, extract=None):
    """The region a cut keeps for a selected area: the selection grown to whole cells, clipped to
    the extract's own box where the source has no data. A selection kept as is lost the cells
    round its edges: 12.7 x 11 km round Tallinn became three cells (8.5 x 5.6 km)."""
    w, s, e, n = selection
    box = [round(math.floor(w / CELL) * CELL, 6), round(math.floor(s / CELL) * CELL, 6),
           round((math.floor(e / CELL) + 1) * CELL, 6), round((math.floor(n / CELL) + 1) * CELL, 6)]
    if extract is not None:
        box = [max(box[0], extract[0]), max(box[1], extract[1]), min(box[2], extract[2]), min(box[3], extract[3])]
    return box


def source_box(selection, extract=None):
    """The package box of a selection's cut (west, south, east, north): what its tiles cover."""
    r = region(selection, extract)
    return package_of(region_keys(r), r)


def cut(pbf, out, region=None):
    """Tiles of every cell overlapping region (default: the PBF header's box)."""
    t0 = time.monotonic()
    out.mkdir(parents=True)
    if region is None:
        box = osmium.io.Reader(str(pbf), osmium.osm.osm_entity_bits.NOTHING).header().box()
        region = [box.bottom_left.lon, box.bottom_left.lat, box.top_right.lon, box.top_right.lat]
    region = list(region)
    keys = sorted(region_keys(region))
    package_box = package_of(keys, region)
    bit = {k: 1 << i for i, k in enumerate(keys)}

    def mask(lon, lat):
        m = 0
        for k in cells_of(lon, lat):
            m |= bit.get(k, 0)
        return m

    # Pass 1: tile masks of nodes inside, ways touching, relevant relations.
    node_inside, poi_nodes, way_tiles = {}, {}, {}
    rel_members, relevant = {}, set()
    processor = osmium.FileProcessor(str(pbf)).with_locations()
    for obj in processor:
        if obj.is_node():
            if obj.location.valid():
                m = mask(obj.location.lon, obj.location.lat)
                if m:
                    node_inside[obj.id] = m
                    if obj.tags and (poi(obj.tags) or landmark_category(obj.tags)):
                        poi_nodes[obj.id] = m
        elif obj.is_way():
            m = 0
            for nd in obj.nodes:
                m |= node_inside.get(nd.ref, 0)
            if m:
                way_tiles[obj.id] = m
        elif obj.is_relation():
            rel_members[obj.id] = [(mb.type, mb.ref) for mb in obj.members]
            if obj.tags.get('type') in ('restriction', 'multipolygon') or landmark_category(obj.tags):
                relevant.add(obj.id)
    print(f'pass 1: {len(keys)} tiles, {len(node_inside)} nodes inside, {len(way_tiles)} ways '
          f'({time.monotonic()-t0:.0f} s)', flush=True)

    # Relations: spatial hits per tile, then nested parents, then complete all descendants.
    rel_tiles = {}
    changed = True
    while changed:
        changed = False
        for rid in relevant:
            m = rel_tiles.get(rid, 0)
            for kind, ref in rel_members[rid]:
                if kind == 'w':
                    m |= way_tiles.get(ref, 0)
                elif kind == 'n':
                    m |= node_inside.get(ref, 0)
                elif kind == 'r':
                    m |= rel_tiles.get(ref, 0)
            if m != rel_tiles.get(rid, 0):
                rel_tiles[rid] = m
                changed = True
    # The hits above used ways touching a tile; completion adds members to the tile.
    extra_ways, extra_nodes = {}, {}
    pending = list(rel_tiles.items())
    while pending:
        rid, m = pending.pop()
        for kind, ref in rel_members.get(rid, []):
            if kind == 'w':
                if (extra_ways.get(ref, 0) | way_tiles.get(ref, 0)) & m != m:
                    extra_ways[ref] = extra_ways.get(ref, 0) | m
            elif kind == 'n':
                extra_nodes[ref] = extra_nodes.get(ref, 0) | m
            elif kind == 'r' and (rel_tiles.get(ref, 0) & m) != m:
                rel_tiles[ref] = rel_tiles.get(ref, 0) | m
                pending.append((ref, rel_tiles[ref]))
    for wid, m in extra_ways.items():
        way_tiles[wid] = way_tiles.get(wid, 0) | m

    # Pass 2: every node of a selected way goes to that way's tiles.
    node_tiles = dict(poi_nodes)
    for nid, m in extra_nodes.items():
        node_tiles[nid] = node_tiles.get(nid, 0) | m
    for obj in osmium.FileProcessor(str(pbf), osmium.osm.WAY):
        m = way_tiles.get(obj.id)
        if m:
            for nd in obj.nodes:
                node_tiles[nd.ref] = node_tiles.get(nd.ref, 0) | m
    print(f'pass 2: {len(node_tiles)} nodes selected ({time.monotonic()-t0:.0f} s)', flush=True)

    # A relation stays in a tile only when all its members (recursively) are written there.
    written_w = way_tiles
    changed = True
    while changed:
        changed = False
        for rid, m in list(rel_tiles.items()):
            keep = m
            for kind, ref in rel_members.get(rid, []):
                if kind == 'n':
                    keep &= node_tiles.get(ref, 0)
                elif kind == 'w':
                    keep &= written_w.get(ref, 0)
                elif kind == 'r':
                    keep &= rel_tiles.get(ref, 0)
            if keep != m:
                rel_tiles[rid] = keep
                changed = True

    # Pass 3: write all tiles in file order.
    writers = {k: osmium.SimpleWriter(osmium.io.File(str(out / f'{k[0]}_{k[1]}.osm.pbf.part'), 'pbf')) for k in keys}
    counts = {k: {'nodes': 0, 'ways': 0, 'relations': 0} for k in keys}
    table = {'n': (node_tiles, 'nodes', 'add_node'), 'w': (way_tiles, 'ways', 'add_way'),
             'r': (rel_tiles, 'relations', 'add_relation')}
    try:
        for obj in osmium.FileProcessor(str(pbf)):
            tiles, label, method = table[obj.type_str()]
            m = tiles.get(obj.id, 0)
            if not m:
                continue
            for k in _mask_keys(m, keys):
                getattr(writers[k], method)(obj)
                counts[k][label] += 1
    finally:
        for w in writers.values():
            w.close()
    index = {'cell': CELL, 'buffer': BUFFER, 'source': Path(pbf).name, 'package_box': package_box,
             'region': region, 'select': SELECT, 'tiles': {}}
    for k in keys:
        part = out / f'{k[0]}_{k[1]}.osm.pbf.part'
        if counts[k]['ways'] == 0:
            part.unlink()
            continue
        final = part.with_suffix('')
        part.replace(final)
        index['tiles'][f'{k[0]}_{k[1]}'] = {
            'file': final.name, 'cell': cell_box(k), 'coverage': coverage(k), 'bytes': final.stat().st_size,
            'sha256': hashlib.sha256(final.read_bytes()).hexdigest(), **counts[k]}
    index['seconds'] = round(time.monotonic() - t0, 1)
    (out / 'index.json').write_text(json.dumps(index, indent=1), encoding='utf8')
    sizes = [t['bytes'] for t in index['tiles'].values()] or [0]
    print(f"written {len(index['tiles'])} tiles, {sum(sizes)/2**20:.1f} MB total, median {sorted(sizes)[len(sizes)//2]/2**10:.0f} KB, "
          f"max {max(sizes)/2**20:.2f} MB ({index['seconds']} s)", flush=True)
    return index


def _mask_keys(mask, order):
    """Keys whose bit is set. ``order[i]`` was stored as bit ``1 << i``."""
    while mask:
        bit = mask & -mask
        yield order[bit.bit_length() - 1]
        mask -= bit


def tile_for(index, bbox):
    """The tile whose coverage contains the whole bbox (west, south, east, north), or None.

    A tile key is the grid cell, so only the cells under the bbox can match. Coverages
    overlap by the buffer; the lexicographically first key is the one a scan of the
    sorted index used to return.
    """
    w, s, e, n = bbox
    cell = index.get('cell', CELL)
    buffer = index.get('buffer', BUFFER)
    tiles = index['tiles']

    def span(lo, hi):
        # ix*cell - buffer <= lo and (ix+1)*cell + buffer >= hi, plus one cell of rounding.
        start = math.floor((hi - buffer) / cell - 1) - 1
        stop = math.floor((lo + buffer) / cell) + 1
        return range(start, stop + 1)

    found = None
    for ix in span(w, e):
        for iy in span(s, n):
            key = f'{ix}_{iy}'
            tile = tiles.get(key)
            if tile is None:
                continue
            cw, cs, ce, cn = tile['coverage']
            if cw <= w and cs <= s and e <= ce and n <= cn and (found is None or key < found[0]):
                found = (key, tile)
    return found


def main():
    p = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    p.add_argument('pbf', type=Path)
    p.add_argument('--out', type=Path, required=True, help='new directory')
    p.add_argument('--region', type=float, nargs=4, metavar=('W', 'S', 'E', 'N'),
                   help='cut every tile whose cell overlaps this box (default: the header box)')
    a = p.parse_args()
    if a.out.exists():
        raise SystemExit(f'{a.out} exists')
    cut(a.pbf, a.out, a.region)


if __name__ == '__main__':
    main()
