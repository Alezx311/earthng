-- What joins the static collision. be:reloadCollision rebuilds it from every ProceduralMesh in
-- the scene, whatever its group, flags or material (~0.27 ms per 1000 triangles: central Kyiv
-- 116-145 ms, plus 20-30 ms of physics the next frame). A hidden object is left out, and stays
-- out once shown again until the next rebuild (night 18.10 collision probe), so each rebuild
-- hides, for its duration only, what the car cannot touch:
--   - the horizon, and far tiles out of the car's reach (Kyiv: 145 -> 67 ms);
--   - near tiles out of that reach too: they are rebuilt with collision as the car comes;
--   - gables, eave boards, balconies and canopies (gable) and roof rims and roof boxes (parapet): 1.9 m
--     (a porch lip) to roof height, on walls that stay solid; 6-10 % of a town tile's solid
--     triangles (earthng/generator_budget.py's synthetic cell);
--   - markings and edge decals (mm to cm over the road and verge), roofs, and the scene's ground covers: areas and paths
--     are drapes 2.5-4 cm over the ground mesh, which collides. The road layer's ground
--     takes those same cover materials where a cover fills a cell, so they stay solid there.
--   - a far tile under a near tile whose roads and ground are in (owner.covered, set by world.lua
--     before each rebuild): same key, same reach, so the near ground is solid wherever the far
--     one would be, and the far ground (coarser, > 5 cm over the near one in a quarter of the
--     cells) only doubled the triangles and could bump the wheels.
-- Hiding and showing ~1000 meshes costs ~1.5 ms; rendering does not see it (one Lua call).
-- What a rebuild keeps sets its time: lastTris and lastObjects count it (the cost figures above
-- put a town tile of ~40 solid meshes and ~20k triangles at 6-9 ms, ~8 such tiles at ~45 ms).
local M = {}

local QUIET = {road = {}, scene = {}}
for _, kind in ipairs({'mark', 'mark_yellow', 'edge_grass', 'edge_dirt', 'manhole', 'drain', 'patch'}) do
  QUIET.road['e2rf_' .. kind], QUIET.scene['e2rf_' .. kind] = true, true
end
for _, kind in ipairs({'roof', 'roof_tile', 'roof_metal', 'roof_sheet', 'roof_mtile_red', 'roof_mtile_brown',
    'win_pvc', 'win_wood', 'door_house', 'door_garage', 'door_rust', 'chimney', 'pipe', 'ac_unit', 'dish', 'plate', 'glyphs', 'paint_red', 'fascia',
    'roof_mtile_green', 'footway', 'footway_asphalt', 'trodden', 'ground',
    'paved', 'water', 'glacier', 'bare_rock', 'scree', 'beach', 'wetland', 'orchard', 'vineyard', 'farmland',
    'meadow', 'heath', 'scrub', 'forest', 'park', 'bare_ground', 'gable', 'parapet'}) do
  QUIET.scene['e2rf_' .. kind] = true
end
M.QUIET = QUIET

-- true when no mesh of a near object ('road' or 'scene' layer) needs collision
function M.quiet(meshes, layer)
  local set = QUIET[layer]
  if not set or not meshes or #meshes == 0 then return false end
  for _, mesh in ipairs(meshes) do
    if not set[mesh.material] then return false end
  end
  return true
end

-- distance from (x, y) to the owner's tile square; nil for owners without a tile
local function reach(owner, x, y, size)
  if not (owner.i and owner.j) then return nil end
  local x0, y0 = owner.i * size, owner.j * size
  local dx = math.max(x0 - x, 0, x - (x0 + size))
  local dy = math.max(y0 - y, 0, y - (y0 + size))
  return math.sqrt(dx * dx + dy * dy)
end

-- points: {x, y, want, keep} for the car or the camera, a parked car and every vehicle. A tile
-- without collision within `want` of one asks for a rebuild; a rebuild keeps the tiles within
-- `keep`, so the next one is due only after the car has covered keep - want.
function M.within(owner, points, size, slot)
  for _, q in ipairs(points) do
    local d = reach(owner, q[1], q[2], size)
    if d ~= nil and d <= q[slot] then return true end
  end
  return false
end

-- does the owner's collision stay in a rebuild (no points: every live tile's does)
function M.solid(owner, points, size)
  if owner.dropped or owner.horizon or owner.covered then return false end
  return #points == 0 or M.within(owner, points, size, 4)
end

function M.new()
  local self = {owners = {}, lastHidden = 0, lastSolid = 0, lastTris = 0, lastObjects = 0}

  -- owner: a near tile {i, j}, a far tile {i, j, far = true} or a horizon block {horizon = true};
  -- dropped owners (owner.dropped) are graves until the engine has deleted their objects;
  -- triangles: the object's count, summed per owner for the report
  function self:track(owner, id, quiet, triangles)
    local key = quiet and 'quietIds' or 'solidIds'
    local list = owner[key]
    if not list then list = {}; owner[key] = list end
    list[#list + 1] = id
    if not quiet then owner.solidTris = (owner.solidTris or 0) + (tonumber(triangles) or 0) end
    self.owners[owner] = true
  end

  local function hide(ids, find, hidden)
    if not ids then return 0 end
    local n, k, live = #ids, 1, 0
    while k <= n do
      local obj = find(ids[k])
      if obj then
        if not obj:isHidden() then obj:setHidden(true); hidden[#hidden + 1] = obj end
        live, k = live + 1, k + 1
      else
        ids[k] = ids[n]; ids[n] = nil; n = n - 1
      end
    end
    return live
  end

  -- find(id) -> object or nil; reload() runs the engine rebuild. Everything hidden here is
  -- shown again even when reload() fails, so a failed rebuild cannot blank the world.
  function self:rebuild(points, size, find, reload)
    local hidden, solid, tris, objects = {}, 0, 0, 0
    for owner in pairs(self.owners) do
      local live = hide(owner.quietIds, find, hidden)
      if M.solid(owner, points, size) then
        solid = solid + 1
        live = live + #(owner.solidIds or {})
        tris, objects = tris + (owner.solidTris or 0), objects + #(owner.solidIds or {})
      else
        live = live + hide(owner.solidIds, find, hidden)
      end
      if owner.dropped and live == 0 then self.owners[owner] = nil end
    end
    local ok, err = pcall(reload)
    for k = 1, #hidden do hidden[k]:setHidden(false) end
    self.lastHidden, self.lastSolid, self.lastTris, self.lastObjects = #hidden, solid, tris, objects
    if not ok then error(err, 0) end
    return #hidden
  end

  return self
end

return M
