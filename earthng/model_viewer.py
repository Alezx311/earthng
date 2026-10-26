"""A standalone 3D page of what generator.lua builds at a place, checked against real LiDAR heights.

  python earthng/model_viewer.py --pack out/country/earthng_estonia.zip --region e0240-n590 \\
      --lat 59.3573 --lon 24.8915 --radius 300 --lidar out/world/cache/est/dem_10m_geotiff --out check.html [--far]

Checking a map by driving it does not scale. This builds the tiles round a place with generator.lua
(road_quality's LuaJIT runtime, every mesh: roads, ground, buildings, rails, fences, cars) and writes
one HTML file. Open it in a browser (it loads three.js from a CDN): orbit with the mouse, switch
layers, click to measure. A click shows the model's height, the LiDAR terrain's height under it and
the difference; two clicks give the distance and the slope. "Colour by deviation" paints the ground
and the roads by (model - LiDAR terrain): green within 0.5 m, warm over, cool under (a bridge deck is
high over the terrain by design). The LiDAR terrain can be shown as a surface of its own. Heights are
real metres: the pack's +20 m datum lift is removed. URL flags open the page in a state:
#top, #dev, #dtm, #hide:buildings+cars, #cam:east+north+back+up+heading (look at that point, in metres from
the place, from `back` m behind it and `up` m over the terrain, heading in degrees from north).

--lidar: a Land Board terrain GeoTIFF (EPSG:3301, metres), or a folder of them; the finest one that
covers the place is used. Without it the page shows the model alone.
"""
import argparse
import base64
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import road_audit as audit  # noqa: E402
import road_quality as rq  # noqa: E402

LIFT = 20.0          # m: the pack's datum lift over real metres
# (substring of the material after e2rf_, rgb), the first match wins
PALETTE = [
    ('mark', (235, 235, 230)), ('road_major', (72, 72, 76)), ('road_worn', (100, 100, 100)),
    ('road_gravel', (150, 132, 100)), ('road_dirt', (140, 115, 80)), ('road_broken', (110, 105, 95)),
    ('road_track', (135, 115, 85)), ('road', (88, 88, 92)),
    ('sidewalk', (165, 165, 160)), ('curb', (190, 190, 185)), ('footway_asphalt', (110, 110, 112)),
    ('footway', (165, 145, 110)), ('trodden', (150, 130, 95)), ('paved', (150, 150, 146)),
    ('clad_metal', (225, 228, 235)), ('parapet', (176, 172, 164)), ('deck', (160, 156, 148)),
    ('pier', (150, 146, 140)), ('abutment', (150, 146, 140)), ('concrete', (165, 160, 152)),
    ('fence', (120, 125, 118)), ('edge_dirt', (138, 122, 88)), ('bare_ground', (138, 122, 88)),
    ('edge_grass', (105, 140, 66)), ('ground', (98, 142, 62)), ('meadow', (110, 150, 66)),
    ('park', (90, 140, 60)), ('grass', (98, 142, 62)), ('heath', (125, 135, 70)), ('scrub', (85, 120, 55)),
    ('forest', (62, 102, 48)), ('wood', (62, 102, 48)), ('farmland', (150, 150, 80)),
    ('water', (64, 104, 150)), ('wetland', (90, 120, 90)), ('sand', (200, 190, 150)), ('beach', (200, 190, 150)),
    ('scree', (150, 145, 135)), ('rock', (140, 135, 128)),
    ('roof', (125, 85, 72)), ('win', (95, 115, 135)), ('door', (100, 80, 60)), ('wall', (205, 190, 165)),
    ('gable', (205, 190, 165)), ('plinth', (150, 140, 130)), ('chimney', (140, 90, 80)), ('car', (175, 45, 45)),
    ('hw_', (120, 100, 80)), ('rail', (120, 110, 100)), ('sleeper', (110, 95, 80)), ('ballast', (130, 125, 120)),
]
GROUPS = [          # (layer, test on the material name after e2rf_), the first match wins
    ('road', lambda m: m.startswith('road')),
    ('marks', lambda m: m.startswith('mark')),
    ('sidewalk', lambda m: m in ('sidewalk', 'curb', 'paved', 'footway', 'footway_asphalt', 'trodden')),
    ('rails', lambda m: m in ('clad_metal', 'clad_tin')),
    ('fences', lambda m: m.startswith('fence')),
    ('buildings', lambda m: m.startswith(('wall', 'roof', 'win', 'door', 'gable', 'plinth', 'chimney', 'parapet', 'hw_'))),
    ('cars', lambda m: m == 'car'),
    ('ground', lambda m: True),
]
DEVIATION = ('road', 'ground')      # the layers the deviation ramp applies to


