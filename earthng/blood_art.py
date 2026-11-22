"""Blood stains of pedestrian hits (world.lua BLOOD), drawn here: no third-party art, no paid call.

(An image model was asked for them once, 22.11: the service declines the subject. These are our
own, from how such stains form.)

    .venv\\Scripts\\python.exe earthng\\blood_art.py --sheet out.jpg     (a look at them)

Each stain is a thickness of blood over a square, built at twice its size and reduced:

    impact   where a body was struck: a blot of merged lobes, spines round it, satellite drops
             that are smaller and longer the further out they flew, their tails pointing away
    spray    thrown one way (the picture's +x): a small blot, then stretched drops in a widening
             fan, thinning out
    pool     what gathers under a body at rest: one smooth lobed outline, thick to its edge
    smear    a body dragged (+x): streaks side by side that break up and feather out
    drops    fallen straight down: round drops of many sizes, some with a crown of specks
    run      a splash with thin runs from it (+x: down a wall, back along a bonnet), a bead at
             the end of each

The outlines are not circles: every shape is drawn on coordinates bent by smooth noise. Thick blood
is nearly black-red and covers; a thin edge is brighter and lets the ground through. files() gives

    blood_<name>.png       a stain with its alpha: the engine's dynamic decals take these for the
                           stains on the ground (blended into the road, lit and shaded as it is)
    blood.color.png, blood_o.data.png    all of them on one atlas, colour and opacity, for the
                           cut-out quads on a wall and on a car's skin (people_art's blood material)
    blood_<name>.dae       the quad of each
    blood.json             what world.lua reads: the stains by kind, their pictures and how much
                           of its square each one fills
"""
import argparse
import io
import json
import math
from pathlib import Path

import numpy as np
from PIL import Image

VERSION = '1'
SIZE = 512             # px of a stain's own picture
CELL = 256             # px of a stain in the atlas
ATLAS = (4, 2)         # stains across and down
SS = 2                 # drawn this many times larger, then reduced
THIN, THICK = np.array([.58, .045, .036]), np.array([.24, .010, .014])   # sRGB of a film and of a depth of blood

# name: (kind, seed)
STAINS = {'impact_a': ('impact', 11), 'impact_b': ('impact', 23), 'spray_a': ('spray', 31), 'spray_b': ('spray', 47),
          'pool_a': ('pool', 53), 'smear_a': ('smear', 61), 'drops_a': ('drops', 71), 'run_a': ('run', 83)}


