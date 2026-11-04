"""Cars of the traffic flow (mod/lua/ge/extensions/e2r/flow.lua): low-poly shapes, one per body and paint.

A flow car is a TSStatic without collision moved by Lua every frame, so its shape is as cheap as a
car can look from 10 m on, ~450 triangles:
  - the lower body lofted through cross-sections along the car (round corners in plan, a rounded
    shoulder, dark sills), the glasshouse on it (windscreen, side and rear glass, a painted roof
    and pillar), bumpers, grille, plates, lamps, mirrors;
  - ten-sided wheels with a rim and a dark arch behind each;
  - normals smoothed across edges under SMOOTH degrees, so the loft reads round, and kept sharp
    where glass meets paint.
Four bodies (sedan, hatchback, crossover, a minibus like a city's marshrutka). Forward is +x, up +z,
the origin on the ground under the middle of the car.
"""
import json
import math

# sRGB, as the game's baseColorFactor takes it: the common colours of a city's cars
PAINTS = [
    ('white', (.86, .86, .84)), ('black', (.05, .05, .06)), ('silver', (.62, .63, .65)), ('grey', (.33, .34, .36)),
    ('blue', (.10, .17, .35)), ('red', (.55, .07, .06)), ('beige', (.70, .64, .52)), ('green', (.12, .24, .16)),
]
# the share of each paint among the flow's cars (flow.lua picks by these)
PAINT_SHARE = [24, 20, 18, 14, 8, 7, 5, 4]

# Bodies: length, width, wheel radius, wheelbase, sill height; the top line of the lower body
# (x, z) front to back; the glasshouse: windscreen foot, roof front, roof back, rear glass foot
# (x), roof height, and how far its foot and its roof sit in from the body's side.
BODIES = [
    ('sedan', dict(L=4.55, W=1.78, R=.31, WB=2.66, z0=.30,
                   top=[(2.275, .64), (2.0, .75), (1.0, .84), (-.9, .88), (-1.6, .90), (-2.12, .87), (-2.275, .76)],
                   cab=(1.0, .22, -.78, -1.5), roof=1.44, inset=(.10, .27))),
    ('hatch', dict(L=4.10, W=1.74, R=.30, WB=2.56, z0=.30,
                   top=[(2.05, .62), (1.78, .73), (.95, .83), (-1.2, .90), (-1.95, .93), (-2.05, .88)],
                   cab=(.95, .15, -1.68, -1.98), roof=1.47, inset=(.10, .25))),
    ('suv', dict(L=4.60, W=1.86, R=.36, WB=2.70, z0=.40,
                 top=[(2.30, .80), (2.02, .93), (1.08, 1.03), (-1.5, 1.07), (-2.18, 1.08), (-2.30, .98)],
                 cab=(1.08, .30, -1.98, -2.20), roof=1.70, inset=(.10, .20))),
    ('van', dict(L=5.10, W=1.96, R=.34, WB=3.20, z0=.38,
                 top=[(2.55, .82), (2.30, .98), (1.62, 1.10), (-2.5, 1.12), (-2.55, 1.05)],
                 cab=(1.62, .98, -2.48, -2.54), roof=2.20, inset=(.08, .13))),
]
# the share of each body among the flow's cars
BODY_SHARE = [40, 30, 22, 8]

SHARED = {
    'glass': {'baseColorFactor': [.05, .07, .09, 1], 'roughnessFactor': .08, 'metallicFactor': .6},
    'trim': {'baseColorFactor': [.035, .035, .04, 1], 'roughnessFactor': .75},
    'tyre': {'baseColorFactor': [.03, .03, .03, 1], 'roughnessFactor': .92},
    'rim': {'baseColorFactor': [.55, .56, .58, 1], 'roughnessFactor': .35, 'metallicFactor': .8},
    'lamp': {'baseColorFactor': [.92, .92, .88, 1], 'roughnessFactor': .15, 'metallicFactor': .3},
    'tail': {'baseColorFactor': [.55, .02, .02, 1], 'roughnessFactor': .25},
    'plate': {'baseColorFactor': [.85, .86, .86, 1], 'roughnessFactor': .5},
}
PREFIX = 'e2r_flow_'
SMOOTH = 50          # degrees: faces of one material meeting flatter than this share their normals


