"""Cars of the traffic flow (mod/lua/ge/extensions/e2r/flow.lua): low-poly shapes, one per paint.

A flow car is a TSStatic without collision moved by Lua every frame, so its shape is as cheap as a
car can look from 30 m on: the body and glasshouse of the generator's box car (generator.lua
parkedCar, 4.4 x 1.76 m), six-sided wheels, lamps front and back. ~120 triangles. Forward is +x,
up +z, the origin on the ground under the middle of the car.
"""
import json

BODY = [(-2.15, .30), (2.15, .30), (2.22, .52), (2.12, .74), (1.05, .84), (-1.75, .87), (-2.17, .80), (-2.22, .52)]
GLASS = [(-1.72, .84), (1.02, .82), (.22, 1.38), (-1.22, 1.41)]
WHEEL_X, WHEEL_R = 1.36, .31
# sRGB, as the game's baseColorFactor takes it: the common colours of a city's cars
PAINTS = [
    ('white', (.86, .86, .84)), ('black', (.05, .05, .06)), ('silver', (.62, .63, .65)), ('grey', (.33, .34, .36)),
    ('blue', (.10, .17, .35)), ('red', (.55, .07, .06)), ('beige', (.70, .64, .52)), ('green', (.12, .24, .16)),
]
# the share of each paint among the flow's cars (flow.lua picks by these)
PAINT_SHARE = [24, 20, 18, 14, 8, 7, 5, 4]
SHARED = {
    'glass': {'baseColorFactor': [.08, .10, .12, 1], 'roughnessFactor': .15, 'metallicFactor': .2},
    'tyre': {'baseColorFactor': [.04, .04, .04, 1], 'roughnessFactor': .9},
    'lamp': {'baseColorFactor': [.95, .93, .85, 1], 'roughnessFactor': .3},
    'tail': {'baseColorFactor': [.60, .03, .03, 1], 'roughnessFactor': .3},
}
PREFIX = 'e2r_flow_'


def shape_path(level, paint):
    return f'/levels/{level}/art/flow/car_{paint}.dae'


def _extrude(tris, material, profile, y0, y1):
    """A prism of a convex (x, z) profile from y0 to y1: caps and sides, each face its own normal."""
    pts = [(x, y0, z) for x, z in profile]
    far = [(x, y1, z) for x, z in profile]
    faces = []
    for k in range(1, len(profile) - 1):
        faces.append((pts[0], pts[k], pts[k + 1]))
        faces.append((far[0], far[k + 1], far[k]))
    n = len(profile)
    for k in range(n):
        a, b = pts[k], pts[(k + 1) % n]
        c, d = far[(k + 1) % n], far[k]
        faces.append((a, b, c))
        faces.append((a, c, d))
    centre = tuple(sum(p[i] for p in pts + far) / (2 * n) for i in range(3))
    for f in faces:
        tris.append((material, _outward(f, centre)))


def _outward(face, centre):
    a, b, c = face
    u = [b[i] - a[i] for i in range(3)]
    v = [c[i] - a[i] for i in range(3)]
    nrm = (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0])
    mid = [(a[i] + b[i] + c[i]) / 3 - centre[i] for i in range(3)]
    if sum(nrm[i] * mid[i] for i in range(3)) < 0:
        return (a, c, b)
    return face


def _quad(tris, material, corners, normal_hint):
    a, b, c, d = corners
    for f in ((a, b, c), (a, c, d)):
        centre = tuple(f[0][i] - normal_hint[i] for i in range(3))
        tris.append((material, _outward(f, centre)))


def triangles(paint):
    tris = []
    _extrude(tris, PREFIX + paint, BODY, -.88, .88)
    _extrude(tris, PREFIX + 'glass', GLASS, -.76, .76)
    ring = []
    import math
    for k in range(6):
        t = k * math.pi / 3 + math.pi / 6
        ring.append((math.cos(t) * WHEEL_R, WHEEL_R + math.sin(t) * WHEEL_R))
    for wx in (-WHEEL_X, WHEEL_X):
        wheel = [(x + wx, z) for x, z in ring]
        _extrude(tris, PREFIX + 'tyre', wheel, .70, .92)
        _extrude(tris, PREFIX + 'tyre', wheel, -.92, -.70)
    for side in (-1, 1):
        y0, y1 = side * .58, side * .82
        lo, hi = min(y0, y1), max(y0, y1)
        _quad(tris, PREFIX + 'lamp', [(2.225, lo, .58), (2.225, hi, .58), (2.225, hi, .68), (2.225, lo, .68)], (1, 0, 0))
        _quad(tris, PREFIX + 'tail', [(-2.225, lo, .60), (-2.225, hi, .60), (-2.225, hi, .72), (-2.225, lo, .72)], (-1, 0, 0))
    return tris