def colour(material):
    name = material.removeprefix('e2rf_')
    for key, rgb in PALETTE:
        if key in name:
            return np.array(rgb, dtype=float)
    return np.array((255, 0, 255), dtype=float)


def group_of(material):
    name = material.removeprefix('e2rf_')
    return next(g for g, test in GROUPS if test(name))


def find_sheet(lidar, e, n):
    """The finest LiDAR terrain raster under (e, n) in L-EST97: the file itself, or the best of a folder's."""
    if lidar is None:
        return None
    import rasterio
    lidar = Path(lidar)
    best = None
    for path in [lidar] if lidar.is_file() else sorted(lidar.glob('*.tif')):
        with rasterio.open(path) as src:
            b = src.bounds
            if b.left <= e < b.right and b.bottom <= n < b.top and (best is None or src.res[0] < best[0]):
                best = (src.res[0], path)
    return best and best[1]


def sample_raster(path, e, n):
    """Bilinear heights of a GeoTIFF at L-EST97 points (NaN outside it or on no data)."""
    import rasterio
    from rasterio.windows import Window
    e, n = np.asarray(e, float), np.asarray(n, float)
    with rasterio.open(path) as src:
        pad = 3
        c0 = int(max(0, math.floor((e.min() - src.bounds.left) / src.res[0]) - pad))
        c1 = int(min(src.width, math.ceil((e.max() - src.bounds.left) / src.res[0]) + pad))
        r0 = int(max(0, math.floor((src.bounds.top - n.max()) / src.res[1]) - pad))
        r1 = int(min(src.height, math.ceil((src.bounds.top - n.min()) / src.res[1]) + pad))
        if c1 <= c0 or r1 <= r0:
            return np.full(e.shape, np.nan)
        data = src.read(1, window=Window(c0, r0, c1 - c0, r1 - r0)).astype(float)
        if src.nodata is not None:
            data[data == src.nodata] = np.nan
        fx = (e - src.bounds.left) / src.res[0] - .5 - c0
        fy = (src.bounds.top - n) / src.res[1] - .5 - r0
    ix, iy = np.floor(fx).astype(int), np.floor(fy).astype(int)
    ok = (ix >= 0) & (iy >= 0) & (ix + 1 < data.shape[1]) & (iy + 1 < data.shape[0])
    ix, iy = np.clip(ix, 0, data.shape[1] - 2), np.clip(iy, 0, data.shape[0] - 2)
    u, v = fx - ix, fy - iy
    z = (data[iy, ix] * (1 - u) + data[iy, ix + 1] * u) * (1 - v) + (data[iy + 1, ix] * (1 - u) + data[iy + 1, ix + 1] * u) * v
    return np.where(ok, z, np.nan)


def b64(a, dtype=np.float32):
    return base64.b64encode(np.ascontiguousarray(a, dtype=dtype).tobytes()).decode('ascii')


def tiles(path, region, generator, far, x0, y0, radius):
    """{material: (n, 3, 3) triangles} of every tile within radius of (x0, y0), meshes of every kind."""
    pack, lua, mods, build, data, slots, cover = audit._runtime(str(path), region, generator and str(generator))
    size = pack.size
    tune = lua.table_from({'all': 1, **({'far': 1} if far else {})})
    mats = defaultdict(list)
    for i in range(math.floor((x0 - radius) / size), math.floor((x0 + radius) / size) + 1):
        for j in range(math.floor((y0 - radius) / size), math.floor((y0 + radius) / size) + 1):
            res = build(mods['generator'], mods['cellformat'], data, slots, i, j, size, pack.cell,
                        pack.region.get('seaLevel'), tune, cover, 1)
            for material, text in (res.mats.items() if res else ()):
                if text:
                    mats[material].append(np.array(text.split(), dtype=np.float64).reshape(-1, 3, 3))
    return {m: np.concatenate(v) for m, v in mats.items()}