def shape_path(level, body, paint):
    return f'/levels/{level}/art/flow/car_{body}_{paint}.dae'


# --- geometry -----------------------------------------------------------------------------------
def _tri(tris, material, a, b, c, out):
    """A triangle facing along `out` (a direction away from the solid)."""
    u = [b[i] - a[i] for i in range(3)]
    v = [c[i] - a[i] for i in range(3)]
    n = (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0])
    if sum(n[i] * out[i] for i in range(3)) < 0:
        b, c = c, b
    tris.append((material, (a, b, c)))


def _quad(tris, material, a, b, c, d, out):
    _tri(tris, material, a, b, c, out)
    _tri(tris, material, a, c, d, out)


def _away(points, centre):
    return [sum(p[i] for p in points) / len(points) - centre[i] for i in range(3)]


def _interp(line, x):
    """z of a (x, z) line given front to back (x falling) at x."""
    if x >= line[0][0]:
        return line[0][1]
    for (x0, z0), (x1, z1) in zip(line, line[1:]):
        if x1 <= x <= x0:
            f = (x0 - x) / (x0 - x1) if x0 != x1 else 0
            return z0 + (z1 - z0) * f
    return line[-1][1]


def _ring(w, zb, zt):
    """The lower body's cross-section (y, z), counter-clockwise from the bottom right, and which of
    its edges are sill (trim): the bottom and the chamfers under the sides."""
    c = min(.07, (zt - zb) / 5)
    pts = [(w - c * .8, zb), (w, zb + c), (w - .015, zt - c * 1.6), (w - c * 1.5, zt),
           (-w + c * 1.5, zt), (-w + .015, zt - c * 1.6), (-w, zb + c), (-w + c * .8, zb)]
    trim = {0, 6, 7}           # edge k joins pts[k] and pts[k + 1]
    return pts, trim


def _body(tris, paint, b):
    L, W, z0, top = b['L'], b['W'], b['z0'], b['top']
    w = W / 2
    h = L / 2
    # stations front to back: round corners in plan, the ends a little up (approach angles)
    xs = [h, h - .05, h - .18, h - .45] + [x for x in (b['cab'][0], .4, -.4, b['cab'][3]) if -h + .5 < x < h - .5]
    xs += [-h + .45, -h + .18, -h + .05, -h]
    xs = sorted(set(round(x, 3) for x in xs), reverse=True)
    width = {0: .84, .05: .95, .18: .99}
    rings = []
    for x in xs:
        end = min(abs(h - x), abs(h + x))
        f = width.get(round(end, 2), 1.0)
        zb = z0 + (.05 if end < .01 else (.03 if end < .1 else 0))
        pts, trim = _ring(w * f, zb, _interp(top, x))
        rings.append((x, pts, trim))
    for (xa, pa, trim), (xb, pb, _) in zip(rings, rings[1:]):
        n = len(pa)
        zc = (min(z for _, z in pa) + max(z for _, z in pa)) / 2
        for k in range(n):
            a = (xa, *pa[k]); b2 = (xa, *pa[(k + 1) % n])
            c = (xb, *pb[(k + 1) % n]); d = (xb, *pb[k])
            # away from the loft's axis
            out = (0, (pa[k][0] + pa[(k + 1) % n][0]) / 2, (pa[k][1] + pa[(k + 1) % n][1]) / 2 - zc)
            _quad(tris, PREFIX + ('trim' if k in trim else paint), a, b2, c, d, out)
    # the nose and the tail
    for x, pts, _ in (rings[0], rings[-1]):
        sx = 1 if x > 0 else -1
        ring = [(x, y, z) for y, z in pts]
        mid = (x, 0, sum(p[2] for p in ring) / len(ring))
        for k in range(len(ring)):
            _tri(tris, PREFIX + paint, mid, ring[k], ring[(k + 1) % len(ring)], (sx, 0, 0))
    return rings


