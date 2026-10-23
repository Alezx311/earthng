"""Top-down map of the street props one generator pass places, outside the game.

  python earthng/props_map.py --pack out/native-packs/earthng_ukraine.zip --lat 50.5105 --lon 30.4970 \
      --prop-spacing 12 --out out/props-map/obolon.png

Builds the near tiles round a point with the real generator (LuaJIT through bench_native's
runtime) and draws buildings, roads, paths and the areas under them with every prop as a dot
coloured by its model. Prints the count of each model and the share of props on each kind of
ground, so a change in placement shows as numbers and as a picture.
"""
import argparse
from collections import Counter
import json
import math
from pathlib import Path

from PIL import Image, ImageDraw

import bench_native

ROOT = Path(__file__).resolve().parents[1]

BUILD = '''
local native, generator, i0, j0, radius, spacing = ...
local function upvalue(f, name)
  for k = 1, 200 do local n, v = debug.getupvalue(f, k); if not n then return end; if n == name then return v end end
end
local region = upvalue(native.update, 'active').region
local d = region.data
local loadCell = upvalue(upvalue(native.update, 'buildTile'), 'loadCell')
local function cellOf(i, j, keep)
  local co = coroutine.create(function() return loadCell(string.format('%d_%d', i, j), i, j, keep) end)
  while true do
    local ok, cell = coroutine.resume(co)
    if not ok then return nil end
    if coroutine.status(co) == 'dead' then return cell end
  end
end
local out = {props = {}, buildings = {}, roads = {}, paths = {}, areas = {}}
for di = -radius, radius do
  for dj = -radius, radius do
    local i, j = i0 + di, j0 + dj
    local rect = {i * 500, j * 500, (i + 1) * 500, (j + 1) * 500}
    local cell = cellOf(math.floor(i * 500 / d.cellSize), math.floor(j * 500 / d.cellSize), rect)
    if cell then
      local _, scene = generator.build({cell}, i, j, {tileSize = 500, seaLevel = d.seaLevel, propSpacing = spacing})
      for _, it in ipairs(scene and scene.items or {}) do
        if it.prop then
          local role = it.name:gsub('^e2rl_[^_]+_[^_]+_', ''):match('^(%a+)') or ''
          local lon, lat = 0, 0
          if region.projection then lon, lat = region.projection.geographic(it.pos[1], it.pos[2]) end
          out.props[#out.props + 1] = {it.shape, it.pos[1], it.pos[2], it.streetKind or '', role, lat, lon}
        end
      end
      for _, b in ipairs(cell.buildings or {}) do out.buildings[#out.buildings + 1] = b.rings[1] end
      for _, r in ipairs(cell.roads or {}) do out.roads[#out.roads + 1] = {r.points, r.width or 7} end
      for _, l in ipairs(cell.lines or {}) do
        if l.kind == 'path' then out.paths[#out.paths + 1] = l.points end
      end
      for _, a in ipairs(cell.areas or {}) do
        local t = a.tags or {}
        out.areas[#out.areas + 1] = {a.kind, a.rings[1], t.place or t.leisure or t.landuse or ''}
      end
    end
  end
end
return out, (i0 - radius) * 500, (j0 - radius) * 500, (2 * radius + 1) * 500
'''

AREA = {'park': (186, 214, 160), 'meadow': (205, 222, 170), 'residential': (232, 226, 214), 'paved': (210, 205, 200),
        'forest': (150, 190, 130), 'water': (160, 190, 225), 'parking': (200, 200, 210)}
COLOURS = [(220, 40, 40), (40, 90, 220), (240, 150, 20), (30, 160, 60), (150, 40, 180), (0, 170, 170),
           (120, 70, 20), (230, 60, 160), (90, 90, 90), (200, 200, 0), (0, 0, 0), (255, 110, 110),
           (110, 160, 255), (60, 220, 120)]


