-- Experimental OSM_DEV point objects. Reads a small, explicitly versioned opt-in
-- file from the user VFS; source OSM and country packs are never changed.
local M = {}
M.path = 'settings/earthng-overrides.json'
M.schema = 'earthng-object-overrides-v1'
M.bench = '/levels/east_coast_usa/art/shapes/clutter/clutter_city_bench_wood.dae'
local function finite(x) return type(x) == 'number' and x == x and x ~= math.huge and x ~= -math.huge end
local function keys(t, allowed)
  if type(t) ~= 'table' then return false end
  for k in pairs(t) do if not allowed[k] then return false end end
  return true
end
local function uuid(s)
  return type(s) == 'string' and #s == 36 and s:match('^[0-9a-f]+%-[0-9a-f]+%-[0-9a-f]+%-[0-9a-f]+%-[0-9a-f]+$')
    and s:sub(9, 9) == '-' and s:sub(14, 14) == '-' and s:sub(19, 19) == '-' and s:sub(24, 24) == '-'
end
local function bounded(v, lo, hi) return finite(v) and v >= lo and v <= hi end

-- All-or-nothing validation: malformed content must not partly modify the world.
function M.validate(data)
  if not keys(data, {schema=true, objects=true}) or data.schema ~= M.schema or type(data.objects) ~= 'table' then
    return nil, 'invalid schema or objects'
  end
  local count, seen, out = 0, {}, {}
  for k in pairs(data.objects) do
    if not finite(k) or k < 1 or k % 1 ~= 0 then return nil, 'objects must be an array' end
    count = count + 1
  end
  if count > 1000 then return nil, 'too many objects' end
  for i = 1, count do
    local p = data.objects[i]
    if not keys(p, {id=true, lat=true, lon=true, shape=true, altitude=true, yaw_degrees=true, scale=true})
      or not uuid(p.id) or seen[p.id] or not bounded(p.lat, -85, 85) or not bounded(p.lon, -180, 180)
      or p.shape ~= M.bench or not keys(p.altitude, {mode=true, meters=true})
      or p.altitude.mode ~= 'terrain' or not bounded(p.altitude.meters, -2, 2)
      or not bounded(p.yaw_degrees, -360, 360) or not bounded(p.scale, .25, 2) then
      return nil, 'invalid object at index ' .. i
    end
    seen[p.id] = true
    out[#out + 1] = {id=p.id, lat=p.lat, lon=p.lon, shape=p.shape,
      height=p.altitude.meters, yaw=p.yaw_degrees * math.pi / 180, scale=p.scale,
      -- A conservative circle around the measured 2 x 0.714 m bench footprint.
      radius=1.063 * p.scale}
  end
  table.sort(out, function(a, b) return a.id < b.id end)
  return out, nil
end

function M.load(project)
  local present, value = pcall(function() return FS:fileExists(M.path) end)
  if not present then return {}, 'cannot check ' .. M.path end
  if not value then return {}, nil end
  local ok, data = pcall(jsonReadFile, M.path)
  if not ok then return {}, 'cannot read ' .. M.path end
  local records, err = M.validate(data)
  if not records then return {}, err end
  if #records > 0 then
    local exists, found = pcall(function() return FS:fileExists(M.bench) end)
    if not exists or not found then return {}, 'bench shape unavailable in VFS' end
  end
  for _, p in ipairs(records) do
    local projected, x, y = pcall(project, p.lat, p.lon)
    if not projected or not finite(x) or not finite(y) then return {}, 'coordinate projection failed' end
    p.x, p.y = x, y
  end
  return records, nil
end

local function distance2(x, y, a, b)
  local dx, dy = b[1] - a[1], b[2] - a[2]
  local d = dx * dx + dy * dy
  local t = d > 0 and math.max(0, math.min(1, ((x-a[1])*dx + (y-a[2])*dy) / d)) or 0
  return (x-a[1]-t*dx)^2 + (y-a[2]-t*dy)^2
end
local function inPolygon(x, y, rings, radius, tick)
  local inside = false
  for _, ring in ipairs(rings or {}) do
    local hit = false
    for i, a in ipairs(ring) do
      tick()
      local b = ring[i % #ring + 1]
      if distance2(x, y, a, b) <= radius * radius then return true end
      if (a[2] > y) ~= (b[2] > y) and x < (b[1]-a[1]) * (y-a[2]) / (b[2]-a[2]) + a[1] then hit = not hit end
    end
    if hit then inside = not inside end
  end
  return inside
end

-- Conservative clearance against source features. Nearby tile ownership uses a halo:
-- accepted objects reserve the same area in both tiles, while drawing is half-open.
function M.plan(records, rect, lists, segments, scene, signs, pause)
  local accepted, rejected = {}, {}
  local checks = 0
  local function tick()
    checks = checks + 1
    if pause and checks % 128 == 0 then pause() end
  end
  for _, p in ipairs(records or {}) do
    local x, y, r = p.x, p.y, p.radius + .4
    if x >= rect[1] - 12 and x < rect[3] + 12 and y >= rect[2] - 12 and y < rect[4] + 12 then
      local clear, reason = true, nil
      for _, road in ipairs(segments or {}) do
        tick()
        if road.surface and distance2(x, y, road.a, road.b) < (r + road.width / 2 + .3)^2 then clear, reason = false, 'road'; break end
      end
      if clear then for _, b in ipairs(lists.buildings or {}) do
        tick()
        if inPolygon(x, y, b.rings, r + .6, tick) then clear, reason = false, 'building'; break end
      end end
      if clear then for _, a in ipairs(lists.areas or {}) do
        tick()
        local tags = a.tags or {}
        if (a.kind == 'water' or a.kind == 'paved' or a.kind == 'parking' or tags.amenity == 'parking')
          and inPolygon(x, y, a.rings, r, tick) then clear, reason = false, 'water/paved/parking'; break end
      end end
      if clear then for _, line in ipairs(lists.lines or {}) do
        tick()
        local pts = line.points or {}
        local width = tonumber((line.tags or {}).width) or 2
        for k = 1, #pts-1 do
          tick()
          if distance2(x, y, pts[k], pts[k+1]) < (r + math.max(.5, math.min(width / 2, 40)))^2 then clear, reason = false, 'mapped line'; break end
        end
        if not clear then break end
      end end
      if clear then for _, point in ipairs(lists.points or {}) do
        tick()
        if point.pos then
          local d = point.kind == 'stop' and 65 or (point.kind == 'tree' and 4 or 2)
          if (x-point.pos[1])^2 + (y-point.pos[2])^2 < (r+d)^2 then clear, reason = false, 'mapped point'; break end
        end
      end end
      if clear then for _, item in ipairs((scene or {}).items or {}) do
        tick()
        if item.kind == 'static' and item.pos and (x-item.pos[1])^2 + (y-item.pos[2])^2 < (r+4)^2 then clear, reason = false, 'existing static'; break end
      end end
      if clear then for _, sign in ipairs(signs or {}) do
        tick()
        if (x-sign[1])^2 + (y-sign[2])^2 < (r+2.6)^2 then clear, reason = false, 'sign'; break end
      end end
      if clear then for _, other in ipairs(accepted) do
        tick()
        if (x-other.x)^2 + (y-other.y)^2 < (r+other.radius+.4)^2 then clear, reason = false, 'another manual object'; break end
      end end
      if clear then accepted[#accepted + 1] = p
      else rejected[#rejected + 1] = {id=p.id, x=p.x, y=p.y, reason=reason} end
    end
  end
  return accepted, rejected
end
return M
