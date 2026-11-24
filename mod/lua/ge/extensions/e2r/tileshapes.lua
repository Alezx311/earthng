-- A layer's ProceduralMesh items packed into compiled shapes (cdae.lua): the drawn geometry of a
-- tile as a few TSStatic instead of ~140 ProceduralMesh. Runs where the tile is built (a worker
-- VM); the game thread only loads the files.
--
-- A mesh goes into a shape of its collision class, as collision.lua sorts ProceduralMesh:
--   solid: what the car can meet (roads, kerbs, the scene's walls, a far tile's ground and roads). A TSStatic
--     with collisionType 'Visible Mesh Final', tracked by collision.lua like the meshes it replaces.
--   quiet: drawn only (markings, covers, the detailed ground over its proxy). collisionType 'None',
--     so a rebuild never has to hide it.
-- A class is cut into files of MATERIALS materials each. The engine takes a new shape file in one
-- frame, ~12 ms and ~1.3 ms for each material in it whatever its triangles (research/fast-tiles,
-- p4): a town scene's hundred materials in one file held a frame for 110-230 ms (23.11, the first
-- drive with the pool), twelve at a time hold one ~28 ms.
-- A horizon block is never met by a car: it is quiet whole. A far tile's tree cards and a layer's
-- decor are shapes of their own, with the item's mark (world.lua keeps each in its own group: the
-- cards outlive the far ground until the near tile's crowns are planted).
-- Left as they are: the invisible collision proxies of a near tile (each its own cell, shown only
-- for a rebuild round the car) and a mesh something addresses by itself (a traffic light's lens).
local M = {}
local cdae = require('ge/extensions/e2r/cdae')
local collision = require('ge/extensions/e2r/collision')

M.MATERIALS = 12

-- file(name) -> the path the shape `name` (solid, solid2, quiet, ...) is written to
-- write(path, bytes) puts the bytes there
-- Replaces the packed items of the layer by 'shape' items. Returns what was packed: {shapes,
-- triangles, objects (the ProceduralMesh the shapes stand for), bytes, left (meshes kept)}.
function M.pack(manifest, layer, file, write, pause)
  local items = manifest and manifest.items
  if type(items) ~= 'table' then return nil end
  local distant = layer == 'far' or layer == 'horizon'
  local classes, shapes, kept = {}, {}, {}
  local stats = {shapes = 0, triangles = 0, objects = 0, bytes = 0, left = 0}
  local origin
  -- the shape a material of a class is in: the class's materials in the order they are met,
  -- MATERIALS to a file
  local function shapeOf(class, variant, material)
    local group = variant == '' and class or (class .. '_' .. variant)
    local c = classes[group]
    if not c then
      c = {of = {}, count = 0}
      classes[group] = c
    end
    local b = c.of[material]
    if not b then
      local part = math.floor(c.count / M.MATERIALS) + 1
      c.count = c.count + 1
      local name = part == 1 and group or (group .. part)
      b = shapes[name]
      if not b then
        b = {name = name, class = class, variant = variant, shape = cdae.builder(), mats = {}, triangles = 0}
        shapes[name] = b
        shapes[#shapes + 1] = b
      end
      b.mats[#b.mats + 1] = material
      c.of[material] = b
    end
    return b
  end
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
      -- (a far tile: its ground and roads are met, its cards and what stands on it are drawn)
      local class = (layer == 'horizon' or (distant and collision.drawn(it, meshes)) or (not distant and not it.forceCollision
        and collision.quiet(meshes, it.layer or layer))) and 'quiet' or 'solid'
      local variant = it.cards and 'cards' or (it.decor and 'decor' or '')
      origin = origin or it.pos
      local dx, dy, dz = it.pos[1] - origin[1], it.pos[2] - origin[2], (it.pos[3] or 0) - (origin[3] or 0)
      for k = 1, #meshes do
        local mesh = meshes[k]
        local b = shapeOf(class, variant, mesh.material or '')
        b.triangles = b.triangles + b.shape:add(class, mesh, dx, dy, dz, pause)
      end
      stats.objects = stats.objects + 1
      if pause then pause() end
    end
  end
  for _, b in ipairs(shapes) do
    local bytes = b.shape:encode(2, pause)
    if bytes then
      local path = file(b.name)
      write(path, bytes)
      kept[#kept + 1] = {kind = 'shape', name = 'e2rs_' .. (manifest.key or '') .. '_' .. layer .. '_' .. b.name,
        file = path, pos = origin, solid = b.class == 'solid', triangles = b.triangles, mats = b.mats, layer = layer,
        cards = b.variant == 'cards' or nil, decor = b.variant == 'decor' or nil}
      stats.shapes, stats.triangles, stats.bytes = stats.shapes + 1, stats.triangles + b.triangles, stats.bytes + #bytes
    end
    if pause then pause() end
  end
  manifest.items = kept
  return stats
end

return M
