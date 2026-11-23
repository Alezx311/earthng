"""Test shapes for p1_shape_load.lua, written into a test profile's e2r_tiles/ folder.

    python research/fast-tiles/make_shapes.py <out>/user --materials e2rf_ground,e2rf_asphalt,...

The same wavy square as a compiled shape (.cdae) in the layouts a tile could take: one material, twenty
materials in one mesh, twenty objects of one material each, and a big one.
"""
import argparse
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'earthng'))
import cdae  # noqa: E402


def square(n, materials, name='tile', size=100.0):
    mesh = cdae.grid(n, size=size, materials=len(materials), name=name)
    mesh['parts'] = [(materials[k], part) for k, (_, part) in enumerate(mesh['parts'])]
    return mesh


def strips(n, materials, size=100.0):
    """The square as one object per material: strips side by side."""
    out = []
    rows = max(1, n // len(materials))
    whole = cdae.grid(n, size=size, materials=1)
    w = n + 1
    for k, material in enumerate(materials):
        j0, j1 = k * rows, (k + 1) * rows
        first, last = j0 * w, (j1 + 1) * w
        part = [v - first for v in whole['parts'][0][1][j0 * n * 6:j1 * n * 6]]
        out.append({'name': f'strip{k}', 'positions': whole['positions'][first * 3:last * 3],
                    'normals': whole['normals'][first * 3:last * 3], 'uvs': whole['uvs'][first * 2:last * 2],
                    'parts': [(material, part)]})
    return out


def main():
    p = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    p.add_argument('user', type=Path)
    p.add_argument('--materials', required=True, help='comma list of materials that exist in the game')
    a = p.parse_args()
    names = [m for m in a.materials.split(',') if m]
    folder = a.user / 'current' / 'e2r_tiles'
    one = names[:1]
    twenty = (names * 20)[:20]
    made = {
        'g20k_m1': [square(100, one)],
        'g20k_m1_b': [square(100, one)],
        'g20k_m1_c': [square(100, one)],
        'g50k_m20': [square(158, twenty)],
        'g50k_o20': strips(158, twenty),
        'g200k_m1': [square(316, one)],
        'g500k_m1': [square(500, one)],
    }
    for name, meshes in made.items():
        data = cdae.write(folder / f'{name}.cdae', meshes, visible_size=2.0)
        triangles = sum(len(part) for mesh in meshes for _, part in mesh['parts']) // 3
        print(f'{name}: {triangles} triangles, {len(data) / 1e6:.2f} MB')
    # the same 20k square with a detail level the engine may drop to: 5k and 1.2k triangles
    print('written to', folder)


if __name__ == '__main__':
    main()
