"""Pedestrians (walkers.lua): low-poly people as static pose shapes, our own, no third-party art.

A walker is a TSStatic without collision moved by Lua; the walk is a flipbook of POSES static shapes
(the game instances static shapes, while animated ones cost ~30 us each a frame, docs/CROWDS_AND_PACKS.md).
One mesh per pose, ~450 triangles: tapered limbs posed by forward kinematics from a gait table, a
waisted torso with collar and hem, a head with jaw and hair, mitts and box shoes. Clothes and skin
take their colour per instance (TSStatic instanceColor*) through the vehicle palette masks, so
8 poses + 1 standing pose serve every outfit. A flat blood_splat mesh is for pedhit hits.

Forward is +x, up +z, the origin on the ground between the feet. In the planet as
levels/<level>/art/people/ (level_files); the physical body that takes a walker's place when a car
hits it is ped_body.py.

    .venv\\Scripts\\python.exe earthng\\people_art.py <out dir>
"""
import io
import json
import math
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

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
    'blood': {'baseColorMap': 'blood_splat.png', 'roughnessFactor': .95, 'metallicFactor': 0,
              'diffuseMap': 'blood_splat.png', 'vertColor': False,
              'alphaMap': 'blood_splat.png', 'castShadows': False, 'translucent': True,
              'translucentBlendOp': 'Alpha', 'alphaRef': 40},
}

# body, metres: hip height, thigh, shin, shoulder height, half widths, arm segments
# (ped_body.py skeleton follows these; keep lengths stable)
HIP, THIGH, SHIN, SHOULDER = .93, .44, .45, 1.44
HIP_W, SHOULDER_W = .105, .20
UPPER, FORE = .29, .27


def gait(phase):
    """Hip flexion (forward +), knee flexion, shoulder swing, elbow flexion (degrees) of the left side,
    and the bob of the pelvis (m), at phase 0..1 of the stride. 0 is the left leg's mid swing: the thigh
    passes vertical while the knee is most bent, so the shin trails (no backward knee)."""
    a = 2 * math.pi * phase
    hip = 26 * math.sin(a)
    knee = 8 + 58 * max(0.0, math.cos(a)) ** 2
    shoulder = -22 * math.sin(a)
    elbow = 20 + 16 * max(0.0, -math.sin(a))
    bob = .028 * math.cos(2 * a)
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
    sz = SHOULDER + bob
    for side in (1, -1):
        hip, knee = legs[side]
        h = (0, side * HIP_W, hz)
        k = _rot(hip, THIGH, h)
        f = _rot(hip - knee, SHIN, k)
        tag = 'l' if side == 1 else 'r'
        # thighs thicker at the hip, shins taper; slight forward bias on the thigh
        _limb(part('thigh_' + tag), 'pants', h, k, .088, .058, sides=7)
        _limb(part('shin_' + tag), 'pants', k, f, .055, .042, sides=7)
        # shoe: sole + upper
        fx, fz = f[0], max(f[2] - .03, 0.0)
        toe = (fx + .17, f[1], fz + .025)
        heel = (fx - .06, f[1], fz + .03)
        _limb(part('foot_' + tag), 'shoes', heel, toe, .048, .042, sides=5)
        _limb(part('foot_' + tag), 'shoes', (fx - .02, f[1], fz + .01), (fx + .12, f[1], fz + .01), .05, .045, sides=4)
        shoulder, elbow = arms[side]
        # sloped shoulder: joint sits out and slightly down from the neck ring
        s = (.02, side * SHOULDER_W, sz - .02)
        e = _rot(shoulder, UPPER, s)
        w = _rot(shoulder + elbow, FORE, e)
        # deltoid bulge then sleeve
        _limb(part('upper_' + tag), 'shirt', (0, side * .12, sz), s, .06, .055, sides=6)
        _limb(part('upper_' + tag), 'shirt', s, e, .055, .046, sides=6)
        _limb(part('fore_' + tag), 'skin', e, w, .043, .035, sides=6)
        hand = _rot(shoulder + elbow, .09, w)
        _limb(part('fore_' + tag), 'skin', w, hand, .036, .032, sides=5)
        # mitt
        _limb(part('fore_' + tag), 'skin', hand, (hand[0] + .04, hand[1], hand[2] - .01), .032, .028, sides=4)
    # pelvis (wider hips), waist, chest (broader), collar, hem flare
    _limb(part('trunk'), 'pants', (0, 0, hz - .08), (0, 0, hz + .06), .155, .145, sides=8)
    _limb(part('trunk'), 'pants', (0, 0, hz + .06), (0, 0, hz + .14), .145, .13, sides=8)
    _limb(part('trunk'), 'shirt', (0, 0, hz + .12), (0, 0, hz + .38), .135, .155, sides=8)
    _limb(part('trunk'), 'shirt', (0, 0, hz + .38), (0, 0, sz + .02), .165, .20, sides=8)
    # collar
    _limb(part('trunk'), 'shirt', (0, 0, sz - .01), (0, 0, sz + .05), .11, .09, sides=8)
    # neck and head with jaw, ears, hair volume
    _limb(part('head'), 'skin', (0, 0, sz + .03), (0, 0, sz + .12), .045, .048, sides=6)
    head = (.02, 0, sz + .22)
    _ball(part('head'), 'skin', head, .095, .082, .11, rings=5, sides=10)
    # jaw / chin
    _limb(part('head'), 'skin', (head[0] + .02, 0, head[2] - .07), (head[0] + .05, 0, head[2] - .1), .055, .035, sides=6)
    # ears
    for side in (1, -1):
        _ball(part('head'), 'skin', (head[0], side * .09, head[2] - .01), .025, .018, .03, rings=2, sides=5)
    # hair: crown + fringe + back volume
    _ball(part('head'), 'hair', (head[0] - .01, 0, head[2] + .01), .102, .09, .12, z_from=.15, rings=3, sides=10)
    _limb(part('head'), 'hair', (head[0] - .02, 0, head[2] + .02), (head[0] - .08, 0, head[2] - .04), .09, .07, sides=6)
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


