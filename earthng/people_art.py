"""Pedestrians (walkers.lua): low-poly people as static pose shapes, our own, no third-party art.

A walker is a TSStatic without collision moved by Lua; the walk is a flipbook of POSES static shapes
(the game instances static shapes, while animated ones cost ~30 us each a frame, docs/CROWDS_AND_PACKS.md).
One mesh per pose, ~300 triangles: tapered six-sided limbs posed by forward kinematics from a gait
table, an eight-sided torso, a low sphere head with a hair cap, box shoes. Clothes and skin take their
colour per instance (TSStatic instanceColor / instanceColor1 / instanceColor2) through the vehicle
palette masks, so 8 poses + 1 standing pose serve every outfit.

Forward is +x, up +z, the origin on the ground between the feet. In the planet as
levels/<level>/art/people/ (level_files); the physical body that takes a walker's place when a car
hits it is ped_body.py.

    .venv\\Scripts\\python.exe earthng\\people_art.py <out dir>
"""
import json
import math
import sys
from pathlib import Path

import flow_art  # (its Collada writer and normal smoothing)

POSES = 8
PREFIX = 'e2r_ped_'
MATERIALS = {
    'shirt': {'baseColorFactor': [1, 1, 1, 1], 'roughnessFactor': .85, 'instanceDiffuse': True,
              'colorPaletteMap': '/vehicles/common/nullcolormaskR.color.png'},
    'pants': {'baseColorFactor': [1, 1, 1, 1], 'roughnessFactor': .85, 'instanceDiffuse': True,
              'colorPaletteMap': '/vehicles/common/nullcolormaskG.color.png'},
    'skin': {'baseColorFactor': [1, 1, 1, 1], 'roughnessFactor': .7, 'instanceDiffuse': True,
             'colorPaletteMap': '/vehicles/common/nullcolormaskB.color.png'},
    'hair': {'baseColorFactor': [.06, .045, .03, 1], 'roughnessFactor': .8},
    'shoes': {'baseColorFactor': [.05, .05, .05, 1], 'roughnessFactor': .7},
}

# body, metres: hip height, thigh, shin, shoulder height, half widths, arm segments
HIP, THIGH, SHIN, SHOULDER = .93, .44, .45, 1.44
HIP_W, SHOULDER_W = .095, .19
UPPER, FORE = .29, .27


def gait(phase):
    """Hip flexion (forward +), knee flexion, shoulder swing, elbow flexion (degrees) of the left side,
    and the bob of the pelvis (m), at phase 0..1 of the stride. 0 is the left leg's mid swing: the thigh
    passes vertical while the knee is most bent, so the shin trails (no backward knee)."""
    a = 2 * math.pi * phase
    hip = 24 * math.sin(a)
    knee = 7 + 55 * max(0.0, math.cos(a)) ** 2
    shoulder = -20 * math.sin(a)
    elbow = 18 + 14 * max(0.0, -math.sin(a))
    bob = .025 * math.cos(2 * a)
    return hip, knee, shoulder, elbow, bob


def _limb(tris, material, a, b, r0, r1, sides=6, caps=True):
    """A tapered prism from point a (radius r0) to b (r1), its faces pointing out."""
    d = [b[i] - a[i] for i in range(3)]
    length = math.sqrt(sum(x * x for x in d)) or 1
    d = [x / length for x in d]
    helper = (0, 0, 1) if abs(d[2]) < .9 else (1, 0, 0)
    u = (d[1] * helper[2] - d[2] * helper[1], d[2] * helper[0] - d[0] * helper[2], d[0] * helper[1] - d[1] * helper[0])
    ul = math.sqrt(sum(x * x for x in u))
    u = [x / ul for x in u]
    v = (d[1] * u[2] - d[2] * u[1], d[2] * u[0] - d[0] * u[2], d[0] * u[1] - d[1] * u[0])
    ring = lambda c, r: [tuple(c[i] + r * (math.cos(2 * math.pi * k / sides) * u[i] + math.sin(2 * math.pi * k / sides) * v[i])
                               for i in range(3)) for k in range(sides)]
    ra, rb = ring(a, r0), ring(b, r1)
    centre = [(a[i] + b[i]) / 2 for i in range(3)]
    for k in range(sides):
        n = (k + 1) % sides
        quad = (ra[k], ra[n], rb[n], rb[k])
        flow_art._quad(tris, material, *quad, flow_art._away(quad, centre))
    if caps:
        for k in range(1, sides - 1):
            flow_art._tri(tris, material, ra[0], ra[k], ra[k + 1], [-x for x in d])
            flow_art._tri(tris, material, rb[0], rb[k], rb[k + 1], d)


def _ball(tris, material, c, rx, ry, rz, z_from=-1.0, rings=4, sides=8):
    """A low sphere (or its top part from z_from of -1..1), faces out."""
    lat = [z_from + (1 - z_from) * k / rings for k in range(rings + 1)]
    pt = lambda s, k: (c[0] + rx * math.sqrt(max(0, 1 - s * s)) * math.cos(2 * math.pi * k / sides),
                       c[1] + ry * math.sqrt(max(0, 1 - s * s)) * math.sin(2 * math.pi * k / sides), c[2] + rz * s)
    for j in range(rings):
        for k in range(sides):
            n = (k + 1) % sides
            quad = (pt(lat[j], k), pt(lat[j], n), pt(lat[j + 1], n), pt(lat[j + 1], k))
            out = flow_art._away(quad, c)
            if j == rings - 1 and lat[-1] >= 1:
                flow_art._tri(tris, material, quad[0], quad[1], quad[2], out)
            else:
                flow_art._quad(tris, material, *quad, out)