def _glasshouse(tris, paint, b, rings):
    w = b['W'] / 2
    xw, xf, xr, xg = b['cab']
    zr = b['roof']
    top = b['top']
    ib, it = b['inset']
    wb, wt = w - ib, w - it
    zw, zg = _interp(top, xw), _interp(top, xg)
    bow = .03 if b['roof'] < 1.8 else .01
    xm = (xf + xr) / 2
    glass, roof = PREFIX + 'glass', PREFIX + paint
    for s in (-1, 1):
        B1, T1, Tm, T2, B2 = (xw, s * wb, zw), (xf, s * wt, zr), (xm, s * wt, zr + bow), (xr, s * wt, zr), (xg, s * wb, zg)
        out = (0, s, 0)
        for a, c in ((T1, Tm), (Tm, T2), (T2, B2)):
            _tri(tris, glass, B1, a, c, out)
        # the pillar between the side windows, a little proud of the glass
        px = xw + (xg - xw) * (.45 if b['roof'] < 1.8 else .3)
        zp = _interp(top, px)
        t_up = zr + bow * .5
        f_lo = (px - xg) / (xw - xg) if xw != xg else .5
        w_lo, w_up = wb, wt
        off = .006 * s
        _quad(tris, roof, (px + .06, s * w_lo + off, zp), (px - .06, s * w_lo + off, zp),
              (px - .06, s * w_up + off, t_up), (px + .06, s * w_up + off, t_up), out)
        del f_lo
    # windscreen, roof, rear glass
    _quad(tris, glass, (xw, -wb, zw), (xw, wb, zw), (xf, wt, zr), (xf, -wt, zr), (1, 0, .6))
    _quad(tris, roof, (xf, -wt, zr), (xf, wt, zr), (xm, wt, zr + bow), (xm, -wt, zr + bow), (0, 0, 1))
    _quad(tris, roof, (xm, -wt, zr + bow), (xm, wt, zr + bow), (xr, wt, zr), (xr, -wt, zr), (0, 0, 1))
    _quad(tris, glass, (xr, -wt, zr), (xr, wt, zr), (xg, wb, zg), (xg, -wb, zg), (-1, 0, .6))
    # mirrors by the windscreen's foot
    for s in (-1, 1):
        x0, x1 = xw - .02, xw - .16
        y0, y1 = s * (wb + .02), s * (w + .09)
        z0, z1 = zw + .04, zw + .16
        _box(tris, roof, x0, x1, y0, y1, z0, z1)


def _box(tris, material, x0, x1, y0, y1, z0, z1):
    xs, ys, zs = sorted((x0, x1)), sorted((y0, y1)), sorted((z0, z1))
    c = [(x, y, z) for x in xs for y in ys for z in zs]
    centre = ((xs[0] + xs[1]) / 2, (ys[0] + ys[1]) / 2, (zs[0] + zs[1]) / 2)
    faces = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
    for f in faces:
        pts = [c[i] for i in f]
        _quad(tris, material, *pts, _away(pts, centre))


def _wheels(tris, b):
    R, WB, w = b['R'], b['WB'], b['W'] / 2
    n = 10
    ring = [(math.cos(2 * math.pi * k / n + math.pi / n) * R, math.sin(2 * math.pi * k / n + math.pi / n) * R) for k in range(n)]
    for wx in (WB / 2, -WB / 2):
        for s in (-1, 1):
            # the tyre stands a centimetre proud of the body's side, its arch dark behind it
            yo, yi = s * (w + .012), s * (w - .20)
            pts = [(wx + x, z + R) for x, z in ring]
            for k in range(n):
                (xa, za), (xb, zb) = pts[k], pts[(k + 1) % n]
                _quad(tris, PREFIX + 'tyre', (xa, yo, za), (xb, yo, zb), (xb, yi, zb), (xa, yi, za),
                      ((xa + xb) / 2 - wx, 0, (za + zb) / 2 - R))
            # the rim on the outer face, the tyre's wall round it
            hub = (wx, yo + s * .004, R)
            for k in range(n):
                (xa, za), (xb, zb) = pts[k], pts[(k + 1) % n]
                ra = (wx + (xa - wx) * .64, yo + s * .004, R + (za - R) * .64)
                rb = (wx + (xb - wx) * .64, yo + s * .004, R + (zb - R) * .64)
                _tri(tris, PREFIX + 'rim', hub, ra, rb, (0, s, 0))
                _quad(tris, PREFIX + 'tyre', (xa, yo, za), (xb, yo, zb), rb, ra, (0, s, 0))
            # the dark arch on the body's side above the wheel
            ya = s * (w + .004)
            arch = [(wx + math.cos(math.pi * k / 6) * (R + .07), R + math.sin(math.pi * k / 6) * (R + .07)) for k in range(7)]
            for (xa, za), (xb, zb) in zip(arch, arch[1:]):
                _tri(tris, PREFIX + 'trim', (wx, ya, R), (xa, ya, za), (xb, ya, zb), (0, s, 0))