def blood_png(size=256):
    """Irregular translucent blood splat (RGBA PNG bytes)."""
    im = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(im)
    cx = cy = size // 2
    # layered blobs: dark core, mid, thin edges and droplets
    layers = [
        ((120, 8, 10, 210), size * .38, 7),
        ((90, 4, 8, 180), size * .28, 5),
        ((55, 2, 4, 230), size * .16, 4),
        ((140, 12, 14, 120), size * .12, 9),
    ]
    for colour, rad, n in layers:
        for k in range(n):
            a = 2 * math.pi * k / n + (k * .7)
            d = rad * (.15 + .55 * ((k * 37) % 10) / 10)
            x, y = cx + rad * .35 * math.cos(a) + d * .2, cy + rad * .3 * math.sin(a)
            r = rad * (.35 + .4 * ((k * 13) % 7) / 7)
            draw.ellipse([x - r, y - r, x + r, y + r], fill=colour)
    # droplets
    for k in range(14):
        a = 2 * math.pi * k / 14 + .4
        d = size * (.32 + .12 * (k % 3))
        x, y = cx + d * math.cos(a), cy + d * math.sin(a)
        r = 3 + (k % 5)
        draw.ellipse([x - r, y - r, x + r, y + r], fill=(100, 5, 8, 160))
    im = im.filter(ImageFilter.GaussianBlur(radius=1.2))
    buf = io.BytesIO()
    im.save(buf, format='PNG')
    return buf.getvalue()