class Canvas:
    """Coverage and thickness of blood over a square of S px, with bent coordinates."""

    def __init__(self, seed, size=SIZE * SS):
        self.S = S = size
        self.rnd = np.random.RandomState(seed)
        y, x = np.mgrid[0:S, 0:S].astype(np.float32)
        # the bend: a slow one that makes a circle a lobed outline, a quick one that frays its edge
        self.X = x + self.noise(6) * S * .034 + self.noise(28) * S * .006
        self.Y = y + self.noise(6) * S * .034 + self.noise(28) * S * .006
        self.cover = np.zeros((S, S), dtype=np.float32)
        self.thick = np.zeros((S, S), dtype=np.float32)

    def noise(self, cells, octaves=3):
        """Smooth noise about 0 (roughly -.5 .. .5), `cells` across at its slowest."""
        total, amp = np.zeros((self.S, self.S), dtype=np.float32), 1.
        for o in range(octaves):
            n = cells * 2 ** o + 1
            grid = Image.fromarray((self.rnd.rand(n, n) * 255).astype(np.uint8))
            total += amp * (np.asarray(grid.resize((self.S, self.S), Image.BICUBIC), dtype=np.float32) / 255 - .5)
            amp *= .5
        return total

    def window(self, cx, cy, r):
        S = self.S
        x0, x1 = int(max(0, cx - r - S * .04)), int(min(S, cx + r + S * .04))
        y0, y1 = int(max(0, cy - r - S * .04)), int(min(S, cy + r + S * .04))
        return (slice(y0, y1), slice(x0, x1)) if x0 < x1 and y0 < y1 else None

    def drop(self, cx, cy, r, angle=0., stretch=1., depth=1.):
        """An ellipse of blood, `stretch` times longer along `angle`, domed: thick in the middle."""
        w = self.window(cx, cy, r * stretch)
        if not w:
            return
        dx, dy = self.X[w] - cx, self.Y[w] - cy
        c, s = math.cos(angle), math.sin(angle)
        e = ((dx * c + dy * s) / (r * stretch)) ** 2 + ((-dx * s + dy * c) / r) ** 2
        edge = max(1.5 / r, .06)          # an edge a pixel and a half wide, whatever the size
        self.cover[w] = np.maximum(self.cover[w], np.clip((1 - e) / edge, 0, 1))
        self.thick[w] = np.maximum(self.thick[w], np.clip(1 - e, 0, 1) ** .7 * depth * min(1, r / (self.S * .012)))

    def tail(self, cx, cy, r, angle, length, depth=.8):
        """A drop that slid: a line of shrinking drops from (cx, cy) along `angle`."""
        steps = max(3, int(length / max(r * .6, 1)))
        for k in range(steps):
            t = k / steps
            self.drop(cx + math.cos(angle) * length * t, cy + math.sin(angle) * length * t, max(r * (1 - t) ** 1.4, .8),
                      depth=depth * (1 - .5 * t))

    def blot(self, cx, cy, radius, lobes, depth=1.):
        """Merged lobes: Gaussians summed and cut at a level, so they flow into one outline."""
        S = self.S
        field = np.zeros((S, S), dtype=np.float32)
        for _ in range(lobes):
            a, d = self.rnd.uniform(0, 2 * math.pi), abs(self.rnd.normal(0, radius * .95))
            sx = radius * self.rnd.uniform(.2, .55)
            px, py = cx + d * math.cos(a), cy + d * math.sin(a)
            w = self.window(px, py, sx * 3)
            if w:
                field[w] += np.exp(-((self.X[w] - px) ** 2 + (self.Y[w] - py) ** 2) / (2 * sx * sx))
        self.cover = np.maximum(self.cover, np.clip((field - .5) / .06, 0, 1))
        self.thick = np.maximum(self.thick, np.clip((field - .5) / 2.2, 0, 1) ** .8 * depth)

    def picture(self, size=SIZE):
        """RGBA: thin blood bright and half clear, thick blood dark and covering; mottled a little."""
        t = np.clip(self.thick, 0, 1)[..., None]
        mottle = 1 + self.noise(40, 2)[..., None] * .22
        rgb = np.clip((THIN * (1 - t ** .7) + THICK * t ** .7) * mottle, 0, 1)
        alpha = self.cover * (.55 + .45 * np.clip(self.thick * 2.2, 0, 1))
        out = np.concatenate([rgb, alpha[..., None]], -1)
        return Image.fromarray((out * 255 + .5).astype(np.uint8), 'RGBA').resize((size, size), Image.LANCZOS)


def impact(c):
    S, r = c.S, c.rnd
    mid = S / 2
    c.blot(mid, mid, S * .085, 30)
    # spines: thin runs straight out of the blot
    for _ in range(r.randint(22, 34)):
        a = r.uniform(0, 2 * math.pi)
        d = S * r.uniform(.07, .12)
        c.tail(mid + d * math.cos(a), mid + d * math.sin(a), S * r.uniform(.006, .013), a, S * r.uniform(.04, .16))
    # satellite drops: more of them near, smaller and longer further out, most to one side
    side = r.uniform(0, 2 * math.pi)
    for _ in range(r.randint(110, 150)):
        a = side + r.normal(0, 1.0) if r.rand() < .55 else r.uniform(0, 2 * math.pi)
        f = r.uniform(0, 1) ** 1.6
        d = S * (.14 + .33 * f)
        rad = S * r.uniform(.0035, .012) * (1.25 - f)
        x, y = mid + d * math.cos(a), mid + d * math.sin(a)
        c.drop(x, y, rad, a, 1.2 + 2.6 * f)
        if f > .35 and r.rand() < .5:
            c.tail(x, y, rad * .6, a, rad * r.uniform(3, 7), .5)


