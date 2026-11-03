-- What joins the static collision. be:reloadCollision rebuilds it from every ProceduralMesh in
-- the scene, whatever its group, flags or material (~0.27 ms per 1000 triangles: central Kyiv
-- 116-145 ms, plus 20-30 ms of physics the next frame). A hidden object is left out, and stays
-- out once shown again until the next rebuild (night 18.10 collision probe), so each rebuild
-- hides, for its duration only, what the car cannot touch:
--   - the horizon, and far tiles out of the car's reach (Kyiv: 145 -> 67 ms);
--   - near tiles out of that reach too: they are rebuilt with collision as the car comes;
--   - markings and edge decals (mm to cm over the road and verge), roofs, and the scene's ground covers: areas and paths
--     are drapes 2.5-4 cm over the ground mesh, which collides. The road layer's ground
--     takes those same cover materials where a cover fills a cell, so they stay solid there.
-- Hiding and showing ~1000 meshes costs ~1.5 ms; rendering does not see it (one Lua call).
local M = {}

local QUIET = {road = {}, scene = {}}
for _, kind in ipairs({'mark', 'mark_yellow', 'edge_grass', 'edge_dirt', 'manhole', 'drain', 'patch'}) do
  QUIET.road['e2rf_' .. kind], QUIET.scene['e2rf_' .. kind] = true, true
end
for _, kind in ipairs({'roof', 'roof_tile', 'roof_metal', 'roof_sheet', 'roof_mtile_red', 'roof_mtile_brown',
    'win_pvc', 'win_wood', 'door_house', 'door_garage', 'door_rust', 'chimney', 'pipe', 'ac_unit', 'dish', 'plate', 'glyphs', 'paint_red', 'fascia',
    'roof_mtile_green', 'footway', 'footway_asphalt', 'trodden', 'ground',
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

-- points: {x, y, want, keep, sceneWant, sceneKeep} for the car or the camera, a parked car and
-- every vehicle. A tile without collision within `want` of one asks for a rebuild; a rebuild keeps
-- the tiles within `keep`, so the next one is due only after the car has covered keep - want.
-- The solid scene of a near tile (walls, fences: tracked with layer 'scene') has its own pair, slots
-- 5 and 6 (keep when a point has none; below 0: none): at speed the car reaches buildings only on
-- its own tile and the next, and they were 2/3 of a city rebuild's triangles.
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

-- does the owner's solid scene stay as well
function M.sceneSolid(owner, points, size)
  if not M.solid(owner, points, size) then return false end
  if #points == 0 then return true end
  for _, q in ipairs(points) do
    local d = reach(owner, q[1], q[2], size)
    if d ~= nil and d <= (q[6] or q[4]) then return true end
  end
  return false
end

function M.new()
  local self = {owners = {}, lastHidden = 0, lastSolid = 0, lastScenes = 0}

  -- owner: a near tile {i, j}, a far tile {i, j, far = true} or a horizon block {horizon = true};
  -- dropped owners (owner.dropped) are graves until the engine has deleted their objects
  -- triangles, layer (optional): what a rebuild keeps, for the automation report (lastKept)
  function self:track(owner, id, quiet, triangles, layer)
    local key = quiet and 'quietIds' or (layer == 'scene' and 'sceneIds') or 'solidIds'
    local list = owner[key]
    if not list then list = {}; owner[key] = list end
    list[#list + 1] = id
    self.owners[owner] = true
    if not quiet and triangles then
      local kept = owner.solidTris or {}
      owner.solidTris = kept
      local slot = layer or (owner.horizon and 'horizon') or (owner.far and 'far') or 'other'
      kept[slot] = (kept[slot] or 0) + triangles
    end
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
    local hidden, solid, scenes, kept = {}, 0, 0, {}
    for owner in pairs(self.owners) do
      local live = hide(owner.quietIds, find, hidden)
      local tris = owner.solidTris or {}
      if M.solid(owner, points, size) then
        solid = solid + 1
        live = live + #(owner.solidIds or {})
        for slot, n in pairs(tris) do
          if slot ~= 'scene' then kept[slot] = (kept[slot] or 0) + n end
        end
      else
        live = live + hide(owner.solidIds, find, hidden)
      end
      if owner.sceneIds then
        if M.sceneSolid(owner, points, size) then
          scenes = scenes + 1
          live = live + #owner.sceneIds
          kept.scene = (kept.scene or 0) + (tris.scene or 0)
        else
          live = live + hide(owner.sceneIds, find, hidden)
        end
      end
      if owner.dropped and live == 0 then self.owners[owner] = nil end
    end
    local ok, err = pcall(reload)
    for k = 1, #hidden do hidden[k]:setHidden(false) end
    self.lastHidden, self.lastSolid, self.lastScenes, self.lastKept = #hidden, solid, scenes, kept
    if not ok then error(err, 0) end
    return #hidden
  end

  return self
end

return M
