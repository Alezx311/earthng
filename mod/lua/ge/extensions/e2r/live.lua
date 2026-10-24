-- Live window inside the game. A point with no country pack downloads OSM and
-- elevation in this process and keeps the cells in memory. The same generator
-- reads them. Nothing is handed to another program. Country packs still win.
-- Elevation is a height grid kept in memory. The download writes nothing.
local M = {}
local coordinates = require('ge/extensions/e2r/coordinates')

local CELL, GRID = 1000, 25
local LAND, DRIVE, MAX_M, GROW = 1200, 4500, 12000, 3000
local LIFT, HALO = 20, 100
local BRIDGE_CLEAR, CLEARANCE, TUNNEL_DEPTH = 6.5, 6.0, 7   -- CLEARANCE: 4.5 m under a 1.5 m deck
local MASK = '1000000000000000'
local LANDING = {'-1_-1', '-1_0', '0_-1', '0_0'}

local DRIVABLE = {motorway = true, trunk = true, primary = true, secondary = true, tertiary = true,
  residential = true, unclassified = true, service = true, living_street = true, road = true}
local LANE = {motorway = 3.75, trunk = 3.5, primary = 3.5, secondary = 3.25, tertiary = 3,
  unclassified = 2.75, residential = 2.75, road = 3}
local NARROW = {living_street = 4.5, service = 4}
local PATHS = {footway = true, path = true, pedestrian = true, cycleway = true, steps = true,
  bridleway = true, track = true}
local PAVED = {industrial = true, commercial = true, retail = true, railway = true, garages = true,
  construction = true, depot = true}
local WOODS = {forest = true, wood = true}
local PARKS = {park = true, garden = true, recreation_ground = true, cemetery = true, village_green = true}
local LOOKS = {
  {'postsoviet', 44, 22, 53, 41},
  {'north-america', 24, -125, 49.5, -66},
  {'british', 49.5, -8.5, 59.5, 2},
  {'nordic', 55, 4, 72, 32},
  {'mediterranean', 35, -10, 44.5, 20},
  {'western', 47, -5, 55, 15.5},
  {'central', 44, 13, 55, 23},
}

local function finite(v)
  return type(v) == 'number' and v == v and math.abs(v) < 1e7
end

local function number(v, default)
  if type(v) == 'number' and v == v then return v end
  if type(v) ~= 'string' then return default end
  local s = v:match('^%s*([%+%-]?%d+[%.,]?%d*)')
  if not s then return default end
  return tonumber((s:gsub(',', '.'))) or default
end

local function nid(v)
  local n = tonumber(v)
  if n and n == math.floor(n) and math.abs(n) < 2 ^ 50 then return string.format('%.0f', n) end
  return tostring(v)
end

local function oneway(tags)
  local v = tostring(tags.oneway or ''):lower()
  if v == 'yes' or v == '1' or v == '-1' or v == 'true' then return true end
  if v == 'no' or v == 'false' or v == '0' or v == 'reversible' or v == 'alternating' then return false end
  return tags.highway == 'motorway' or tags.junction == 'roundabout' or tags.junction == 'circular'
end

local function roadWidth(tags)
  local highway = tostring(tags.highway or '')
  local klass = highway:gsub('_link$', '')
  local one = oneway(tags)
  local fallback
  if NARROW[klass] and tags.lanes == nil then
    fallback = (tags.service == 'driveway' or tags.service == 'alley') and 3 or NARROW[klass]
  else
    local lanes = math.max(1, number(tags.lanes, (highway == 'motorway' or not one) and 2 or 1))
    fallback = lanes * (LANE[klass] or 3.3)
    if tags.junction == 'roundabout' or tags.junction == 'circular' then
      fallback = math.max(5.5, lanes * 4)
    end
    local left, right = 0, 0
    if tags.width == nil and tags.junction ~= 'roundabout' and tags.junction ~= 'circular' then
      if highway == 'motorway_link' or highway == 'trunk_link' then left, right = 0.25, 1
      elseif one and highway == 'trunk' then left, right = 0.5, 1.5
      elseif one and highway == 'primary' then left, right = 0.25, 0.75
      elseif highway == 'motorway' then left, right = 0.75, 2.5
      elseif highway == 'trunk' then left, right = 1, 1
      elseif highway == 'primary' then left, right = 0.5, 0.5
      elseif highway == 'secondary' then left, right = 0.25, 0.25
      end
    end
    fallback = math.max(3.2, fallback) + left + right
  end
  return math.min(35, math.max(2.5, number(tags.width, fallback)))
end