def spray(c):
    S, r = c.S, c.rnd
    mid = S / 2
    c.blot(S * .15, mid, S * .055, 9)
    # a ragged streak out of the blot
    y = mid
    for k in range(26):
        t = k / 25
        y += r.normal(0, S * .004)
        c.drop(S * (.19 + .2 * t), y, S * (.03 * (1 - t) ** 1.3 + .006), 0, 1.8, .9)
    for _ in range(r.randint(150, 190)):
        t = r.uniform(.1, 1) ** .75
        x = S * (.17 + .78 * t)
        dy = r.normal(0, 1) * S * (.02 + .13 * t)
        a = math.atan2(dy, x - S * .15)
        rad = S * (.013 * (1 - t) + .0032) * r.uniform(.5, 1.4)
        if abs(dy) < S * .44:
            c.drop(x, mid + dy, rad, a, 1.6 + 3.2 * t)
            if r.rand() < .4:
                c.tail(x, mid + dy, rad * .55, a, rad * r.uniform(3, 8), .5)


def pool(c):
    S, r = c.S, c.rnd
    mid = S / 2
    dx, dy = c.X - mid, c.Y - mid
    # an outline of slow lobes round the middle, a little longer one way
    a = r.uniform(0, math.pi)
    u, v = dx * math.cos(a) + dy * math.sin(a), -dx * math.sin(a) + dy * math.cos(a)
    f = 1 - np.sqrt((u / (S * .40)) ** 2 + (v / (S * .33)) ** 2) + c.noise(3, 2) * .42
    c.cover = np.maximum(c.cover, np.clip(f / .025, 0, 1))
    c.thick = np.maximum(c.thick, np.clip(f * 2.4, 0, 1) ** .7)
    for _ in range(r.randint(4, 7)):
        t = r.uniform(0, 2 * math.pi)
        d = S * r.uniform(.4, .46)
        c.drop(mid + d * math.cos(t), mid + d * math.sin(t), S * r.uniform(.006, .016))


def smear(c):
    S, r = c.S, c.rnd
    y, x = np.mgrid[0:S, 0:S].astype(np.float32) / S
    yb = y + c.noise(4, 2) * .05           # the whole drag wavers a little
    # how wide it is along its way, and how heavy: full at the left, feathering out to the right
    half = .15 * (1 - .45 * x) + .02
    across = np.clip(1 - np.abs(yb - .5) / half, 0, 1)
    along = np.clip((x - .04) / .06, 0, 1) * np.clip((.98 - x) / .35, 0, 1) ** .7
    # streaks: noise stretched along the drag, cut harder the further it goes
    rows = Image.fromarray((r.rand(96, 5) * 255).astype(np.uint8)).resize((S, S), Image.BICUBIC)
    streak = np.asarray(rows, dtype=np.float32) / 255 + c.noise(30, 2) * .25
    cut = .25 + .5 * x
    body = np.clip((streak - cut) / .12, 0, 1) * np.clip(across * 2.2, 0, 1) * along
    c.cover = np.maximum(c.cover, np.clip(body * 1.6, 0, 1))
    c.thick = np.maximum(c.thick, np.clip(body * (1.1 - x) * across, 0, 1) * .85)
    c.blot(S * .1, S * .5, S * .06, 8, .9)
    for _ in range(26):
        c.drop(S * r.uniform(.1, .95), S * (.5 + r.normal(0, .12)), S * r.uniform(.003, .009), 0, r.uniform(1.5, 4))


def drops(c):
    S, r = c.S, c.rnd
    for _ in range(r.randint(17, 24)):
        x, y = S * r.uniform(.07, .93), S * r.uniform(.07, .93)
        rad = S * min(.05, math.exp(r.normal(-4.4, .6)))
        c.drop(x, y, rad)
        if r.rand() < .45:
            for _ in range(r.randint(4, 11)):
                a, d = r.uniform(0, 2 * math.pi), rad * r.uniform(1.3, 2.4)
                c.drop(x + d * math.cos(a), y + d * math.sin(a), max(rad * r.uniform(.06, .16), 1), a, r.uniform(1, 2.5))


