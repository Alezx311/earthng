"""How big a pedestrian graph and a lane graph would be if the pack builder baked them.

Reads real v2 blocks (extracted from a pack, see docs/RUST_IN_MOD.md) with the reference decoder and
counts what a walk graph is made of: mapped paths (lines footway/path/pedestrian/steps), sidewalks
along city roads (two offset polylines per road, the rule the generator approximates), crossings,
entrances and shops/POIs as places people go. Sizes assume the EGB3 idea: int32 centimetres, an
edge as two u32 node indices, a few u32 attributes.

    .venv\\Scripts\\python.exe research\\rust-in-mod\\walk_estimate.py <block.bin> [...]
"""
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'earthng'))
import country_format as cf  # noqa: E402

WALK_LINES = {'footway', 'footway_asphalt', 'path', 'pedestrian', 'steps', 'cycleway', 'bridleway'}
SIDEWALK_ROADS = {'primary', 'primary_link', 'secondary', 'secondary_link', 'tertiary', 'tertiary_link',
                  'residential', 'living_street', 'unclassified', 'service'}
PLACES = {'entrance', 'shop', 'poi', 'stop', 'door'}


def main(paths):
    total = Counter()
    for path in paths:
        data = Path(path).read_bytes()
        t = time.perf_counter()
        for slot, (at, end) in sorted(cf.decode_block(data).items()):
            cell = cf.decode_cell(data, (0.0, 0.0), (0, 0, 1000, 1000), at, end)
            total['cells'] += 1
            total['cellBytes'] += end - at
            seen = set()
            for r in cell['roads']:
                if r['id'] in seen:
                    continue
                seen.add(r['id'])
                hw = r['tags'].get('highway', '')
                n = len(r['points'])
                total['roadPoints'] += n
                total['laneEdges'] += max(0, n - 1)
                if hw in SIDEWALK_ROADS and r['tags'].get('sidewalk', 'both') not in ('no', 'none', 'separate'):
                    sides = {'left': 1, 'right': 1}.get(r['tags'].get('sidewalk'), 2)
                    total['sidewalkPoints'] += sides * n
                    total['sidewalkEdges'] += sides * max(0, n - 1)
            for ln in cell['lines']:
                if ln['kind'] in WALK_LINES:
                    n = len(ln['points'])
                    total['pathPoints'] += n
                    total['pathEdges'] += max(0, n - 1)
            for p in cell['points']:
                k = p['kind']
                if k == 'crossing':
                    total['crossings'] += 1
                elif k in PLACES or 'shop' in p['tags'] or 'amenity' in p['tags']:
                    total['places'] += 1
                total['kind:' + k] += 1
            total['buildings'] += len(cell['buildings'])
        total['decodeS'] += time.perf_counter() - t
    nodes = total['sidewalkPoints'] + total['pathPoints'] + 2 * total['crossings']
    edges = total['sidewalkEdges'] + total['pathEdges'] + total['crossings']
    walk_bytes = nodes * 12 + edges * 12 + total['places'] * 16
    lane_bytes = total['roadPoints'] * 12 + total['laneEdges'] * 12
    km2 = total['cells']
    print(f"cells {km2} (1 km2 each), v2 cell bytes {total['cellBytes'] / 1e6:.1f} MB, decode {total['decodeS']:.1f} s")
    print(f"walk graph: {nodes} nodes, {edges} edges, {total['places']} places, {total['crossings']} crossings")
    print(f"  sidewalk points {total['sidewalkPoints']}, path points {total['pathPoints']}, buildings {total['buildings']}")
    print(f"  ~{walk_bytes / 1e6:.2f} MB raw ({walk_bytes / km2 / 1e3:.0f} KB/km2), "
          f"{100 * walk_bytes / max(1, total['cellBytes']):.0f}% of the cells")
    print(f"lane graph (road polylines + lanes): ~{lane_bytes / 1e6:.2f} MB raw ({lane_bytes / km2 / 1e3:.0f} KB/km2)")
    print('point kinds:', {k[5:]: v for k, v in total.items() if k.startswith('kind:') and v >= 50})


if __name__ == '__main__':
    main(sys.argv[1:])
