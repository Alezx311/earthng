-- What joins the static collision. be:reloadCollision rebuilds it from every ProceduralMesh in
-- the scene, whatever its group, flags or material (~0.27 ms per 1000 triangles: central Kyiv
-- 116-145 ms, plus 20-30 ms of physics the next frame). A hidden object is left out, and stays
-- out once shown again until the next rebuild (night 18.10 collision probe), so each rebuild
-- hides, for its duration only, what the car cannot touch:
--   - the horizon, and far tiles out of the car's reach (Kyiv: 145 -> 67 ms);
--   - near tiles out of that reach too: they are rebuilt with collision as the car comes;
--   - markings (8 mm over the road), roofs, and the scene's ground covers: areas and paths
--     are drapes 2.5-4 cm over the ground mesh, which collides. The road layer's ground
--     takes those same cover materials where a cover fills a cell, so they stay solid there.
-- Hiding and showing ~1000 meshes costs ~1.5 ms; rendering does not see it (one Lua call).
local M = {}

local QUIET = {road = {}, scene = {}}
for _, kind in ipairs({'mark', 'mark_yellow'}) do
  QUIET.road['e2rf_' .. kind], QUIET.scene['e2rf_' .. kind] = true, true
end
for _, kind in ipairs({'roof', 'roof_tile', 'roof_metal', 'footway', 'footway_asphalt', 'trodden', 'ground',
    'paved', 'water', 'glacier', 'bare_rock', 'scree', 'beach', 'wetland', 'orchard', 'vineyard', 'farmland',
    'meadow', 'heath', 'scrub', 'forest', 'park', 'bare_ground'}) do
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
  if owner.dropped or owner.horizon then return false end
  return #points == 0 or M.within(owner, points, size, 4)
end

function M.new()
  local self = {owners = {}, lastHidden = 0, lastSolid = 0}

  -- owner: a near tile {i, j}, a far tile {i, j, far = true} or a horizon block {horizon = true};
  -- dropped owners (owner.dropped) are graves until the engine has deleted their objects
  function self:track(owner, id, quiet)
    local key = quiet and 'quietIds' or 'solidIds'
    local list = owner[key]
    if not list then list = {}; owner[key] = list end
    list[#list + 1] = id
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
    local hidden, solid = {}, 0
    for owner in pairs(self.owners) do
      local live = hide(owner.quietIds, find, hidden)
      if M.solid(owner, points, size) then
        solid = solid + 1
        live = live + #(owner.solidIds or {})
      else
        live = live + hide(owner.solidIds, find, hidden)
      end
      if owner.dropped and live == 0 then self.owners[owner] = nil end
    end
    local ok, err = pcall(reload)
    for k = 1, #hidden do hidden[k]:setHidden(false) end
    self.lastHidden, self.lastSolid = #hidden, solid
    if not ok then error(err, 0) end
    return #hidden
  end

  return self
end

return M