def _ends(tris, b, rings):
    """Lamps, grille, plates and bumpers on the nose and the tail."""
    for x, pts, _ in (rings[0], rings[-1]):
        s = 1 if x > 0 else -1
        we = max(y for y, _ in pts)
        zb = min(z for _, z in pts)
        zt = max(z for _, z in pts)
        xo = x + s * .006
        out = (s, 0, 0)

        def plate(material, y0, y1, z0, z1, dx=0.0):
            _quad(tris, material, (xo + s * dx, y0, z0), (xo + s * dx, y1, z0), (xo + s * dx, y1, z1), (xo + s * dx, y0, z1), out)

        bump0, bump1 = zb + .02, zb + .17
        plate(PREFIX + 'trim', -we + .02, we - .02, bump0, bump1, .02)
        lamp = PREFIX + ('lamp' if s > 0 else 'tail')
        lz0, lz1 = zt - .19, zt - .07
        for side in (-1, 1):
            plate(lamp, side * (we - .04), side * (we - .36), lz0, lz1)
        if s > 0:
            plate(PREFIX + 'trim', -(we - .42), we - .42, max(bump1 + .03, lz0 - .06), lz1 - .02)
        plate(PREFIX + 'plate', -.26, .26, bump0 + .02, bump0 + .13, .03)


def triangles(body, paint):
    b = dict(BODIES)[body]
    tris = []
    rings = _body(tris, paint, b)
    _glasshouse(tris, paint, b, rings)
    _wheels(tris, b)
    _ends(tris, b, rings)
    return tris


# --- Collada --------------------------------------------------------------------------------------
def _normal(a, b, c):
    u = [b[i] - a[i] for i in range(3)]
    v = [c[i] - a[i] for i in range(3)]
    n = (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0])
    length = sum(x * x for x in n) ** .5 or 1
    return tuple(x / length for x in n)


def _smooth(faces):
    """Per corner normals: the mean of the normals of the faces of one material at that point that
    meet this face's flatter than SMOOTH degrees."""
    limit = math.cos(math.radians(SMOOTH))
    normals = [_normal(*f) for f in faces]
    at = {}
    for k, f in enumerate(faces):
        for p in f:
            at.setdefault(tuple(round(c, 4) for c in p), []).append(k)
    out = []
    for k, f in enumerate(faces):
        n0 = normals[k]
        corners = []
        for p in f:
            acc = [0.0, 0.0, 0.0]
            for j in at[tuple(round(c, 4) for c in p)]:
                nj = normals[j]
                if sum(n0[i] * nj[i] for i in range(3)) >= limit:
                    for i in range(3):
                        acc[i] += nj[i]
            length = sum(x * x for x in acc) ** .5 or 1
            corners.append(tuple(x / length for x in acc))
        out.append(corners)
    return out


def car_dae(body, paint):
    tris = triangles(body, paint)
    by_material = {}
    for material, face in tris:
        by_material.setdefault(material, []).append(face)
    positions, normals, blocks = [], [], []
    for material, faces in by_material.items():
        idx = []
        for face, corners in zip(faces, _smooth(faces)):
            for p, n in zip(face, corners):
                positions.append(p)
                normals.append(n)
                idx += [len(positions) - 1, len(normals) - 1]
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
        out[PREFIX + name] = {'baseColorFactor': [*rgb, 1], 'roughnessFactor': .3, 'metallicFactor': .45,
                              'clearCoatFactor': .5, 'clearCoatRoughnessFactor': .15}
    for name, stage in SHARED.items():
        out[PREFIX + name] = stage
    return {m: {'name': m, 'mapTo': m, 'class': 'Material', 'version': 1.5, 'Stages': [stage, {}, {}, {}]}
            for m, stage in out.items()}


def level_files(level):
    files = {f'levels/{level}/art/flow/car_{body}_{name}.dae': car_dae(body, name)
             for body, _ in BODIES for name, _ in PAINTS}
    files[f'levels/{level}/art/flow/main.materials.json'] = json.dumps(materials(), indent=2)
    return files
