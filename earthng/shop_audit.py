"""Storefront experiment audit: the game's generator over a real pack, decisions per mapped node.

  python earthng/shop_audit.py --pack out/.../earthng_spot-bilychi.zip --lat 50.46036 --lon 30.34419 --radius 2 --json out/.../shop_audit.json

Lands like bench_native.py, then builds each near tile round the landing twice: as the game
does (baseline) and with experimentalShopfront and the game's cellSize. Every 'poi' point and
every shop-tagged building the generator weighed is reported once, with its decision and
reason (BLD.shopLinks), the tiles that drew a storefront, and per tile the shop triangles,
total triangles and build ms of both runs. A node judged differently by two tiles is listed
as inconsistent. OSM node ids are recovered from the point ids (-(10**12 + id)).
"""
import argparse
import collections
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import bench_native  # noqa: E402

TILES = '''
local native, generator, i0, j0, radius = ...
local function upvalue(f, name)
  for k = 1, 200 do local n, v = debug.getupvalue(f, k); if not n then return end; if n == name then return v end end
end
local active = upvalue(native.update, 'active')
local d = active.region.data
local loadCell = upvalue(upvalue(native.update, 'buildTile'), 'loadCell')
local function cellOf(i, j, keep)
  local co = coroutine.create(function() return loadCell(string.format('%d_%d', i, j), i, j, keep) end)
  while true do
    local ok, cell = coroutine.resume(co)
    if not ok then error(cell) end
    if coroutine.status(co) == 'dead' then return cell end
  end
end
local out = {}
for di = -radius, radius do
  for dj = -radius, radius do
    local i, j = i0 + di, j0 + dj
    local rect = {i * 500, j * 500, (i + 1) * 500, (j + 1) * 500}
    -- the cells the game's buildTile gives this tile: its own and those within 40 m
    local cells, seen = {}, {}
    for ci = math.floor((rect[1] - 40) / d.cellSize), math.ceil((rect[3] + 40) / d.cellSize) - 1 do
      for cj = math.floor((rect[2] - 40) / d.cellSize), math.ceil((rect[4] + 40) / d.cellSize) - 1 do
        local c = cellOf(ci, cj, rect)
        if c and not seen[c] then seen[c] = true; cells[#cells + 1] = c end
      end
    end
    local row = {key = i .. '_' .. j}
    for _, on in ipairs({false, true}) do
      local report = {}
      collectgarbage('collect')
      local t = clock()
      local road, scene = generator.build(cells, i, j, {tileSize = 500, pause = function() end,
        seaLevel = d.seaLevel, experimentalShopfront = on or nil, cellSize = on and d.cellSize or nil,
        poiReport = on and report or nil})
      local ms = (clock() - t) * 1000
      local tris, shop = 0, 0
      for _, m in ipairs({road, scene}) do
        for _, it in ipairs(m.items) do
          for _, mesh in ipairs(it.meshes or {}) do
            tris = tris + #mesh.faces / 3
            if mesh.material:find('e2rf_wall_shop_', 1, true) == 1 then shop = shop + #mesh.faces / 3 end
          end
        end
      end
      local tag = on and 'on' or 'off'
      row[tag .. 'Ms'], row[tag .. 'Tris'], row[tag .. 'Shop'] = ms, tris, shop
      if on then row.report = report end
    end
    out[#out + 1] = row
  end
end
local proj = active.region.projection
return out, d.frame, function(x, y) return proj.geographic(x, y) end
'''


def plain(value):
    if hasattr(value, 'items') and not isinstance(value, dict):
        items = dict(value.items())
        if items and all(isinstance(k, int) for k in items):
            return [plain(items[k]) for k in sorted(items)]
        return {k: plain(v) for k, v in items.items()}
    if isinstance(value, bytes):
        return value.decode('utf8')
    return value


def osm_node(point_id):
    try:
        return int(-int(str(point_id).split(':')[0]) - 10**12)
    except ValueError:
        return None