def py(value):
    """A lupa table (nested) as Python lists/dicts."""
    if hasattr(value, 'items') and not isinstance(value, dict):
        keys = list(value.keys())
        if keys and all(isinstance(k, int) for k in keys):
            return [py(value[k]) for k in sorted(keys)]
        return {k: py(v) for k, v in value.items()}
    return value


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--pack', type=Path, default=ROOT / 'out/native-packs/earthng_ukraine.zip')
    p.add_argument('--lat', type=float, required=True)
    p.add_argument('--lon', type=float, required=True)
    p.add_argument('--radius', type=int, default=0, help='tiles round the point (0: one 500 m tile)')
    p.add_argument('--prop-spacing', type=float, default=12)
    p.add_argument('--px', type=float, default=3, help='pixels per metre')
    p.add_argument('--out', type=Path, required=True)
    a = p.parse_args()
    lua, mods, _ = bench_native.runtime(a.pack)
    native = mods['native']
    native.refresh()
    job = native.land(lua.table_from({'seq': 1, 'lat': a.lat, 'lon': a.lon}))
    if job.state == 'error':
        raise SystemExit(job.message)
    land = lua.eval('function(native) local n,v; for k=1,200 do n,v=debug.getupvalue(native.update,k); '
                    'if n=="active" then return v.landing.x, v.landing.y end end end')(native)
    i0, j0 = int(land[0] // 500), int(land[1] // 500)
    out, x0, y0, size = lua.execute(BUILD, native, mods['generator'], i0, j0, a.radius, a.prop_spacing)
    out = py(out)
    s = a.px
    w = int(size * s)
    img = Image.new('RGB', (w, w), (245, 243, 238))
    g = ImageDraw.Draw(img)

    def xy(pt):
        return ((pt[0] - x0) * s, (y0 + size - pt[1]) * s)
    for kind, ring, _tag in out['areas']:
        if kind in AREA and len(ring) > 2:
            g.polygon([xy(q) for q in ring], fill=AREA[kind])
    for points, width in out['roads']:
        if len(points) > 1:
            g.line([xy(q) for q in points], fill=(120, 120, 120), width=max(1, int(width * s)))
    for points in out['paths']:
        if len(points) > 1:
            g.line([xy(q) for q in points], fill=(190, 150, 120), width=max(1, int(1.6 * s)))
    for ring in out['buildings']:
        if len(ring) > 2:
            g.polygon([xy(q) for q in ring], fill=(160, 150, 145), outline=(90, 85, 80))
    shapes = Counter(p[0] for p in out['props'])
    colour = {name: COLOURS[n % len(COLOURS)] for n, (name, _) in enumerate(shapes.most_common())}
    r = max(2, s * .9)
    for shape, x, y, _kind, _role, _lat, _lon in out['props']:
        cx, cy = xy((x, y))
        g.ellipse([cx - r, cy - r, cx + r, cy + r], fill=colour[shape])
    legend = 8
    for name, n in shapes.most_common():
        g.rectangle([8, legend, 20, legend + 12], fill=colour[name])
        g.text((26, legend), f'{n:5d}  {name.rsplit("/", 1)[-1]}', fill=(0, 0, 0))
        legend += 16
    a.out.parent.mkdir(parents=True, exist_ok=True)
    img.save(a.out)
    # the ground under each prop: the area kind it stands in (none: untagged ground)
    import shapely
    polys = [(kind, shapely.Polygon([q[:2] for q in ring])) for kind, ring, _ in out['areas'] if len(ring) > 3]
    tree = shapely.STRtree([pp for _, pp in polys])
    ground = Counter()
    for shape, x, y, kind, _role, _lat, _lon in out['props']:
        hits = [polys[k][0] for k in tree.query(shapely.Point(x, y), predicate='intersects')]
        ground[(kind or 'furniture', hits[0] if hits else 'none')] += 1
    report = {'props': len(out['props']), 'models': dict(shapes.most_common()),
              'roles': dict(Counter(p[4] for p in out['props']).most_common()),
              # a few props of each role where a camera can look at them (lat, lon, model)
              'samples': {role: [[round(p[5], 7), round(p[6], 7), p[0].rsplit('/', 1)[-1]]
                                 for p in out['props'] if p[4] == role][::max(1, n // 4)][:4]
                          for role, n in Counter(p[4] for p in out['props']).items()},
              'ground': {f'{k[0]}@{k[1]}': v for k, v in ground.most_common()}}
    print(json.dumps(report, indent=1))
    a.out.with_suffix('.json').write_text(json.dumps(report, indent=1), encoding='utf8')


if __name__ == '__main__':
    main()