def run(c):
    S, r = c.S, c.rnd
    c.blot(S * .2, S * .5, S * .085, 12)
    for _ in range(40):
        a, d = r.uniform(0, 2 * math.pi), S * r.uniform(.1, .2)
        c.drop(S * .2 + d * math.cos(a), S * .5 + d * math.sin(a), S * r.uniform(.003, .01), a, r.uniform(1, 2.5))
    for k in range(r.randint(5, 7)):
        y = S * (.5 + (k - 2.5) * .045 + r.normal(0, .012))
        x, width, length = S * .22, S * r.uniform(.006, .011), S * r.uniform(.2, .68)
        end = x + length
        while x < end:
            y += r.normal(0, S * .0016)
            c.drop(x, y, width * (1 - .35 * (x - S * .22) / length), 0, 1.4, .75)
            x += width * .7
        c.drop(end, y, width * r.uniform(1.5, 2.2), 0, 1.25)


KINDS = {'impact': impact, 'spray': spray, 'pool': pool, 'smear': smear, 'drops': drops, 'run': run}


def stain(name):
    """A stain's picture (RGBA, SIZE px) and how much of the square it fills along x and y."""
    kind, seed = STAINS[name]
    canvas = Canvas(seed)
    KINDS[kind](canvas)
    picture = canvas.picture()
    a = np.asarray(picture.getchannel('A'))
    ys, xs = np.nonzero(a > 40)
    box = ((xs.max() - xs.min() + 1) / SIZE, (ys.max() - ys.min() + 1) / SIZE) if len(xs) else (1, 1)
    return picture, box


def quad_dae(uv, material='e2r_ped_blood'):
    """A flat unit quad on the XY plane (z up), +x the picture's +x, its UV a square of the atlas."""
    u0, u1, v0, v1 = uv
    a, b, c, d = (-.5, -.5, 0), (.5, -.5, 0), (.5, .5, 0), (-.5, .5, 0)
    pos = [a, b, c, a, c, d]
    tex = [(u0, v0), (u1, v0), (u1, v1), (u0, v0), (u1, v1), (u0, v1)]
    fmt = lambda rows: ' '.join(f'{x:.5f}' for row in rows for x in row)
    return f'''<?xml version="1.0" encoding="utf-8"?>
<COLLADA xmlns="http://www.collada.org/2005/11/COLLADASchema" version="1.4.1">
  <asset><unit name="meter" meter="1"/><up_axis>Z_UP</up_axis></asset>
  <library_effects><effect id="{material}-fx"><profile_COMMON><technique sid="common">
    <lambert><diffuse><color>1 1 1 1</color></diffuse></lambert></technique></profile_COMMON></effect></library_effects>
  <library_materials><material id="{material}" name="{material}"><instance_effect url="#{material}-fx"/></material></library_materials>
  <library_geometries><geometry id="stain-g" name="stain"><mesh>
    <source id="stain-pos"><float_array id="stain-pa" count="18">{fmt(pos)}</float_array>
      <technique_common><accessor source="#stain-pa" count="6" stride="3">
        <param name="X" type="float"/><param name="Y" type="float"/><param name="Z" type="float"/></accessor></technique_common></source>
    <source id="stain-nrm"><float_array id="stain-na" count="18">{fmt([(0, 0, 1)] * 6)}</float_array>
      <technique_common><accessor source="#stain-na" count="6" stride="3">
        <param name="X" type="float"/><param name="Y" type="float"/><param name="Z" type="float"/></accessor></technique_common></source>
    <source id="stain-uv"><float_array id="stain-ua" count="12">{fmt(tex)}</float_array>
      <technique_common><accessor source="#stain-ua" count="6" stride="2">
        <param name="S" type="float"/><param name="T" type="float"/></accessor></technique_common></source>
    <vertices id="stain-vtx"><input semantic="POSITION" source="#stain-pos"/></vertices>
    <triangles material="{material}" count="2">
      <input semantic="VERTEX" source="#stain-vtx" offset="0"/>
      <input semantic="NORMAL" source="#stain-nrm" offset="1"/>
      <input semantic="TEXCOORD" source="#stain-uv" offset="0" set="0"/>
      <p>0 0 1 1 2 2 3 3 4 4 5 5</p>
    </triangles></mesh></geometry></library_geometries>
  <library_visual_scenes><visual_scene id="Scene"><node id="stain" name="stain">
    <instance_geometry url="#stain-g"><bind_material><technique_common>
      <instance_material symbol="{material}" target="#{material}"/></technique_common></bind_material></instance_geometry>
  </node></visual_scene></library_visual_scenes>
  <scene><instance_visual_scene url="#Scene"/></scene>
</COLLADA>
'''