def build(path, region, lat, lon, radius, generator=None, far=False, lidar=None, grid=400):
    """The page's data: per layer the triangles (metres east / up / -north of the place), their colours and
    their deviation from the LiDAR terrain, and the terrain itself as a grid."""
    from pyproj import Transformer
    pack = rq.Pack(Path(path), region)
    x0, y0 = audit.local(pack, lat, lon)
    to3301 = Transformer.from_crs(4326, 3301, always_xy=True)

    def en(x, y):
        la, lo = pack.geo(np.asarray(x, float), np.asarray(y, float))
        e, n = to3301.transform(lo, la)
        return np.asarray(e), np.asarray(n)

    mats = tiles(path, region, generator, far, x0, y0, radius + 30)
    sheet = find_sheet(lidar, *(float(v) for v in en(x0, y0)))
    layers, total = [], 0
    for group, _ in GROUPS:
        names = [m for m in mats if group_of(m) == group]
        if not names:
            continue
        t = np.concatenate([mats[m] for m in names])
        tri_rgb = np.concatenate([np.repeat(colour(m)[None], len(mats[m]), 0) for m in names])
        c = t.mean(1)
        keep = (np.abs(c[:, 0] - x0) <= radius) & (np.abs(c[:, 1] - y0) <= radius)
        t, tri_rgb = t[keep], tri_rgb[keep]
        if not len(t):
            continue
        dev = None
        if sheet is not None and group in DEVIATION:
            e, n = en(t[:, :, 0].ravel(), t[:, :, 1].ravel())
            dev = (t[:, :, 2].ravel() - LIFT) - sample_raster(sheet, e, n)
        pos = np.stack([t[:, :, 0] - x0, t[:, :, 2] - LIFT, -(t[:, :, 1] - y0)], -1)       # east, up, -north
        layers.append({'name': group, 'tris': int(len(t)),
                       'colour': '#%02x%02x%02x' % tuple(int(v) for v in tri_rgb.mean(0)),
                       'cols': b64(tri_rgb, np.uint8), 'pos': b64(pos),
                       'dev': b64(np.nan_to_num(dev, nan=999., posinf=999., neginf=999.)) if dev is not None else None})
        total += len(t)
    dtm = None
    if sheet is not None:
        step = max(1., 2 * radius / grid)
        n = int(2 * radius / step) + 1
        gx, gy = np.meshgrid(np.arange(n) * step - radius + x0, np.arange(n) * step - radius + y0)
        e, nn = en(gx.ravel(), gy.ravel())
        dtm = {'n': n, 'step': step, 'half': radius,
               'z': b64(np.nan_to_num(sample_raster(sheet, e, nn).reshape(n, n), nan=-9999.))}
    return {'lat': lat, 'lon': lon, 'radius': radius, 'tris': total, 'groups': layers, 'dtm': dtm,
            'lidar': sheet.name if sheet else None, 'far': bool(far)}