def car_dae(paint):
    tris = triangles(paint)
    by_material = {}
    for material, face in tris:
        by_material.setdefault(material, []).append(face)
    positions, normals, blocks = [], [], []
    for material, faces in by_material.items():
        idx = []
        for a, b, c in faces:
            u = [b[i] - a[i] for i in range(3)]
            v = [c[i] - a[i] for i in range(3)]
            n = (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0])
            length = sum(x * x for x in n) ** .5 or 1
            normals.append(tuple(x / length for x in n))
            ni = len(normals) - 1
            for p in (a, b, c):
                positions.append(p)
                idx += [len(positions) - 1, ni]
        blocks.append((material, len(faces), idx))
    fmt = lambda rows: ' '.join(f'{x:.4f}' for row in rows for x in row)
    effects = ''.join(
        f'<effect id="{m}-fx"><profile_COMMON><technique sid="common"><lambert><diffuse><color>0.5 0.5 0.5 1</color>'
        f'</diffuse></lambert></technique></profile_COMMON></effect>' for m, _, _ in blocks)
    materials = ''.join(f'<material id="{m}" name="{m}"><instance_effect url="#{m}-fx"/></material>' for m, _, _ in blocks)
    prims = ''.join(
        f'<triangles material="{m}" count="{count}"><input semantic="VERTEX" source="#g0-vtx" offset="0"/>'
        f'<input semantic="NORMAL" source="#g0-nrm" offset="1"/><p>{" ".join(map(str, idx))}</p></triangles>'
        for m, count, idx in blocks)
    binds = ''.join(f'<instance_material symbol="{m}" target="#{m}"/>' for m, _, _ in blocks)
    return f'''<?xml version="1.0" encoding="utf-8"?>
<COLLADA xmlns="http://www.collada.org/2005/11/COLLADASchema" version="1.4.1">
<asset><unit name="meter" meter="1"/><up_axis>Z_UP</up_axis></asset>
<library_effects>{effects}</library_effects>
<library_materials>{materials}</library_materials>
<library_geometries><geometry id="g0" name="g0"><mesh>
<source id="g0-pos"><float_array id="g0-pos-array" count="{3 * len(positions)}">{fmt(positions)}</float_array><technique_common><accessor source="#g0-pos-array" count="{len(positions)}" stride="3"><param name="X" type="float"/><param name="Y" type="float"/><param name="Z" type="float"/></accessor></technique_common></source>
<source id="g0-nrm"><float_array id="g0-nrm-array" count="{3 * len(normals)}">{fmt(normals)}</float_array><technique_common><accessor source="#g0-nrm-array" count="{len(normals)}" stride="3"><param name="X" type="float"/><param name="Y" type="float"/><param name="Z" type="float"/></accessor></technique_common></source>
<vertices id="g0-vtx"><input semantic="POSITION" source="#g0-pos"/></vertices>
{prims}
</mesh></geometry></library_geometries>
<library_visual_scenes><visual_scene id="Scene"><node id="base00" name="base00"><node id="start01" name="start01"><node id="car" name="car"><instance_geometry url="#g0"><bind_material><technique_common>{binds}</technique_common></bind_material></instance_geometry></node></node></node></visual_scene></library_visual_scenes>
<scene><instance_visual_scene url="#Scene"/></scene></COLLADA>
'''


def materials():
    out = {}
    for name, rgb in PAINTS:
        out[PREFIX + name] = {'baseColorFactor': [*rgb, 1], 'roughnessFactor': .35, 'metallicFactor': .4}
    for name, stage in SHARED.items():
        out[PREFIX + name] = stage
    return {m: {'name': m, 'mapTo': m, 'class': 'Material', 'version': 1.5, 'Stages': [stage, {}, {}, {}]}
            for m, stage in out.items()}


def level_files(level):
    files = {f'levels/{level}/art/flow/car_{name}.dae': car_dae(name) for name, _ in PAINTS}
    files[f'levels/{level}/art/flow/main.materials.json'] = json.dumps(materials(), indent=2)
    return files
