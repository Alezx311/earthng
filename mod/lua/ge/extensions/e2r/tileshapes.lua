-- A layer's ProceduralMesh items packed into compiled shapes (cdae.lua): the drawn geometry of a
-- tile as one or two TSStatic instead of ~140 ProceduralMesh. Runs where the tile is built (a
-- worker VM); the game thread only loads the files.
--
-- An item goes into the shape of its collision class, as collision.lua sorts ProceduralMesh:
--   solid: what the car can meet (roads, kerbs, the scene's walls, a far tile's ground). A TSStatic
--     with collisionType 'Visible Mesh', tracked by collision.lua like the meshes it replaces.
--   quiet: drawn only (markings, covers, the detailed ground over its proxy). collisionType 'None',
--     so a rebuild never has to hide it.
-- Left as they are: the invisible collision proxies of a near tile (each its own cell, shown only
-- for a rebuild round the car) and a mesh something addresses by itself (a traffic light's lens).
local M = {}
local cdae = require('ge/extensions/e2r/cdae')
local collision = require('ge/extensions/e2r/collision')

-- file(class) -> the path the shape of that class is written to
-- write(path, bytes) puts the bytes there
-- Returns the items of the layer with the packed ones replaced by 'shape' items, and what was
-- packed: {shapes, triangles, objects (the ProceduralMesh the shapes stand for), bytes}.
function M.pack(manifest, layer, file, write, pause)
  local items = manifest and manifest.items
  if type(items) ~= 'table' then return nil end
  local distant = layer == 'far' or layer == 'horizon'
  local builders, order, kept = {}, {}, {}
  local stats = {shapes = 0, triangles = 0, objects = 0, bytes = 0, left = 0}
  local origin
  for _, it in ipairs(items) do
    local meshes = it.kind == 'proc' and it.meshes
    local lens = false
    if meshes then
      for k = 1, #meshes do if meshes[k].lens then lens = true end end
    end
    if not meshes or it.proxy or lens or it.lens or type(it.pos) ~= 'table' then
      kept[#kept + 1] = it
      if meshes then stats.left = stats.left + 1 end
    else
      local class = (not distant and not it.forceCollision and collision.quiet(meshes, it.layer or layer)) and 'quiet' or 'solid'
      local b = builders[class]
      if not b then
        b = {shape = cdae.builder(), mats = {}, seen = {}, triangles = 0}
        builders[class] = b
        order[#order + 1] = class
      end
      origin = origin or it.pos
      local dx, dy, dz = it.pos[1] - origin[1], it.pos[2] - origin[2], (it.pos[3] or 0) - (origin[3] or 0)
      for k = 1, #meshes do
        local mesh = meshes[k]
        b.triangles = b.triangles + b.shape:add(class, mesh, dx, dy, dz)
        local name = mesh.material or ''
        if not b.seen[name] then b.seen[name] = true; b.mats[#b.mats + 1] = name end
      end
      stats.objects = stats.objects + 1
      if pause then pause() end
    end
  end
  for _, class in ipairs(order) do
    local b = builders[class]
    local bytes = b.shape:encode(2, pause)
    if bytes then
      local path = file(class)
      write(path, bytes)
      kept[#kept + 1] = {kind = 'shape', name = 'e2rs_' .. (manifest.key or '') .. '_' .. layer .. '_' .. class,
        file = path, pos = origin, solid = class == 'solid', triangles = b.triangles, mats = b.mats, layer = layer}
      stats.shapes, stats.triangles, stats.bytes = stats.shapes + 1, stats.triangles + b.triangles, stats.bytes + #bytes
    end
    if pause then pause() end
  end
  manifest.items = kept
  return stats
end

return M
