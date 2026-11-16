"""Capacity model: what the game thread can take in from the Rust bridge, per kind of model.

    .venv/Scripts/python.exe research/native-bridge/capacity/model.py
    .venv/Scripts/python.exe research/native-bridge/capacity/model.py --scene-objects 30000 --kind-items 10000

Prices are game-thread costs measured on BeamNG 0.40.5 in central Kyiv (capacity/run.py, runs
out/capacity-1116/cap-01..04, research/native-bridge/CAPACITY.md); the link's decode share is from
the round-8 tile pool runs (NIGHT_2026-11-16.md). The tile is the average central-Kyiv tile at
quality 50 (9 tiles of generator output, out/capacity-1116/census-kyiv.json).
"""
import argparse

COSTS = {
    # Forest
    'forest_create_us': 1.6,          # createNewItem, flat from 10k to 300k items
    'forest_tick_us_per_item': 0.46,  # deferred Ticking of a commit: per item standing in each touched kind
    # TSStatic (no collision, warm shape); per 1000 scene objects the call grows
    'tss_create_us': 8.0, 'tss_create_us_per_k': 0.12,
    'tss_move_us': 1.8, 'tss_move_us_per_k': 0.6,     # setPosRot, Lua + the engine's Ticking
    'tss_hide_us': 1.2, 'tss_hide_us_per_k': 0.8,     # setHidden
    # DynamicShapeBatch: one scene object, N instances of one shape
    'dsb_set_us': 0.55,               # setInstance(i, vec3, quat, scale, ColorF), flat to 20k
    # ProceduralMesh
    'mesh_tri_us': 2.0,               # createMesh from Lua tables (tables or vec3 cdata: same)
    'mesh_build_us_per_vert': 1.2,    # making those Lua tables (decode side)
    'object_first_ms': 1.2,           # first drawn frames of a new mesh object (24 objects: ~30 ms)
    'collision_tri_us': 0.27, 'collision_obj_us': 35.0,
    # link (round 8 tile pool; socket alone measured 0.56 ms/MB in 8 KB pieces)
    'recv_ms_per_mb': 2.6, 'decode_ms_per_mb': 14.0, 'garbage_per_byte': 4.2, 'gc_ms_per_mb': 1.2,
}
TILE = {'objects': 140, 'verts': 55977, 'tris': 48109, 'statics': 3149, 'kinds': 27, 'emc_mb': 4.8}


def per_call(c, name, scene_k):
    return c[name] + c.get(name + '_per_k', 0) * scene_k


def tile_ms(c, t, kind_items):
    parts = {
        'receive': t['emc_mb'] * c['recv_ms_per_mb'],
        'decode': t['emc_mb'] * c['decode_ms_per_mb'],
        'gc': t['emc_mb'] * c['garbage_per_byte'] * c['gc_ms_per_mb'],
        'createMesh': t['tris'] * c['mesh_tri_us'] / 1000,
        'firstDraw': t['objects'] * c['object_first_ms'],
        'collision': (t['tris'] * c['collision_tri_us'] + t['objects'] * c['collision_obj_us']) / 1000,
        'forestItems': t['statics'] * c['forest_create_us'] / 1000,
        'forestCommits': t['kinds'] * kind_items * c['forest_tick_us_per_item'] / 1000,
    }
    parts['total'] = sum(parts.values())
    return parts


def main():
    p = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    p.add_argument('--scene-objects', type=float, default=3000, help='SceneObjects in the level (TSStatic, meshes...)')
    p.add_argument('--kind-items', type=float, default=2500, help='items standing in each Forest kind a commit touches')
    p.add_argument('--fps', type=float, default=60)
    a = p.parse_args()
    c, t, k = COSTS, TILE, a.scene_objects / 1000
    parts = tile_ms(c, t, a.kind_items)
    print(f'Game thread for one central-Kyiv tile (q50; {a.kind_items:.0f} items a Forest kind), ms:')
    print('  ' + ', '.join(f'{n} {v:.0f}' for n, v in parts.items()))
    print()
    print(f'Per call at {a.scene_objects:,.0f} scene objects, us: TSStatic create {per_call(c, "tss_create_us", k):.1f}, '
          f'move {per_call(c, "tss_move_us", k):.1f}, hide {per_call(c, "tss_hide_us", k):.1f}; '
          f'DynamicShapeBatch setInstance {c["dsb_set_us"]}; Forest add {c["forest_create_us"]}')
    print()
    head = (f'{"ms/frame":>8} {"tiles/s":>8} {"m/s":>5} {"Forest add/s":>13} {"DSB updates/frame":>18}'
            f' {"TSStatic moves/frame":>21} {"TSStatic new/s":>15} {"mesh tris/s":>12}')
    print(head)
    for b in (2, 4, 8):
        per_s = b * a.fps
        tiles = per_s / parts['total']
        print(f'{b:>8} {tiles:>8.2f} {tiles * 500 / 3:>5.0f} {per_s * 1000 / c["forest_create_us"]:>13,.0f}'
              f' {b * 1000 / c["dsb_set_us"]:>18,.0f} {b * 1000 / per_call(c, "tss_move_us", k):>21,.0f}'
              f' {per_s * 1000 / per_call(c, "tss_create_us", k):>15,.0f} {per_s * 1000 / c["mesh_tri_us"]:>12,.0f}')
    print('  (m/s: straight drive, a new row of 3 tiles of 500 m; intake only, the rest of the frame is the world)')
    print()
    bands = [(500, 60), (2000, 10), (7500, 2)]
    calls = sum(n * hz for n, hz in bands)
    total = sum(n for n, _ in bands)
    for name, us in (('TSStatic setPosRot', per_call(c, 'tss_move_us', k + total / 1000)),
                     ('DynamicShapeBatch', c['dsb_set_us'])):
        print(f'{total:,} moving agents {bands} (count, Hz) via {name}: {calls * us / 1000 / a.fps:.1f} ms/frame')


if __name__ == '__main__':
    main()
