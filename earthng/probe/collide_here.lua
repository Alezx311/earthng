-- What the car would meet round it, and is any of it not drawn. A session of
-- test_world.py --manual --probe, the car standing by the place:
--   python earthng/probe.py --user <out>/user --timeout 120 -f earthng/probe/collide_here.lua
-- Level rays of the physics' static collision (castRayStatic: what the car meets) go out from the
-- car in `dirs` directions at `heights` m over the ground under the car, `reach` m long, from the
-- car's centre and from points `ring` m round it. Each stop that stands at least `stands` m over
-- the ground just before it is then asked of the drawn world (Engine.castRay on render geometry,
-- the same segment; it sees objects and the terrain, not EarthNG's ProceduralMesh): a stop it
-- names is an object, the rest are meshes, the terrain block or a stale piece. For each such
-- stop the probe names what could be there: scene objects whose world box holds the point (class,
-- name, group, hidden, collision type), the hidden terrain block's height there (turf.lua), Forest
-- items of a collidable kind within 1.5 m. Then the world's own collision rebuild is forced and the
-- rays are cast again: a stop that goes is a stale piece of an earlier snapshot (an object deleted
-- or hidden since the last rebuild), one that stays is in the scene now.
local dirs, heights, reach, ring, stands, near = 48, {.12, .3, .6, 1.0}, 14, {0, 4}, .08, .6
local veh = getPlayerVehicle(0)
local at = veh and veh:getPosition() or core_camera.getPosition()
local W = extensions.e2r_world

local function groundAt(x, y, z)
  local d = castRayStatic(vec3(x, y, z + 4), vec3(0, 0, -1), 12)
  return d and d < 12 and (z + 4 - d) or nil
end

local function describe(o)
  local okC, cls = pcall(function() return o:getClassName() end)
  local name = (pcall(function() return o:getName() end)) and o:getName() or ''
  local group = ''
  pcall(function() local g = o:getGroup(); group = g and g:getName() or '' end)
  local hidden = false
  pcall(function() hidden = o:isHidden() end)
  local ctype, shape = '', ''
  if okC and cls == 'TSStatic' then
    ctype = tostring(o:getField('collisionType', 0))
    shape = tostring(o:getField('shapeName', 0)):match('([^/]+)$') or ''
  end
  return string.format('%s %s [%s]%s %s %s', cls or '?', name, group, hidden and ' hidden' or '', ctype, shape)
end

-- scene objects whose world box holds p (or comes within .3 m of it)
local function boxed(p)
  local out = {}
  local function look(g, depth)
    if depth > 3 or not g then return end
    for n = 0, g:getCount() - 1 do
      local raw = g:getObject(n)
      local o = raw and scenetree.findObjectById(raw:getID())
      if o then
        local okC, cls = pcall(function() return o:getClassName() end)
        if okC and (cls == 'SimGroup') then look(o, depth + 1)
        elseif okC and cls ~= 'BeamNGVehicle' then
          local ok, box = pcall(function() return o:getWorldBox() end)
          if ok and box and box.minExtents then
            local mn, mx = box.minExtents, box.maxExtents
            if p.x >= mn.x - .3 and p.x <= mx.x + .3 and p.y >= mn.y - .3 and p.y <= mx.y + .3
                and p.z >= mn.z - .3 and p.z <= mx.z + .3 then
              -- a tile's ground or a far tile's spans hundreds of metres: name it, but say its size
              local size = math.max(mx.x - mn.x, mx.y - mn.y)
              if size < 60 then
                out[#out + 1] = describe(o) .. string.format(' box %.0fm', size)
                if #out >= 8 then return end
              end
            end
          end
        end
      end
    end
  end
  look(scenetree.MissionGroup, 0)
  -- groups kept out of the MissionGroup (far tiles, horizon, cards)
  for _, name in ipairs(scenetree.findClassObjects('SimGroup')) do
    if name:match('^E2R[FHC]_') then look(scenetree.findObject(name), 1) end
  end
  return out
end

local function forestNear(p)
  local out = {}
  pcall(function()
    local f = scenetree.findClassObjects('Forest')
    for _, name in ipairs(f) do
      local forest = scenetree.findObject(name)
      local data = forest and forest:getData()
      if data then
        local box = Box3F()
        box.minExtents = vec3(p.x - 1.5, p.y - 1.5, p.z - 3)
        box.maxExtents = vec3(p.x + 1.5, p.y + 1.5, p.z + 3)
        for _, item in ipairs(data:getItemsBox(box) or {}) do
          local d = item:getData()
          local dn = d and d:getName() or '?'
          local col = d and tostring(d:getField('collidable', 0)) or '?'
          local shape = d and tostring(d:getField('shapeFile', 0)):match('([^/]+)$') or '?'
          out[#out + 1] = string.format('%s collidable=%s %s', dn, col, shape)
          if #out >= 6 then return end
        end
      end
    end
  end)
  return out
end

local function terrainAt(p)
  local tb = scenetree.findObject('e2rTurf')
  if not tb then return 'no turf block' end
  local ok, h = pcall(function() return core_terrain.getTerrainHeight(vec3(p.x, p.y, p.z)) end)
  if ok and h then return string.format('turf %.2f (point %.2f)', h, p.z) end
  return 'turf ?'
end

local function cast(pass)
  local stops = {}
  for _, r in ipairs(ring) do
    for k = 0, (r == 0 and 0 or 7) do
      local ox = at.x + r * math.cos(k * math.pi / 4)
      local oy = at.y + r * math.sin(k * math.pi / 4)
      local g = groundAt(ox, oy, at.z)
      if g then
        for _, h in ipairs(heights) do
          for d = 0, dirs - 1 do
            local a = d * 2 * math.pi / dirs
            local dir = vec3(math.cos(a), math.sin(a), 0)
            local from = vec3(ox, oy, g + h)
            local dist = castRayStatic(from, dir, reach)
            if dist and dist < reach - .05 then
              local hx, hy = ox + dir.x * dist, oy + dir.y * dist
              local before = groundAt(ox + dir.x * math.max(0, dist - .3), oy + dir.y * math.max(0, dist - .3), g + h)
              if before and g + h - before >= stands then
                local key = string.format('%.0f,%.0f,%.1f', hx * 2, hy * 2, h)
                if not stops[key] then
                  local pt = vec3(hx, hy, g + h)
                  -- the drawn world on the same segment
                  local okR, hit = pcall(Engine.castRay, from, vec3(ox + dir.x * (dist + near), oy + dir.y * (dist + near), g + h), true, false)
                  local drawn = okR and type(hit) == 'table' and hit.pt and math.abs(hit.dist or ((hit.pt - from):length())) - dist < near
                  local seen = ''
                  if okR and type(hit) == 'table' and hit.pt then
                    seen = string.format('%.2f m: %s', (hit.pt - from):length(), hit.obj and describe(hit.obj) or 'terrain/none')
                  end
                  stops[key] = {x = hx, y = hy, z = g + h, over = g + h - before, dist = dist, h = h, drawn = drawn and true or false,
                    seen = seen, from = string.format('%.1f,%.1f', ox - at.x, oy - at.y)}
                end
              end
            end
          end
        end
      end
    end
  end
  return stops
end

local R = {car = string.format('%.1f, %.1f, %.1f', at.x, at.y, at.z)}
local first = cast(1)
local frame = 0
return P.task(function()
  frame = frame + 1
  if frame == 1 then
    -- the world's own rebuild, now (world.lua updateCollision: a removed piece asks for one)
    local S = W and W.dbg and W.dbg().S
    if S then S.removedCollision, S.collisionDirty, S.collisionAt = true, true, -1e9 end
    return
  end
  if frame < 90 then return end
  local second = cast(2)
  local invisible, visible, stale = {}, 0, 0
  for key, s in pairs(first) do
    if s.drawn then visible = visible + 1
    else
      local still = second[key] ~= nil
      if not still then stale = stale + 1 end
      if #invisible < 24 then
        invisible[#invisible + 1] = {
          at = string.format('%.2f, %.2f, %.2f (+%.2f over the ground, %.1f m from the car at %s, ray at %.2f)', s.x, s.y, s.z, s.over, s.dist, s.from, s.h),
          afterRebuild = still and 'stays' or 'gone',
          drawnRay = s.seen,
          boxes = boxed(vec3(s.x, s.y, s.z)),
          forest = forestNear(vec3(s.x, s.y, s.z)),
          terrain = terrainAt(vec3(s.x, s.y, s.z))}
      end
    end
  end
  local newOnes = 0
  for key in pairs(second) do if not first[key] then newOnes = newOnes + 1 end end
  local n = 0
  for _ in pairs(first) do n = n + 1 end
  R.stops, R.drawnStops, R.staleStops, R.newAfterRebuild = n, visible, stale, newOnes
  R.invisible = invisible
  return R
end)