PAGE = r'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>EarthNG model check</title>
<style>
html,body{margin:0;height:100%;background:#1b1d22;color:#e8e8ea;font:13px/1.4 system-ui,sans-serif;overflow:hidden}
#c{display:block;width:100vw;height:100vh}
#panel{position:fixed;top:10px;left:10px;background:rgba(20,22,27,.88);border:1px solid #3a3d46;border-radius:8px;padding:10px 12px;max-width:290px}
#panel h1{font-size:13px;margin:0 0 6px;color:#ffd27a}
#panel label{display:block;margin:2px 0;cursor:pointer}
#panel .sw{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:6px;vertical-align:-1px}
#panel button{margin:6px 4px 0 0;background:#2d3039;color:#eee;border:1px solid #4a4e5a;border-radius:5px;padding:3px 8px;cursor:pointer}
#hud{position:fixed;bottom:10px;left:10px;background:rgba(20,22,27,.88);border:1px solid #3a3d46;border-radius:8px;padding:8px 12px;min-width:300px;white-space:pre;font-family:ui-monospace,Consolas,monospace}
#legend{position:fixed;top:10px;right:10px;background:rgba(20,22,27,.88);border:1px solid #3a3d46;border-radius:8px;padding:8px 12px;display:none}
#legend .bar{width:180px;height:10px;background:linear-gradient(90deg,#2b6cff,#4fc3f7,#35c46a,#ffd34f,#ff3b2f)}
#legend .ticks{display:flex;justify-content:space-between;font-size:11px;color:#bbb}
.dim{color:#9aa}
</style></head><body>
<canvas id="c"></canvas>
<div id="panel"><h1>__TITLE__</h1><div class="dim">__SUB__</div><div id="layers" style="margin-top:6px"></div>
<label><input type="checkbox" id="dtmOn"> LiDAR terrain surface</label>
<label><input type="checkbox" id="devOn"> Colour by deviation (model - LiDAR)</label>
<button id="top">Top view</button><button id="reset">Reset</button><button id="clear">Clear marks</button>
<div class="dim" style="margin-top:6px">drag: orbit - right drag: pan - wheel: zoom<br>click: measure (two clicks: distance)</div></div>
<div id="legend"><div class="bar"></div><div class="ticks"><span>-3 m</span><span>0</span><span>+3 m</span></div><div class="dim">model lower | higher than LiDAR</div></div>
<div id="hud">click the model to measure</div>
<script src="https://cdn.jsdelivr.net/npm/three@0.128.0/build/three.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/controls/OrbitControls.js"></script>
<script>
const DATA = __DATA__;
const f32 = s => { const b = atob(s), u = new Uint8Array(b.length); for (let i = 0; i < b.length; i++) u[i] = b.charCodeAt(i); return new Float32Array(u.buffer); };
const u8 = s => { const b = atob(s), u = new Uint8Array(b.length); for (let i = 0; i < b.length; i++) u[i] = b.charCodeAt(i); return u; };
const R = DATA.radius;
const renderer = new THREE.WebGLRenderer({canvas: document.getElementById('c'), antialias: true});
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
const scene = new THREE.Scene(); scene.background = new THREE.Color(0x1b1d22);
const camera = new THREE.PerspectiveCamera(55, 1, 0.5, 20000);
const controls = new THREE.OrbitControls(camera, renderer.domElement); controls.maxPolarAngle = Math.PI * 0.499;
scene.add(new THREE.HemisphereLight(0xffffff, 0x4a5260, 0.55));
const sun = new THREE.DirectionalLight(0xffffff, 0.55); sun.position.set(-300, 500, 200); scene.add(sun);
function reset() { camera.position.set(R * .55, R * .45, R * .75); controls.target.set(0, 0, 0); controls.update(); }
function topView() { camera.position.set(0, R * 1.6, 0.01); controls.target.set(0, 0, 0); controls.update(); }
const layers = {}, meshes = [];
const ramp = d => { // -3..+3 m diverging: blue, cyan, green (within .5 m), yellow, red
  if (!(Math.abs(d) < 900)) return [.35, .35, .35];
  const t = Math.max(-1, Math.min(1, d / 3));
  const stops = [[-1, [.17, .42, 1]], [-.5, [.31, .76, .97]], [0, [.21, .77, .42]], [.5, [1, .83, .31]], [1, [1, .23, .18]]];
  for (let i = 0; i < stops.length - 1; i++) { const [a, ca] = stops[i], [b, cb] = stops[i + 1];
    if (t >= a && t <= b) { const u = (t - a) / (b - a); return ca.map((v, k) => v + (cb[k] - v) * u); } }
  return [1, 1, 1];
};
for (const g of DATA.groups) {
  const pos = f32(g.pos), geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.BufferAttribute(pos, 3)); geo.computeVertexNormals();
  const tc = u8(g.cols), col = new Float32Array(pos.length), devc = new Float32Array(pos.length);
  for (let i = 0; i < pos.length / 3; i++) { const k = 3 * Math.floor(i / 3); col[3*i] = tc[k] / 255; col[3*i+1] = tc[k+1] / 255; col[3*i+2] = tc[k+2] / 255; }
  if (g.dev) { const d = f32(g.dev); for (let i = 0; i < d.length; i++) { const c = ramp(d[i]); devc[3*i] = c[0]; devc[3*i+1] = c[1]; devc[3*i+2] = c[2]; } }
  geo.setAttribute('color', new THREE.BufferAttribute(col, 3));
  const mesh = new THREE.Mesh(geo, new THREE.MeshLambertMaterial({vertexColors: true, side: THREE.DoubleSide}));
  mesh.userData = {name: g.name, base: col.slice(), dev: g.dev ? devc : null, devRaw: g.dev ? f32(g.dev) : null};
  scene.add(mesh); meshes.push(mesh); layers[g.name] = mesh;
  const l = document.createElement('label');
  l.innerHTML = `<input type="checkbox" checked> <span class="sw" style="background:${g.colour}"></span>${g.name} <span class="dim">${g.tris}</span>`;
  l.firstChild.onchange = e => { mesh.visible = e.target.checked; };
  document.getElementById('layers').appendChild(l);
}
let dtmMesh = null;
if (DATA.dtm) {
  const n = DATA.dtm.n, z = f32(DATA.dtm.z), step = DATA.dtm.step, half = DATA.dtm.half, pos = [], idx = [];
  for (let j = 0; j < n; j++) for (let i = 0; i < n; i++) pos.push(i * step - half, z[j * n + i] > -9000 ? z[j * n + i] : 0, -(j * step - half));
  for (let j = 0; j < n - 1; j++) for (let i = 0; i < n - 1; i++) {
    const a = j * n + i, b = a + 1, c = a + n, d = c + 1;
    if (z[a] > -9000 && z[b] > -9000 && z[c] > -9000 && z[d] > -9000) idx.push(a, c, b, b, c, d); }
  const geo = new THREE.BufferGeometry(); geo.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3)); geo.setIndex(idx); geo.computeVertexNormals();
  dtmMesh = new THREE.Mesh(geo, new THREE.MeshLambertMaterial({color: 0xb9a37a, side: THREE.DoubleSide, transparent: true, opacity: .55}));
  dtmMesh.visible = false; scene.add(dtmMesh);
}
function lidarAt(x, zNorth) { // the LiDAR terrain height at a point (x east, zNorth = -z of the scene), real metres
  if (!DATA.dtm) return null;
  const n = DATA.dtm.n, step = DATA.dtm.step, half = DATA.dtm.half, z = DATA._z || (DATA._z = f32(DATA.dtm.z));
  const fx = (x + half) / step, fy = (-zNorth + half) / step;   // scene z = -north
  const i = Math.floor(fx), j = Math.floor(fy); if (i < 0 || j < 0 || i >= n - 1 || j >= n - 1) return null;
  const u = fx - i, v = fy - j, a = z[j*n+i], b = z[j*n+i+1], c = z[(j+1)*n+i], d = z[(j+1)*n+i+1];
  if (a < -9000 || b < -9000 || c < -9000 || d < -9000) return null;
  return (a*(1-u)+b*u)*(1-v) + (c*(1-u)+d*u)*v;
}
document.getElementById('dtmOn').onchange = e => { if (dtmMesh) dtmMesh.visible = e.target.checked; };
document.getElementById('devOn').onchange = e => {
  document.getElementById('legend').style.display = e.target.checked ? 'block' : 'none';
  for (const m of meshes) { const c = m.geometry.attributes.color; const src = e.target.checked && m.userData.dev ? m.userData.dev : m.userData.base; c.array.set(src); c.needsUpdate = true; } };