def _rot(deg, length, origin, down=True):
    """The end of a segment of `length` from origin, swung `deg` forward from hanging (or from up)."""
    r = math.radians(deg)
    s = -1 if down else 1
    return (origin[0] + length * math.sin(r), origin[1], origin[2] + s * length * math.cos(r))


def triangles(phase=None, parts=None):
    """A walking pose at phase 0..1, or the standing pose (None). With a dict `parts`, each body part's
    triangles also go to parts[name] (trunk, head, thigh_l, shin_l, foot_l, upper_l, fore_l, ... _r):
    the physical pedestrian (ped_body.py) gives each part its own flexbody."""
    tris = []

    def part(name):
        if parts is None:
            return tris
        return parts.setdefault(name, [])
    if phase is None:
        legs = {1: (2, 4), -1: (-1, 3)}
        arms = {1: (4, 12), -1: (-3, 14)}
        bob = 0
    else:
        legs, arms = {}, {}
        for side, ph in ((1, phase), (-1, (phase + .5) % 1)):
            hip, knee, shoulder, elbow, bob = gait(ph)
            legs[side] = (hip, knee)
            arms[side] = (shoulder, elbow)
        bob = gait(phase)[4]
    hz = HIP + bob
    for side in (1, -1):
        hip, knee = legs[side]
        h = (0, side * HIP_W, hz)
        k = _rot(hip, THIGH, h)
        f = _rot(hip - knee, SHIN, k)
        tag = 'l' if side == 1 else 'r'
        _limb(part('thigh_' + tag), 'pants', h, k, .075, .055)
        _limb(part('shin_' + tag), 'pants', k, f, .052, .040)
        # shoe: a box from the ankle forward along the ground direction of the foot
        fx, fz = f[0], max(f[2] - .03, 0.0)
        _limb(part('foot_' + tag), 'shoes', (fx - .05, f[1], fz + .035), (fx + .16, f[1], fz + .03), .045, .04, sides=4)
        shoulder, elbow = arms[side]
        s = (0, side * SHOULDER_W, SHOULDER + bob)
        e = _rot(shoulder, UPPER, s)
        w = _rot(shoulder + elbow, FORE, e)
        _limb(part('upper_' + tag), 'shirt', s, e, .052, .045)
        _limb(part('fore_' + tag), 'skin', e, w, .042, .034)
        _limb(part('fore_' + tag), 'skin', w, _rot(shoulder + elbow, .08, w), .035, .03, sides=4)
    # pelvis and torso (eight-sided, wider at the chest), neck, head, hair
    _limb(part('trunk'), 'pants', (0, 0, hz - .06), (0, 0, hz + .10), .15, .16, sides=8)
    _limb(part('trunk'), 'shirt', (0, 0, hz + .10), (0, 0, SHOULDER + bob + .03), .16, .20, sides=8)
    _limb(part('head'), 'skin', (0, 0, SHOULDER + bob + .03), (0, 0, SHOULDER + bob + .11), .05, .05)
    head = (.01, 0, SHOULDER + bob + .21)
    _ball(part('head'), 'skin', head, .10, .085, .115)
    _ball(part('head'), 'hair', (head[0] - .008, 0, head[2] + .008), .106, .091, .118, z_from=.25, rings=2)
    if parts is not None:
        tris = [t for name in parts for t in parts[name]]
    return tris


def pose_dae(phase):
    """Collada of one pose: flow_art's writer with this mesh."""
    tris = triangles(phase)
    saved = flow_art.triangles
    flow_art.triangles = lambda body, paint: tris
    try:
        text = flow_art.car_dae('sedan', 'white')
    finally:
        flow_art.triangles = saved
    return text.replace('name="car"', 'name="ped"').replace('id="car"', 'id="ped"'), len(tris)


def files():
    out, counts = {}, {}
    for k in range(POSES):
        text, n = pose_dae(k / POSES)
        out[f'ped_walk{k}.dae'] = text
        counts[k] = n
    out['ped_stand.dae'], counts['stand'] = pose_dae(None)
    mats = {PREFIX + m: {'name': PREFIX + m, 'mapTo': PREFIX + m, 'class': 'Material', 'version': 1.5,
                         'Stages': [stage, {}, {}, {}]} for m, stage in MATERIALS.items()}
    out['people.materials.json'] = json.dumps(mats, indent=2)
    # the shapes name their materials without the prefix: map them
    for name in list(out):
        if name.endswith('.dae'):
            text = out[name]
            for m in MATERIALS:
                text = text.replace(f'"{m}"', f'"{PREFIX}{m}"').replace(f'#{m}"', f'#{PREFIX}{m}"').replace(
                    f'id="{m}-fx"', f'id="{PREFIX}{m}-fx"').replace(f'#{m}-fx"', f'#{PREFIX}{m}-fx"')
            out[name] = text
    return out, counts


def level_files(level):
    """The poses and their materials for the planet ZIP (build_mod.py)."""
    out, _ = files()
    return {f'levels/{level}/art/people/{name}': text for name, text in out.items()}


if __name__ == '__main__':
    target = Path(sys.argv[1])
    target.mkdir(parents=True, exist_ok=True)
    out, counts = files()
    for name, text in out.items():
        (target / name).write_text(text, encoding='utf8')
    print('triangles per pose', counts)