_FILES = {}


def files(level='e2r_world'):
    """{name: bytes or text} of the people art folder (made once a run: the stains take a few seconds)."""
    if level in _FILES:
        return _FILES[level]
    root = f'/levels/{level}/art/people/'
    cols, rows = ATLAS
    colour = Image.new('RGB', (cols * CELL, rows * CELL), tuple(int(v * 255) for v in THICK))
    opacity = Image.new('L', (cols * CELL, rows * CELL), 0)
    out, listed = {}, []

    def png(image):
        buf = io.BytesIO()
        image.save(buf, format='PNG')
        return buf.getvalue()
    for k, name in enumerate(STAINS):
        picture, box = stain(name)
        out[f'blood_{name}.png'] = png(picture)
        cell = picture.resize((CELL, CELL), Image.LANCZOS)
        x, y = k % cols * CELL, k // cols * CELL
        # the colour without its alpha, blood under the clear texels too (no pale fringe at a cut edge)
        flat = Image.new('RGB', cell.size, tuple(int(v * 255) for v in THIN * .7 + THICK * .3))
        flat.paste(cell.convert('RGB'), (0, 0), cell.getchannel('A').point(lambda v: 255 if v > 24 else 0))
        colour.paste(flat, (x, y))
        opacity.paste(cell.getchannel('A'), (x, y))
        # (v up, as a Collada has it)
        uv = [k % cols / cols, (k % cols + 1) / cols, 1 - (k // cols + 1) / rows, 1 - (k // cols) / rows]
        out[f'blood_{name}.dae'] = quad_dae(uv)
        listed.append({'name': name, 'kind': STAINS[name][0], 'texture': root + f'blood_{name}.png',
                       'shape': f'blood_{name}', 'box': [round(float(v), 3) for v in box]})
    out['blood.color.png'], out['blood_o.data.png'] = png(colour), png(opacity)
    out['blood.json'] = json.dumps({'version': VERSION, 'stains': listed})
    _FILES[level] = out
    return out


def level_files(level):
    """The stains for the planet ZIP (build_mod.py), after people_art's: the atlas takes the place
    of its drawn one under the same names."""
    return {f'levels/{level}/art/people/{name}': data for name, data in files(level).items()}


def sheet(path):
    """Every stain over asphalt grey and over a car's paint, and the atlas as the quads cut it."""
    out = files()
    tiles = []
    for name in STAINS:
        im = Image.open(io.BytesIO(out[f'blood_{name}.png']))
        for back in ((96, 96, 100), (40, 62, 150)):
            tile = Image.new('RGB', im.size, back)
            tile.paste(im, (0, 0), im)
            tiles.append(tile.resize((320, 320), Image.LANCZOS))
    colour = Image.open(io.BytesIO(out['blood.color.png']))
    opacity = Image.open(io.BytesIO(out['blood_o.data.png']))
    cut = Image.new('RGB', colour.size, (200, 200, 205))
    cut.paste(colour, (0, 0), opacity.point(lambda v: 255 if v >= 64 else 0))
    cols = 8
    rows = (len(tiles) + cols - 1) // cols
    canvas = Image.new('RGB', (cols * 320, rows * 320 + cut.height), 'black')
    for k, tile in enumerate(tiles):
        canvas.paste(tile, (k % cols * 320, k // cols * 320))
    canvas.paste(cut, (0, rows * 320))
    canvas.save(path, quality=90)


def main():
    p = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    p.add_argument('--sheet', type=Path, help='a picture of every stain')
    p.add_argument('--out', type=Path, help='write the files into this folder')
    a = p.parse_args()
    if a.sheet:
        sheet(a.sheet)
    if a.out:
        a.out.mkdir(parents=True, exist_ok=True)
        for name, data in files().items():
            (a.out / name).write_bytes(data if isinstance(data, bytes) else data.encode('utf8'))


if __name__ == '__main__':
    main()
