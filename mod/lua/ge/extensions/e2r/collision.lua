-- What joins the static collision. be:reloadCollision rebuilds it from every ProceduralMesh in
-- the scene, whatever its group, flags or material (~0.27 ms per 1000 triangles: central Kyiv
-- 116-145 ms, plus 20-30 ms of physics the next frame). A hidden object is left out, and stays
-- out once shown again until the next rebuild (night 18.10 collision probe), so each rebuild
-- hides, for its duration only, what the car cannot touch.
--
-- The ground and the building shells the car can actually meet are separate invisible meshes
-- (generator col_ground / col_bldg): the ground is the same lattice the ground is drawn with,
-- the shell is one quad per wall instead of the windowed facade. A rebuild keeps the proxy
-- cells in the 3x3 around the car (and the other focus points) and leaves the detailed
-- ground and facade walls out. Roads stay the meshes they are drawn with.
--   - the horizon, and far tiles out of the car's reach (Kyiv: 145 -> 67 ms);
--   - near tiles out of that reach too: they are rebuilt with collision as the car comes;
--   - markings and edge decals (mm to cm over the road and verge), roofs, and the scene's ground covers: areas and paths
--     are drapes 2.5-4 cm over the ground mesh, which collides. The road layer's ground
--     takes those same cover materials where a cover fills a cell, so they stay solid there;
--   - railway tracks (generator.lua RAIL): flush on a carriageway, 20 cm over the ground beside it.
-- Hiding and showing ~1000 meshes costs ~1.5 ms; rendering does not see it (one Lua call).
local M = {}

local QUIET = {road = {}, scene = {}}
for _, kind in ipairs({'mark', 'mark_yellow', 'edge_grass', 'edge_dirt', 'manhole', 'drain', 'patch'}) do
  QUIET.road['e2rf_' .. kind], QUIET.scene['e2rf_' .. kind] = true, true
end
-- the land coming into another in a piece of open ground (generator.lua VEG.land): it lies in
-- the ground's own triangles, and the land under it (cut_*) is the one that collides
-- (levels: generator.lua VEG.land.levels, fast_style.LAND_LEVELS)
for _, land in ipairs({'dry', 'lush', 'earth'}) do
  for level = 1, 6 do
    QUIET.road['e2rf_fade_' .. land .. level], QUIET.scene['e2rf_fade_' .. land .. level] = true, true
  end
end
for _, kind in ipairs({'roof', 'roof_tile', 'roof_metal', 'roof_sheet', 'roof_mtile_red', 'roof_mtile_brown',
    'win_pvc', 'win_wood', 'door_house', 'door_garage', 'door_rust', 'chimney', 'pipe', 'ac_unit', 'dish', 'plate', 'glyphs', 'glyphs_dark', 'sign_white', 'lens_dark', 'lens_red', 'lens_yellow', 'lens_green', 'paint_red', 'fascia',
    'roof_mtile_green', 'footway', 'footway_asphalt', 'trodden', 'ground', 'grass_dry', 'grass_lush', 'earth',
    'paved', 'water', 'glacier', 'bare_rock', 'scree', 'beach', 'wetland', 'orchard', 'vineyard', 'farmland',
    'meadow', 'heath', 'scrub', 'forest', 'park', 'bare_ground', 'ballast', 'track', 'rail', 'rail_side'}) do
  QUIET.scene['e2rf_' .. kind] = true
end
M.QUIET = QUIET
-- the detailed ground the road layer draws. The coarse proxy (e2rf_col_ground) collides instead,
-- so these stay out of the rebuild. Roads, kerbs and sidewalks are not in this set.
local TERRAIN = {}
for _, kind in ipairs({'ground', 'meadow', 'grass', 'grass_dry', 'grass_lush', 'earth', 'park', 'forest',
    'farmland', 'orchard', 'vineyard', 'heath', 'scrub', 'wetland', 'bare_ground', 'beach', 'bare_rock',
    'scree', 'sand', 'desert', 'dune', 'steppe', 'dry_grass', 'tundra', 'alpine', 'snow', 'snow_edge'}) do
  TERRAIN['e2rf_' .. kind] = true
end

-- true when no mesh of a near object ('road' or 'scene' layer) needs collision
function M.quiet(meshes, layer)
  local set = QUIET[layer]
  if not set or not meshes or #meshes == 0 then return false end
  for _, mesh in ipairs(meshes) do
    local name = mesh.material or ''
    -- the proxies are the collision; a facade wall (e2rf_wall_*) is drawn, the shell collides
    if name == 'e2rf_col_ground' or name == 'e2rf_col_bldg' then return false end
    local skip = set[name]
      or (layer == 'road' and (TERRAIN[name] or name:sub(1, 9) == 'e2rf_cut_'))
      or (layer == 'scene' and name:sub(1, 10) == 'e2rf_wall_')
    if not skip then return false end
  end
  return true
end

-- a proxy cell {ix, iy, size} is kept when a focus point lies in its 3x3
function M.nearCell(cell, points)
  if not cell then return false end
  if not points or #points == 0 then return true end
  local size = cell[3] or 64
  if size < 1 then size = 64 end
  for _, q in ipairs(points) do
    local cx, cy = math.floor(q[1] / size), math.floor(q[2] / size)
    if math.abs(cx - cell[1]) <= 1 and math.abs(cy - cell[2]) <= 1 then return true end
  end
  return false
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
  -- cell: {ix, iy, size} of an invisible proxy mesh (kept only in the 3x3 round the car)
  function self:track(owner, id, quiet, triangles, layer, cell)
    if cell then
      local list = owner.proxyIds
      if not list then list = {}; owner.proxyIds = list end
      list[#list + 1] = id
      local cells = owner.proxyCell
      if not cells then cells = {}; owner.proxyCell = cells end
      cells[id] = cell
      self.owners[owner] = true
      return
    end
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
    local hidden, opened, solid, scenes, kept = {}, {}, 0, 0, {}
    for owner in pairs(self.owners) do
      if owner.proxyIds then
        local cells, n, k = owner.proxyCell, #owner.proxyIds, 1
        while k <= n do
          local id = owner.proxyIds[k]
          local obj = find(id)
          if obj then
            if M.nearCell(cells and cells[id], points) then
              if obj:isHidden() then obj:setHidden(false); opened[#opened + 1] = obj end
            elseif not obj:isHidden() then
              obj:setHidden(true)
            end
            k = k + 1
          else
            owner.proxyIds[k] = owner.proxyIds[n]
            owner.proxyIds[n] = nil
            if cells then cells[id] = nil end
            n = n - 1
          end
        end
      end
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
      live = live + #(owner.proxyIds or {})
      if owner.dropped and live == 0 then self.owners[owner] = nil end
    end
    local ok, err = pcall(reload)
    for k = 1, #opened do opened[k]:setHidden(true) end
    for k = 1, #hidden do hidden[k]:setHidden(false) end
    self.lastHidden, self.lastSolid, self.lastScenes, self.lastKept = #hidden, solid, scenes, kept
    if not ok then error(err, 0) end
    return #hidden
  end

  return self
end

return M