local function drivable(tags)
  local h = tags.highway
  if type(h) ~= 'string' or tags.area == 'yes' or tags.access == 'no' then return false end
  if DRIVABLE[h] then return true end
  local base = h:gsub('_link$', '')
  return base ~= h and DRIVABLE[base] == true
end

local function lineKind(tags)
  if tags.natural == 'coastline' then return 'coastline' end
  local h = tags.highway
  if PATHS[h] and tags.area ~= 'yes' and tags.footway ~= 'sidewalk' and tags.footway ~= 'crossing'
      and (tags.bridge == nil or tags.bridge == 'no') and (tags.tunnel == nil or tags.tunnel == 'no')
      and (tags.layer == nil or tags.layer == '0' or tags.layer == '') then
    return 'path'
  end
  if tags.natural == 'tree_row' then return 'tree_row' end
  if tags.barrier == 'fence' or tags.barrier == 'wall' then return 'fence' end
end

local function pointKind(tags)
  local h = tags.highway
  if h == 'crossing' then
    local marked = tags['crossing:markings'] or tags.crossing
    if marked == 'no' or marked == 'none' or marked == 'unmarked' then return nil end
    return 'crossing'
  end
  if h == 'give_way' then return 'give_way' end
  if h == 'stop' then return 'stop_sign' end
  if h == 'mini_roundabout' then return 'mini_roundabout' end
  if h == 'turning_circle' or h == 'turning_loop' then return 'turning_circle' end
  if h == 'bus_stop' then return 'stop' end
  if tags.public_transport == 'platform' and (tags.bus == 'yes' or tags.trolleybus == 'yes' or tags.tram == 'yes') then
    return 'stop'
  end
end

local function groundKind(tags)
  if tags.natural == 'water' or tags.waterway == 'riverbank' or tags.landuse == 'reservoir' or tags.natural == 'bay' then
    return 'water'
  end
  local land, natural = tags.landuse, tags.natural
  if PAVED[land] or tags.amenity == 'parking' or tags.place == 'square' then return 'paved' end
  if WOODS[land] or WOODS[natural] then return 'forest' end
  if PARKS[tags.leisure] or PARKS[land] then return 'park' end
  if land == 'residential' then return 'residential' end
  if natural == 'bare_rock' or natural == 'scree' or natural == 'beach' or natural == 'wetland'
      or natural == 'glacier' or natural == 'scrub' or natural == 'heath' then return natural end
  if natural == 'shingle' then return 'scree' end
  if natural == 'sand' then return 'beach' end
  if natural == 'bare_ground' then return 'bare_ground' end
  if natural == 'grassland' or natural == 'fell' or land == 'meadow' or land == 'grass' then return 'meadow' end
  if land == 'farmland' or land == 'orchard' or land == 'vineyard' then return land end
  if land == 'farmyard' then return 'bare_ground' end
end

function M.lookFor(lat, lon)
  for _, box in ipairs(LOOKS) do
    if lat >= box[2] and lat <= box[4] and lon >= box[3] and lon <= box[5] then return box[1] end
  end
  return 'general'
end