def blood_dae():
    """A flat unit quad on the XY plane (z up), UV 0..1, material blood."""
    # corners of a 1x1 m quad centred on origin, slightly above z=0
    a, b, c, d = (-.5, -.5, 0), (.5, -.5, 0), (.5, .5, 0), (-.5, .5, 0)
    # two triangles, normal +z; UVs: a(0,0) b(1,0) c(1,1) d(0,1)
    pos = [a, b, c, a, c, d]
    uv = [(0, 0), (1, 0), (1, 1), (0, 0), (1, 1), (0, 1)]
    nrm = [(0, 0, 1)] * 6
    fmt = lambda rows: ' '.join(f'{x:.4f}' for row in rows for x in row)
    idx = ' '.join(str(i) for i in range(6) for _ in (0, 1))  # pos+uv shared index per corner via two inputs
    # simpler: interleaved indices for POSITION and TEXCOORD
    p_idx = []
    for i in range(6):
        p_idx += [i, i]
    return f'''<?xml version="1.0" encoding="utf-8"?>
<COLLADA xmlns="http://www.collada.org/2005/11/COLLADASchema" version="1.4.1">
  <asset><unit name="meter" meter="1"/><up_axis>Z_UP</up_axis></asset>
  <library_effects>
    <effect id="{PREFIX}blood-fx"><profile_COMMON><technique sid="common">
      <lambert><diffuse><texture texture="{PREFIX}blood-sampler" texcoord="UV"/></diffuse></lambert>
    </technique>
    <newparam sid="{PREFIX}blood-surface"><surface type="2D"><init_from>{PREFIX}blood-img</init_from></surface></newparam>
    <newparam sid="{PREFIX}blood-sampler"><sampler2D><source>{PREFIX}blood-surface</source></sampler2D></newparam>
    </profile_COMMON></effect>
  </library_effects>
  <library_images><image id="{PREFIX}blood-img" name="{PREFIX}blood-img">
    <init_from>blood_splat.png</init_from></image></library_images>
  <library_materials>
    <material id="{PREFIX}blood" name="{PREFIX}blood"><instance_effect url="#{PREFIX}blood-fx"/></material>
  </library_materials>
  <library_geometries>
    <geometry id="splat-g" name="splat"><mesh>
      <source id="splat-pos"><float_array id="splat-pa" count="18">{fmt(pos)}</float_array>
        <technique_common><accessor source="#splat-pa" count="6" stride="3">
          <param name="X" type="float"/><param name="Y" type="float"/><param name="Z" type="float"/>
        </accessor></technique_common></source>
      <source id="splat-nrm"><float_array id="splat-na" count="18">{fmt(nrm)}</float_array>
        <technique_common><accessor source="#splat-na" count="6" stride="3">
          <param name="X" type="float"/><param name="Y" type="float"/><param name="Z" type="float"/>
        </accessor></technique_common></source>
      <source id="splat-uv"><float_array id="splat-ua" count="12">{fmt(uv)}</float_array>
        <technique_common><accessor source="#splat-ua" count="6" stride="2">
          <param name="S" type="float"/><param name="T" type="float"/>
        </accessor></technique_common></source>
      <vertices id="splat-vtx"><input semantic="POSITION" source="#splat-pos"/></vertices>
      <triangles material="{PREFIX}blood" count="2">
        <input semantic="VERTEX" source="#splat-vtx" offset="0"/>
        <input semantic="NORMAL" source="#splat-nrm" offset="1"/>
        <input semantic="TEXCOORD" source="#splat-uv" offset="0" set="0"/>
        <p>0 0 1 1 2 2 3 3 4 4 5 5</p>
      </triangles>
    </mesh></geometry>
  </library_geometries>
  <library_visual_scenes><visual_scene id="Scene">
    <node id="splat" name="splat">
      <instance_geometry url="#splat-g"><bind_material><technique_common>
        <instance_material symbol="{PREFIX}blood" target="#{PREFIX}blood"/>
      </technique_common></bind_material></instance_geometry>
    </node>
  </visual_scene></library_visual_scenes>
  <scene><instance_visual_scene url="#Scene"/></scene>
</COLLADA>
'''


def files():
    out, counts = {}, {}
    for k in range(POSES):
        text, n = pose_dae(k / POSES)
        out[f'ped_walk{k}.dae'] = text
        counts[k] = n
    out['ped_stand.dae'], counts['stand'] = pose_dae(None)
    out['blood_splat.dae'] = blood_dae()
    out['blood_splat.png'] = blood_png()
    mats = {}
    for m, stage in MATERIALS.items():
        mats[PREFIX + m] = {'name': PREFIX + m, 'mapTo': PREFIX + m, 'class': 'Material', 'version': 1.5,
                            'Stages': [dict(stage), {}, {}, {}]}
    # blood texture path inside the people art folder
    blood_stage = mats[PREFIX + 'blood']['Stages'][0]
    blood_stage['baseColorMap'] = f'/levels/e2r_world/art/people/blood_splat.png'
    blood_stage.pop('diffuseMap', None)
    blood_stage.pop('alphaMap', None)
    out['people.materials.json'] = json.dumps(mats, indent=2)
    # the shapes name their materials without the prefix: map them
    for name in list(out):
        if name.endswith('.dae') and name != 'blood_splat.dae':
            text = out[name]
            for m in MATERIALS:
                if m == 'blood':
                    continue
                text = text.replace(f'"{m}"', f'"{PREFIX}{m}"').replace(f'#{m}"', f'#{PREFIX}{m}"').replace(
                    f'id="{m}-fx"', f'id="{PREFIX}{m}-fx"').replace(f'#{m}-fx"', f'#{PREFIX}{m}-fx"')
            out[name] = text
    return out, counts


def level_files(level):
    """The poses and their materials for the planet ZIP (build_mod.py)."""
    out, _ = files()
    # blood material path must match the level
    mats = json.loads(out['people.materials.json'])
    stage = mats[PREFIX + 'blood']['Stages'][0]
    stage['baseColorMap'] = f'/levels/{level}/art/people/blood_splat.png'
    out['people.materials.json'] = json.dumps(mats, indent=2)
    return {f'levels/{level}/art/people/{name}': text for name, text in out.items()}


if __name__ == '__main__':
    target = Path(sys.argv[1])
    target.mkdir(parents=True, exist_ok=True)
    out, counts = files()
    for name, text in out.items():
        path = target / name
        if isinstance(text, (bytes, bytearray)):
            path.write_bytes(text)
        else:
            path.write_text(text, encoding='utf8')
    print('triangles per pose', counts)