document.getElementById('top').onclick = topView; document.getElementById('reset').onclick = reset;
const marks = [], marker = new THREE.Mesh(new THREE.SphereGeometry(.5, 12, 8), new THREE.MeshBasicMaterial({color: 0xff40ff}));
const ray = new THREE.Raycaster(), hud = document.getElementById('hud'); let pts = [];
function clearMarks() { for (const m of marks) scene.remove(m); marks.length = 0; pts = []; hud.textContent = 'click the model to measure'; }
document.getElementById('clear').onclick = clearMarks;
let down = null;
renderer.domElement.addEventListener('pointerdown', e => { down = [e.clientX, e.clientY]; });
renderer.domElement.addEventListener('pointerup', e => {
  if (!down || Math.hypot(e.clientX - down[0], e.clientY - down[1]) > 4 || e.button !== 0) return;
  const r = renderer.domElement.getBoundingClientRect();
  ray.setFromCamera(new THREE.Vector2(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1), camera);
  const targets = meshes.filter(m => m.visible).concat(dtmMesh && dtmMesh.visible ? [dtmMesh] : []);
  const hit = ray.intersectObjects(targets, false)[0]; if (!hit) return;
  const p = hit.point, ll = lidarAt(p.x, p.z), name = hit.object === dtmMesh ? 'LiDAR terrain' : hit.object.userData.name;
  if (pts.length >= 2) clearMarks();
  pts.push(p.clone()); const m = marker.clone(); m.position.copy(p); scene.add(m); marks.push(m);
  let t = `${name}   east ${p.x.toFixed(1)}  north ${(-p.z).toFixed(1)} m\nmodel z  ${p.y.toFixed(2)} m` + (ll === null ? '' : `\nLiDAR z  ${ll.toFixed(2)} m   model - LiDAR ${(p.y - ll >= 0 ? '+' : '') + (p.y - ll).toFixed(2)} m`);
  if (pts.length === 2) { const d = pts[0].distanceTo(pts[1]), h = Math.hypot(pts[1].x - pts[0].x, pts[1].z - pts[0].z), dz = pts[1].y - pts[0].y;
    t += `\n--\ndistance ${d.toFixed(1)} m   horizontal ${h.toFixed(1)} m   dz ${(dz >= 0 ? '+' : '') + dz.toFixed(2)} m   slope ${h > .1 ? (100 * dz / h).toFixed(1) + ' %' : '-'}`; }
  hud.textContent = t; });