function M.cellIds(radius)
  local reach = math.ceil(radius / CELL) + 1
  local out = {}
  for i = -reach, reach do
    for j = -reach, reach do
      local cx, cy = (i + 0.5) * CELL, (j + 0.5) * CELL
      if cx * cx + cy * cy <= radius * radius then out[#out + 1] = {i, j} end
    end
  end
  return out
end

function M.wantedRadius(car, have)
  car, have = tonumber(car) or 0, tonumber(have) or 0
  local goal = math.min(MAX_M, math.max(LAND, car + DRIVE))
  if have <= 0 then return LAND end
  if have + 1 < goal then return math.min(goal, have + GROW) end
  return have
end

function M.frameSpec(lat, lon)
  local crs, x, y = coordinates.utm(lat, lon)
  if not crs then return nil end
  local function whole(v)
    if v >= 0 then return math.floor(v + 0.5) else return math.ceil(v - 0.5) end
  end
  return {crs = crs, origin = {whole(x), whole(y)}}
end

function M.terrarium(r, g, b)
  return r * 256 + g + b / 256 - 32768
end

function M.tileXY(lat, lon)
  local n = 4096
  lat = math.max(-85, math.min(85, lat))
  local x = math.floor((lon + 180) / 360 * n)
  local t = math.tan(math.rad(lat))
  local y = math.floor((1 - math.log(t + math.sqrt(t * t + 1)) / math.pi) / 2 * n)
  return x, y
end

function M.degreeBox(lat, lon, radius)
  local dlat = radius / 111320
  local dlon = radius / (111320 * math.max(0.2, math.cos(math.rad(lat))))
  return math.max(-180, lon - dlon), math.max(-85, lat - dlat), math.min(180, lon + dlon), math.min(85, lat + dlat)
end

local function keyOf(i, j) return string.format('%d_%d', i, j) end

local function dist(a, b)
  local dx, dy = b.x - a.x, b.y - a.y
  return math.sqrt(dx * dx + dy * dy)
end

local function layerOf(tags)
  local n = tonumber(tags.layer)
  if not n or n < 1 then return 1 end
  return n
end

local function flagged(v)
  return v ~= nil and v ~= 'no' and v ~= '0' and v ~= 'false'
end

local function breathe()
  if coroutine.running() then coroutine.yield() end
end

local function rawAt(sample, x, y)
  local z = sample(x, y)
  if not finite(z) or math.abs(z) > 10000 then return 0 end
  return z
end

local function dedup(pts)
  local out = {pts[1]}
  for i = 2, #pts do
    local p = pts[i]
    local a = out[#out]
    if (p.x - a.x) ^ 2 + (p.y - a.y) ^ 2 > 0.0025 then out[#out + 1] = p end
  end
  return out
end

local function resample(pts, sample)
  local length = 0
  for i = 2, #pts do length = length + dist(pts[i - 1], pts[i]) end
  if length <= 1 then return pts end
  local step = math.min(20, length / 2)
  local out = {pts[1]}
  local function push(p)
    local last = out[#out]
    if (p.x - last.x) ^ 2 + (p.y - last.y) ^ 2 > 0.01 then out[#out + 1] = p end
  end
  for i = 2, #pts do
    local a, b = pts[i - 1], pts[i]
    local dx, dy = b.x - a.x, b.y - a.y
    local seg = math.sqrt(dx * dx + dy * dy)
    if seg > step then
      local n = math.floor(seg / step)
      for k = 1, n do
        local t = k * step / seg
        if t < 0.999 then
          local x, y = a.x + dx * t, a.y + dy * t
          push({x = x, y = y, dem = rawAt(sample, x, y)})
        end
      end
    end
    push(b)
  end
  return out
end

local function profile(pts, bridge, tunnel, layer)
  for _, p in ipairs(pts) do p.z = p.dem + LIFT end
  if #pts < 3 or (not bridge and not tunnel) then return end
  pts[1].tip, pts[#pts].tip = true, true
  local acc, along = 0, {0}
  for i = 2, #pts do
    acc = acc + dist(pts[i - 1], pts[i])
    along[i] = acc
  end
  local z0, z1 = pts[1].z, pts[#pts].z
  for i = 2, #pts - 1 do
    local chord = z0 + (z1 - z0) * (acc > 0 and along[i] / acc or 0)
    if tunnel then pts[i].z = pts[i].dem + LIFT - TUNNEL_DEPTH * layer
    else pts[i].z = math.max(chord, pts[i].dem + LIFT + BRIDGE_CLEAR * layer) end
    pts[i].interior = true
  end
end

local function clearance(roads)
  local buckets = {}
  local function put(seg)
    local x0, x1 = math.min(seg.ax, seg.bx), math.max(seg.ax, seg.bx)
    local y0, y1 = math.min(seg.ay, seg.by), math.max(seg.ay, seg.by)
    for ix = math.floor((x0 - 40) / 32), math.floor((x1 + 40) / 32) do
      for iy = math.floor((y0 - 40) / 32), math.floor((y1 + 40) / 32) do
        local key = ix * 131072 + iy
        local list = buckets[key]
        if not list then list = {}; buckets[key] = list end
        list[#list + 1] = seg
      end
    end
  end
  for _, road in ipairs(roads) do
    if not road.bridge and not road.tunnel then
      local reach = road.width / 2 + 2
      for i = 2, #road.pts do
        local a, b = road.pts[i - 1], road.pts[i]
        put({ax = a.x, ay = a.y, az = a.z, bx = b.x, by = b.y, bz = b.z, reach = reach})
      end
    end
  end
  local seen = 0
  for _, road in ipairs(roads) do
    if road.bridge then
      local reach = road.width / 2
      for i = 2, #road.pts - 1 do
        local p = road.pts[i]
        if p.interior then
          local ix, iy = math.floor(p.x / 32), math.floor(p.y / 32)
          for dx = -2, 2 do
            for dy = -2, 2 do
              local list = buckets[(ix + dx) * 131072 + (iy + dy)]
              if list then
                for _, seg in ipairs(list) do
                  local sx, sy = seg.bx - seg.ax, seg.by - seg.ay
                  local l2 = sx * sx + sy * sy
                  local t = 0
                  if l2 > 1e-8 then
                    t = ((p.x - seg.ax) * sx + (p.y - seg.ay) * sy) / l2
                    if t < 0 then t = 0 elseif t > 1 then t = 1 end
                  end
                  local qx, qy = seg.ax + sx * t, seg.ay + sy * t
                  local limit = reach + seg.reach
                  if (p.x - qx) ^ 2 + (p.y - qy) ^ 2 <= limit * limit then
                    local qz = seg.az + (seg.bz - seg.az) * t
                    if p.z < qz + CLEARANCE then p.z = qz + CLEARANCE end
                  end
                end
              end
            end
          end
        end
        seen = seen + 1
        if seen % 200 == 0 then breathe() end
      end
    end
  end
end

local function hits(rect, pts)
  local x0, y0, x1, y1 = rect[1] - HALO, rect[2] - HALO, rect[3] + HALO, rect[4] + HALO
  for i = 1, #pts do
    local p = pts[i]
    if p.x >= x0 and p.x <= x1 and p.y >= y0 and p.y <= y1 then return true end
    if i > 1 then
      local q = pts[i - 1]
      if math.min(p.x, q.x) <= x1 and math.max(p.x, q.x) >= x0
          and math.min(p.y, q.y) <= y1 and math.max(p.y, q.y) >= y0 then return true end
    end
  end
  return false
end

local function xyz(pts)
  local out = {}
  for i, p in ipairs(pts) do out[i] = {p.x, p.y, p.z or (p.dem + LIFT)} end
  return out
end

local function sortId(list)
  table.sort(list, function(a, b) return tostring(a.id) < tostring(b.id) end)
end

-- elements: Overpass nodes and ways. project(lon, lat) -> x, y. sample(x, y) -> raw DEM metres.
-- ids: cells to emit, {{i, j}, ...}, including empty ground. A published cell is the caller's job.
function M.compile(elements, project, sample, ids, job)
  local nodes, roads, features = {}, {}, {}
  local count = 0
  for _, el in ipairs(elements or {}) do
    count = count + 1
    if count % 200 == 0 then breathe() end
    if el.type == 'node' and el.id ~= nil and finite(el.lon) and finite(el.lat) then
      local x, y = project(el.lon, el.lat)
      if finite(x) and finite(y) then
        nodes[nid(el.id)] = {x = x, y = y, tags = el.tags or {}, id = el.id}
      end
    end
  end
  for _, node in pairs(nodes) do
    node.dem = rawAt(sample, node.x, node.y)
    node.z = node.dem + LIFT
    local kind = pointKind(node.tags)
    if kind then
      features[#features + 1] = {kind = 'points', id = 'n' .. nid(node.id), pointKind = kind,
        tags = node.tags, pts = {node}}
    end
  end
  for _, el in ipairs(elements or {}) do
    if el.type == 'way' and type(el.nodes) == 'table' and type(el.tags) == 'table' then
      local tags, pts = el.tags, {}
      for _, id in ipairs(el.nodes) do
        local node = nodes[nid(id)]
        if node then pts[#pts + 1] = {x = node.x, y = node.y, dem = node.dem, z = node.z, nid = nid(id)} end
      end
      local closed = #pts >= 4 and pts[1].nid ~= nil and pts[1].nid == pts[#pts].nid
      pts = dedup(pts)
      local building = type(tags.building) == 'string' and tags.building ~= 'no'
      if not closed and building and #pts >= 3 then closed = true end
      if closed and pts[1] ~= pts[#pts] then pts[#pts + 1] = pts[1] end
      if #pts >= 2 then
        local bridge = flagged(tags.bridge)
        local tunnel = flagged(tags.tunnel) and tags.tunnel ~= 'building_passage'
        if drivable(tags) then
          if bridge or tunnel then pts = resample(pts, sample) end
          profile(pts, bridge, tunnel, layerOf(tags))
          local road = {id = 'w' .. nid(el.id), width = roadWidth(tags), tags = tags, pts = pts,
            bridge = bridge, tunnel = tunnel, nodes = {pts[1].nid or 'a', pts[#pts].nid or 'b'}}
          roads[#roads + 1] = road
          features[#features + 1] = {kind = 'roads', id = road.id, road = road, pts = pts}
        elseif lineKind(tags) then
          for _, p in ipairs(pts) do p.z = p.dem + LIFT end
          features[#features + 1] = {kind = 'lines', id = 'l' .. nid(el.id), lineKind = lineKind(tags),
            tags = tags, pts = pts}
        elseif closed and (building or groundKind(tags)) then
          for _, p in ipairs(pts) do p.z = p.dem + LIFT end
          if building then
            local feature = {kind = 'buildings', id = 'b' .. nid(el.id), building = tags.building, tags = tags, pts = pts}
            if tags.height or tags['building:levels'] then
              feature.height = math.max(2.5, math.min(850, number(tags.height, number(tags['building:levels'], 3) * 3)))
            end
            if tags.min_height then feature.minHeight = math.max(0, number(tags.min_height, 0)) end
            features[#features + 1] = feature
          else
            features[#features + 1] = {kind = 'areas', id = 'a' .. nid(el.id), areaKind = groundKind(tags),
              tags = tags, pts = pts}
          end
        end
      end
    end
    count = count + 1
    if count % 200 == 0 then breathe() end
  end
  clearance(roads)
  local cells = {}
  for _, ij in ipairs(ids or {}) do
    local i, j = ij[1], ij[2]
    local rect = {i * CELL, j * CELL, (i + 1) * CELL, (j + 1) * CELL}
    local nx = math.floor(CELL / GRID) + 1
    local heights, low = {}, math.huge
    for iy = 0, nx - 1 do
      for ix = 0, nx - 1 do
        local h = rawAt(sample, rect[1] + ix * GRID, rect[2] + iy * GRID) + LIFT
        heights[#heights + 1] = h
        if h < low then low = h end
      end
    end
    local cell = {terrain = {rect = rect, nx = nx, ny = nx, heights = heights}, low = low,
      roads = {}, junctions = {}, buildings = {}, areas = {}, lines = {}, points = {}}
    for _, feature in ipairs(features) do
      if hits(rect, feature.pts) then
        if feature.kind == 'roads' then
          local road = feature.road
          cell.roads[#cell.roads + 1] = {id = road.id, width = road.width, tags = road.tags,
            nodes = road.nodes, points = xyz(road.pts)}
        elseif feature.kind == 'buildings' then
          local item = {id = feature.id, kind = feature.building, tags = feature.tags, rings = {xyz(feature.pts)}}
          if feature.height then item.height = feature.height end
          if feature.minHeight then item.minHeight = feature.minHeight end
          cell.buildings[#cell.buildings + 1] = item
        elseif feature.kind == 'areas' then
          cell.areas[#cell.areas + 1] = {id = feature.id, kind = feature.areaKind, tags = feature.tags,
            rings = {xyz(feature.pts)}}
        elseif feature.kind == 'lines' then
          cell.lines[#cell.lines + 1] = {id = feature.id, kind = feature.lineKind, tags = feature.tags,
            points = xyz(feature.pts)}
        else
          local p = feature.pts[1]
          cell.points[#cell.points + 1] = {id = feature.id, kind = feature.pointKind, tags = feature.tags,
            pos = {p.x, p.y, p.z}}
        end
      end
    end
    for _, name in ipairs({'roads', 'buildings', 'areas', 'lines', 'points'}) do sortId(cell[name]) end
    cells[keyOf(i, j)] = cell
    if job then breathe() end
  end
  return cells
end

local function status(uk, en, seq)
  if seq and seq ~= M.seq then return end
  M.state = {message_uk = uk, message_en = en}
end

local function brief(err, limit)
  local why = tostring(err or 'download')
  why = why:gsub('^%[string%s+".-"%]:%d+:%s*', '')
  why = why:gsub('^%S+:%d+:%s*', '')
  why = why:gsub('[%c]+', ' ')
  limit = limit or 140
  if #why > limit then why = why:sub(1, limit) end
  return why
end

local function boxOf(keys)
  local w, s, e, n = math.huge, math.huge, -math.huge, -math.huge
  for key in pairs(keys) do
    local i, j = key:match('^(-?%d+)_(-?%d+)$')
    i, j = tonumber(i), tonumber(j)
    if i then
      for _, p in ipairs({{i * CELL, j * CELL}, {(i + 1) * CELL, j * CELL},
          {i * CELL, (j + 1) * CELL}, {(i + 1) * CELL, (j + 1) * CELL}}) do
        local lon, lat = M.frame.geographic(p[1], p[2])
        w, s, e, n = math.min(w, lon), math.min(s, lat), math.max(e, lon), math.max(n, lat)
      end
    end
  end
  return {w, s, e, n}
end

local function publish()
  for _, key in ipairs(LANDING) do if not M.store[key] then return end end
  if not M.doc then
    local g = M.frame.affineAt(0, 0)
    M.doc = {
      schemaVersion = 2, sourceFormat = 'earthng-features-v2', runtime = 'lua', id = 'here',
      blockCells = 1, cellSize = CELL, tileSize = 500, seaLevel = LIFT, landing = {0, 0},
      look = M.look, frame = {crs = M.spec.crs, origin = {M.spec.origin[1], M.spec.origin[2]}},
      frameToken = M.spec.crs .. ':' .. M.spec.origin[1] .. ':' .. M.spec.origin[2],
      blocks = {}, serial = 0, seq = M.seq,
      geo = {g[1], g[2], g[3], g[4], g[5], g[6], g[7], g[8]},
    }
    M.cached = nil
  end
  local added = false
  for key in pairs(M.store) do
    if M.doc.blocks[key] == nil then
      M.doc.blocks[key] = {memory = true, mask = MASK}
      added = true
    end
  end
  local box = boxOf(M.store)
  M.doc.bounds = box
  M.doc.coverage = {box}
  if added then M.doc.serial = (M.doc.serial or 0) + 1 end
  M.doc.ready = true
  M.doc.seq = M.seq
end

local function pin(lat, lon)
  local spec = M.frameSpec(lat, lon)
  if not spec then return false end
  M.spec, M.look = spec, {block = M.lookFor(lat, lon)}
  M.frame = coordinates.frame(spec)
  M.store, M.doc, M.cached = {}, nil, nil
  M.radius, M.carM, M.lat, M.lon = 0, 0, lat, lon
  return true
end

function M.begin(lat, lon)
  M.seq = (M.seq or 0) + 1
  return pin(lat, lon) and M.spec or nil
end

function M.put(cells, seq)
  if seq and seq ~= M.seq then return false end
  if not M.store or type(cells) ~= 'table' then return false end
  local added = false
  for key, cell in pairs(cells) do
    if type(key) == 'string' and M.store[key] == nil and type(cell) == 'table' then
      M.store[key] = cell
      added = true
    end
  end
  if added then publish() end
  return added
end

function M.cell(i, j)
  if not M.store then return nil end
  return M.store[keyOf(i, j)]
end

local function regionOf(doc)
  local coverage = doc.coverage
  local country = {id = 'live', title = 'Live', available = true, coverage = coverage, runtime = 'native'}
  local descriptor = {id = 'here', coverage = coverage}
  return {
    country = country, descriptor = descriptor, data = doc, coverage = coverage,
    projection = coordinates.frame(doc.frame), serial = doc.serial, frameToken = doc.frameToken,
  }
end

local function changed(region, doc)
  if region.frameToken ~= doc.frameToken then return false end
  if region.serial == doc.serial then return false end
  region.coverage = doc.coverage
  region.country.coverage = doc.coverage
  region.descriptor.coverage = doc.coverage
  region.serial = doc.serial
  return true
end

function M.sync()
  local doc = M.doc
  if not doc or doc.seq ~= M.seq or doc.ready ~= true or type(doc.blocks) ~= 'table' then return nil end
  local region = M.cached
  if not region or region.frameToken ~= doc.frameToken then
    region = regionOf(doc)
    M.cached = region
    return region
  end
  if region.serial ~= doc.serial then changed(region, doc) end
  return region
end

function M.absorb(region)
  local doc = M.doc
  if not doc or doc.seq ~= M.seq or doc.ready ~= true or not region or region.serial == doc.serial then
    return false
  end
  return changed(region, doc)
end

function M.note(lat, lon)
  if not M.frame or not M.seq or not finite(lat) or not finite(lon) then return end
  local now = os.clock()
  if M.noted and now - M.noted < 2 then return end
  M.noted = now
  local x, y = M.frame.localPoint(lat, lon)
  local d = math.sqrt(x * x + y * y)
  if not M.carM or math.abs(d - M.carM) >= 30 then M.carM = d end
end

function M.status()
  return M.state
end

function M.parseOverpass(text)
  if type(text) ~= 'string' or text == '' then return nil, 'empty' end
  local head = text:sub(1, 240):lower()
  if head:find('<html', 1, true) or head:find('<remark', 1, true) or head:find('<!doctype', 1, true) then
    return nil, 'overpass refused'
  end
  if type(jsonDecode) ~= 'function' then return nil, 'no json' end
  local ok, doc = pcall(jsonDecode, text)
  if not ok or type(doc) ~= 'table' then return nil, 'not json' end
  if doc.remark then return nil, tostring(doc.remark):sub(1, 140) end
  if type(doc.elements) ~= 'table' then return nil, 'no elements' end
  return doc.elements
end

-- The game curl only talks to api.beamng.com. A foreign address is prefixed
-- onto that host, and the 404 body matches the game API. These two answers
-- are plain HTTP from the game's own luasocket.
local function httpNote(msg)
  if type(log) == 'function' then pcall(log, 'I', 'earthng.live', msg) end
end

local function httpCall(method, url, body, contentType, timeout)
  local okH, http = pcall(require, 'socket.http')
  local okL, ltn12 = pcall(require, 'ltn12')
  if not okH or not okL then return nil, 'http socket' end
  http.TIMEOUT = timeout or 60
  local chunks = {}
  local headers = {['User-Agent'] = 'EarthNG/0.6 (BeamNG live)', ['Accept'] = '*/*'}
  local req = {url = url, method = method or 'GET', headers = headers, sink = ltn12.sink.table(chunks)}
  if type(body) == 'string' then
    headers['Content-Type'] = contentType or 'text/plain'
    headers['Content-Length'] = tostring(#body)
    req.source = ltn12.source.string(body)
  end
  httpNote((method or 'GET') .. ' ' .. url:sub(1, 140))
  local ok, code = http.request(req)
  local text = table.concat(chunks)
  if not ok then return nil, 'http ' .. brief(code, 80) end
  if #text > 48 * 1024 * 1024 then return nil, 'http huge' end
  code = tonumber(code) or 0
  httpNote(string.format('http %s bytes=%d', tostring(code), #text))
  return text, code
end

local function overpass(west, south, east, north)
  local b = string.format('(%.5f,%.5f,%.5f,%.5f)', south, west, north, east)
  local query = '[out:json][timeout:90];('
    .. 'way["highway"]' .. b .. ';'
    .. 'way["building"]' .. b .. ';'
    .. 'way["landuse"]' .. b .. ';'
    .. 'way["natural"]' .. b .. ';'
    .. 'way["leisure"]' .. b .. ';'
    .. 'way["waterway"]' .. b .. ';'
    .. 'way["barrier"]' .. b .. ';'
    .. 'node["highway"~"bus_stop|crossing|stop|give_way"]' .. b .. ';'
    .. ');(._;>;);out body;'
  local text, code = httpCall('POST', 'http://overpass.osm.ch/api/interpreter', query, 'text/plain', 90)
  if type(code) ~= 'number' then return nil, 'overpass ' .. brief(code, 80) end
  if not text or code ~= 200 then return nil, 'overpass ' .. tostring(code) .. ' ' .. brief(text, 48) end
  return M.parseOverpass(text)
end

local function elevationsOf(text)
  local list = type(text) == 'string' and text:match('"elevation"%s*:%s*%[(.-)%]')
  if not list then return nil end
  local nums = {}
  for token in list:gmatch('[^,%s]+') do nums[#nums + 1] = tonumber(token) or 0 end
  return nums
end

local function prefetchDem(west, south, east, north)
  local mid = (south + north) / 2
  local span = math.max((north - south) * 111320, (east - west) * 111320 * math.max(0.2, math.cos(math.rad(mid))))
  local stepM = span > 48 * 100 and span / 48 or 100
  local stepLat = stepM / 111320
  local stepLon = stepM / (111320 * math.max(0.2, math.cos(math.rad(mid))))
  local nx = math.max(2, math.floor((east - west) / stepLon) + 1)
  local ny = math.max(2, math.floor((north - south) / stepLat) + 1)
  local have = M.demGrid
  if have and have.west <= west and have.east >= east and have.south <= south and have.north >= north
      and have.stepM <= stepM + 1 then
    return true
  end
  local lats, lons = {}, {}
  for iy = 0, ny - 1 do
    local lat = math.min(north, south + iy * stepLat)
    for ix = 0, nx - 1 do
      lats[#lats + 1] = string.format('%.5f', lat)
      lons[#lons + 1] = string.format('%.5f', math.min(east, west + ix * stepLon))
    end
  end
  local heights = {}
  for i = 1, #lats, 60 do
    local j = math.min(i + 59, #lats)
    local latPart, lonPart = {}, {}
    for k = i, j do
      latPart[#latPart + 1] = lats[k]
      lonPart[#lonPart + 1] = lons[k]
    end
    local url = 'http://api.open-meteo.com/v1/elevation?latitude=' .. table.concat(latPart, ',')
      .. '&longitude=' .. table.concat(lonPart, ',')
    local body, code = httpCall('GET', url, nil, nil, 30)
    if type(code) ~= 'number' or code ~= 200 then
      return nil, 'elevation ' .. tostring(code) .. ' ' .. brief(body, 40)
    end
    local nums = elevationsOf(body)
    if not nums or #nums ~= (j - i + 1) then return nil, 'elevation parse' end
    for n = 1, #nums do heights[#heights + 1] = nums[n] end
    breathe()
  end
  M.demGrid = {west = west, south = south, east = east, north = north, stepLat = stepLat,
    stepLon = stepLon, stepM = stepM, nx = nx, ny = ny, h = heights}
  return true
end

local function gridAt(lat, lon)
  local g = M.demGrid
  if not g or not g.stepLon or g.stepLon == 0 or not g.stepLat or g.stepLat == 0 then return 0 end
  local fx = (lon - g.west) / g.stepLon
  local fy = (lat - g.south) / g.stepLat
  if fx ~= fx or fy ~= fy then return 0 end
  fx = math.max(0, math.min(g.nx - 1.0001, fx))
  fy = math.max(0, math.min(g.ny - 1.0001, fy))
  local x0, y0 = math.floor(fx), math.floor(fy)
  local x1, y1 = math.min(x0 + 1, g.nx - 1), math.min(y0 + 1, g.ny - 1)
  local tx, ty = fx - x0, fy - y0
  local function h(ix, iy) return g.h[iy * g.nx + ix + 1] or 0 end
  local a = h(x0, y0) * (1 - tx) + h(x1, y0) * tx
  local b = h(x0, y1) * (1 - tx) + h(x1, y1) * tx
  return a * (1 - ty) + b * ty
end

local function demSample()
  return function(x, y)
    local lon, lat = M.frame.geographic(x, y)
    return gridAt(lat, lon)
  end
end

local function remember(seq, list)
  local seen, out = {}, {}
  for _, el in ipairs(list or {}) do
    local id = tostring(el.type) .. ':' .. nid(el.id)
    if not seen[id] then
      seen[id] = true
      out[#out + 1] = el
    end
  end
  return out
end

local function ring(lat, lon, radius, seq)
  local w, s, e, n = M.degreeBox(lat, lon, radius + HALO)
  local boxes
  if radius <= LAND then boxes = {{w, s, e, n}}
  else
    local mx, my = (w + e) / 2, (s + n) / 2
    boxes = {{w, s, mx, my}, {mx, s, e, my}, {w, my, mx, n}, {mx, my, e, n}}
  end
  local elements = {}
  for _, b in ipairs(boxes) do
    if seq ~= M.seq then return false end
    breathe()
    status('Качаю OSM…', 'Downloading OSM…', seq)
    local part, err = overpass(b[1], b[2], b[3], b[4])
    if not part then return err or 'overpass' end
    for _, el in ipairs(part) do elements[#elements + 1] = el end
    breathe()
  end
  elements = remember(seq, elements)
  if seq ~= M.seq then return false end
  status('Качаю висоти…', 'Downloading elevation…', seq)
  breathe()
  local raised, why = prefetchDem(w, s, e, n)
  if not raised then return why or 'elevation' end
  local ids = {}
  for _, ij in ipairs(M.cellIds(radius)) do
    if not M.store[keyOf(ij[1], ij[2])] then ids[#ids + 1] = ij end
  end
  if seq ~= M.seq then return false end
  status('Збираю дороги й висоти…', 'Building roads and elevation…', seq)
  breathe()
  local cells = M.compile(elements, function(lon, lat) return M.frame.localPoint(lat, lon) end, demSample(), ids, true)
  if seq ~= M.seq then return false end
  M.put(cells, seq)
  M.radius = radius
  return true
end

function M._run(job, lat, lon, seq)
  status('Качаю OSM і висоти…', 'Downloading OSM and elevation…', seq)
  breathe()
  local radius = 0
  while seq == M.seq do
    local want = M.wantedRadius(M.carM or 0, radius)
    if want <= radius + 1 then
      if radius >= MAX_M then
        status('Вікно зібране. Далі потрібен пакет країни.', 'The window is built. Farther out needs a country pack.', seq)
      end
      if job and job.sleep then job.sleep(2) else break end
    else
      local ok, result = pcall(ring, lat, lon, want, seq)
      if seq ~= M.seq then return end
      if not ok or result ~= true then
        local why = brief(result, 160)
        status('Не вдалось скачати (' .. why .. '). Спробую ще.',
          'The download failed (' .. why .. '). Retrying.', seq)
        if job and job.sleep then job.sleep(8) else return end
      else
        radius = want
        if M.doc and M.doc.ready then
          status('Можна висаджуватись. Околиця ще докачується.',
            'You can land. The surroundings are still downloading.', seq)
        end
        breathe()
      end
    end
  end
end

function M.request(lat, lon)
  if not finite(lat) or not finite(lon) or lat < -80 or lat > 84 then return false end
  M.seq = (M.seq or 0) + 1
  local seq = M.seq
  if not pin(lat, lon) then
    status('Цю точку не зібрати.', 'This point cannot be built.', seq)
    return false
  end
  status('Качаю OSM і висоти…', 'Downloading OSM and elevation…', seq)
  local jobs = rawget(_G, 'core_jobsystem')
  if type(jobs) == 'table' and type(jobs.create) == 'function' then
    jobs.create(function(job) M._run(job, lat, lon, seq) end, 0)
    return true
  end
  status('Немає планувальника кадрів гри.', 'The game frame scheduler is missing.', seq)
  return false
end

return M