def main():
    p = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    p.add_argument('--pack', type=Path, required=True)
    p.add_argument('--lat', type=float, required=True)
    p.add_argument('--lon', type=float, required=True)
    p.add_argument('--radius', type=int, default=2)
    p.add_argument('--json', type=Path)
    p.add_argument('--square', type=float, nargs=4, metavar=('X0', 'Y0', 'X1', 'Y1'),
                   help="the analysis square in the pack frame's CRS (Bilychi: EPSG:32636 metres)")
    a = p.parse_args()
    lua, mods, _ = bench_native.runtime(a.pack)
    native = mods['native']
    native.refresh()
    job = native.land(lua.table_from({'seq': 1, 'lat': a.lat, 'lon': a.lon}))
    if job.state == 'error':
        sys.exit(job.message)
    land = lua.eval('function(native) local n,v; for k=1,200 do n,v=debug.getupvalue(native.update,k); '
                    'if n=="active" then return v.landing.x, v.landing.y end end end')(native)
    i0, j0 = int(land[0] // 500), int(land[1] // 500)
    rows, frame, geographic = lua.execute(TILES, native, mods['generator'], i0, j0, a.radius)
    rows, frame = plain(rows), plain(frame)
    ox, oy = frame['origin'][0], frame['origin'][1]

    def place(entry, x, y):
        lon, lat = geographic(x, y)
        entry['lat'], entry['lon'] = round(lat, 7), round(lon, 7)
        if a.square:
            entry['inSquare'] = a.square[0] <= x + ox <= a.square[2] and a.square[1] <= y + oy <= a.square[3]
    pois, buildings, draws = {}, {}, collections.defaultdict(dict)
    inconsistent = set()
    for row in rows:
        for entry in row.pop('report') or []:
            entry = dict(entry)
            if entry['evidence'] == 'draw':
                draws[entry['building']][row['key']] = entry.get('reason') or 'drawn'
                continue
            key = entry.get('poi') or 'building:' + entry['building']
            table = pois if entry['evidence'] == 'poi' else buildings
            judged = (entry.get('decision'), entry.get('reason'), entry.get('wall'), str(entry.get('span')))
            if key in table and table[key]['judged'] != judged:
                inconsistent.add(key)
            entry['judged'] = judged
            entry.setdefault('tiles', [])
            table.setdefault(key, entry)['tiles'].append(row['key'])
    for table in (pois, buildings):
        for key, entry in table.items():
            entry.pop('judged')
            if entry.get('building') in draws:
                entry['draw'] = draws[entry['building']]
            if entry['evidence'] == 'poi':
                entry['osm'] = f"node/{osm_node(entry['poi'])}"
            place(entry, entry['x'], entry['y'])
            if entry.get('wall'):
                x1, y1, x2, y2 = (float(v) for v in entry['wall'].split(','))
                length = ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** .5
                s0, s1 = entry.get('span') or (0, length)
                mid = (s0 + s1) / 2 / length
                mx, my = x1 + (x2 - x1) * mid, y1 + (y2 - y1) * mid
                nx, ny = (y2 - y1) / length, -(x2 - x1) / length
                # a camera on the street side looking back at the storefront
                view = {}
                place(view, mx + nx * 12, my + ny * 12)
                at = {}
                place(at, mx, my)
                entry['view'] = f"{view['lat']},{view['lon']},1.7:{at['lat']},{at['lon']},2:60"

    if a.square:
        pois = {k: e for k, e in pois.items() if e.get('inSquare')}
        buildings = {k: e for k, e in buildings.items() if e.get('inSquare')}
    summary = {
        'pack': str(a.pack), 'lat': a.lat, 'lon': a.lon, 'tiles': len(rows), 'frame': frame, 'square': a.square,
        'drawnPoi': sum(1 for e in pois.values() if e['decision'] == 'linked' and 'drawn' in (e.get('draw') or {}).values()
                        or any(v == 'house_walls_replaced' for v in (e.get('draw') or {}).values())),
        'poi': dict(collections.Counter(e.get('reason') or e['decision'] for e in pois.values())),
        'building_tag': dict(collections.Counter(e.get('reason') or e['decision'] for e in buildings.values())),
        'inconsistent': sorted(inconsistent),
        'shopTriangles': sum(r['onShop'] for r in rows),
        'trianglesOff': sum(r['offTris'] for r in rows), 'trianglesOn': sum(r['onTris'] for r in rows),
        'msOff': sum(r['offMs'] for r in rows), 'msOn': sum(r['onMs'] for r in rows),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    if a.json:
        a.json.parent.mkdir(parents=True, exist_ok=True)
        a.json.write_text(json.dumps({'summary': summary, 'tiles': rows, 'pois': pois, 'buildings': buildings},
                                     ensure_ascii=False, indent=1), encoding='utf-8')


if __name__ == '__main__':
    main()