function resize() { const w = innerWidth, h = innerHeight; renderer.setSize(w, h, false); camera.aspect = w / h; camera.updateProjectionMatrix(); }
addEventListener('resize', resize); resize(); reset();
for (const flag of location.hash.slice(1).split(',')) {
  if (flag === 'top') topView();
  if (flag === 'dtm' && dtmMesh) { document.getElementById('dtmOn').checked = true; dtmMesh.visible = true; }
  if (flag === 'dev') { const b = document.getElementById('devOn'); b.checked = true; b.onchange({target: b}); }
  if (flag.startsWith('cam:')) { // cam:east,north,back,up,heading: look at that point from `back` m behind it and `up` m over the terrain
    const [e, n, back, up, hd] = flag.slice(4).split('+').map(Number), g = lidarAt(e, n) || 0, h = hd * Math.PI / 180;
    controls.target.set(e, g, -n); camera.position.set(e - back * Math.sin(h), g + up, -(n - back * Math.cos(h))); controls.update(); }
  if (flag.startsWith('hide:')) for (const n of flag.slice(5).split('+')) if (layers[n]) layers[n].visible = false;
}
(function loop() { requestAnimationFrame(loop); controls.update(); renderer.render(scene, camera); })();
</script></body></html>'''


def page(data):
    sub = f"{data['lat']:.5f}, {data['lon']:.5f}  r {data['radius']:.0f} m  {data['tris']:,} triangles" + \
          ('  (far tiles)' if data['far'] else '') + \
          (f"<br>LiDAR terrain: {data['lidar']}" if data['lidar'] else '<br>no LiDAR terrain for this place')
    return PAGE.replace('__TITLE__', 'EarthNG model check').replace('__SUB__', sub).replace('__DATA__', json.dumps(data))


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--pack', type=Path, required=True)
    p.add_argument('--region', help='region id in a country of several (default: the first)')
    p.add_argument('--lat', type=float, required=True)
    p.add_argument('--lon', type=float, required=True)
    p.add_argument('--radius', type=float, default=300, help='m round the place')
    p.add_argument('--far', action='store_true', help='far tiles (the ring past the near radius)')
    p.add_argument('--generator', type=Path, help='another generator.lua (an A/B)')
    p.add_argument('--lidar', type=Path, help='a LiDAR terrain GeoTIFF (EPSG:3301), or a folder of them')
    p.add_argument('--out', type=Path, default=Path('out/polygon/runs/model_check.html'))
    a = p.parse_args()
    data = build(a.pack, a.region, a.lat, a.lon, a.radius, a.generator, a.far, a.lidar)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    html = page(data)
    a.out.write_text(html, encoding='utf-8')
    print(f"{a.out}: {len(html) / 1e6:.1f} MB, {data['tris']:,} triangles, layers {[g['name'] for g in data['groups']]}, "
          f"LiDAR {data['lidar']}")


if __name__ == '__main__':
    main()
