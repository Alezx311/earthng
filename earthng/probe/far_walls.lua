-- What of the far tiles round the car a car would meet (24.11: a far tile is met as its ground
-- and roads; before, its trees' cards, the boxes of its buildings and its fences were walls, the
-- cards' clear parts walls nobody saw). A session of test_world.py --manual --probe:
--   python earthng/probe.py --user <out>/user --wait-landed --timeout 400 -f earthng/probe/far_walls.lua
-- A car that stands has its near tiles round it and no far tile within the collision's reach, so
-- the probe rebuilds the collision itself with everything in sight (be:reloadCollision, nothing
-- hidden: each object joins by its own collision type, as it would in a rebuild that takes its
-- tile) and then looks at the `tiles` nearest far tiles. The world's next rebuild puts its own
-- back; end the session after the probe. Returns:
--   objects: the far tiles' objects by shape class and collision type;
--   rays, hits: level rays through each tile `over` m above the ground under their start, both
--     ways along x and y, `step` m apart, and how many stopped at something that stands at least
--     `stands` m over the ground before it (a card, a box, a fence; not a slope);
--   where: the first hits, "x,y +m over the ground".
local tiles, over, step, stands = 8, 1.0, 10, .6
local veh = getPlayerVehicle(0)
local at = veh and veh:getPosition() or core_camera.getPosition()
local R = {at = {math.floor(at.x), math.floor(at.y), math.floor(at.z)}, tiles = {}, objects = {}, rays = 0, hits = 0, noGround = 0, where = {}}

local function groundAt(x, y, z)
  local d = castRayStatic(vec3(x, y, z + 80), vec3(0, 0, -1), 240)
  return d and d < 240 and (z + 80 - d) or nil
end

local dirs = {vec3(1, 0, 0), vec3(-1, 0, 0), vec3(0, 1, 0), vec3(0, -1, 0)}
local function sweep(i, j)
  local x0, y0 = i * 500, j * 500
  for k = step / 2, 500, step do
    for d = 1, 4 do
      local dir = dirs[d]
      local sx = d == 1 and x0 + 1 or d == 2 and x0 + 499 or x0 + k
      local sy = d == 3 and y0 + 1 or d == 4 and y0 + 499 or y0 + k
      -- along the ray in pieces: after a hit the ray goes on from behind it
      local done = 0
      while done < 497 do
        local px, py = sx + dir.x * done, sy + dir.y * done
        local g = groundAt(px, py, at.z)
        if not g then R.noGround = R.noGround + 1; break end
        local z = g + over
        local left = 498 - done
        local dist = castRayStatic(vec3(px, py, z), dir, left)
        R.rays = R.rays + 1
        if not dist or dist >= left - 1 then break end
        local before = groundAt(px + dir.x * math.max(0, dist - .5), py + dir.y * math.max(0, dist - .5), at.z)
        if before and z - before >= stands then
          R.hits = R.hits + 1
          if #R.where < 16 then
            R.where[#R.where + 1] = string.format('%.0f,%.0f +%.1f', px + dir.x * dist, py + dir.y * dist, z - before)
          end
        end
        done = done + dist + 2
      end
    end
  end
end

-- the far tiles, nearest first, and what they are made of
local far = {}
for _, name in ipairs(scenetree.findClassObjects('SimGroup')) do
  local i, j = name:match('^E2RF_(-?%d+)_(-?%d+)$')
  if i then
    i, j = tonumber(i), tonumber(j)
    local dx = math.max(i * 500 - at.x, 0, at.x - (i * 500 + 500))
    local dy = math.max(j * 500 - at.y, 0, at.y - (j * 500 + 500))
    far[#far + 1] = {i, j, math.sqrt(dx * dx + dy * dy)}
  end
  if name:sub(1, 5) == 'E2RF_' or name:sub(1, 5) == 'E2RC_' then
    local g = scenetree.findObject(name)
    for n = 0, g:getCount() - 1 do
      local raw = g:getObject(n)
      local obj = raw and scenetree.findObjectById(raw:getID())
      if obj then
        local kind = obj:getClassName()
        if kind == 'TSStatic' then
          local file = tostring(obj:getField('shapeName', 0)):match('([^/]+)%.cdae$') or 'shape'
          kind = (file:gsub('^.-_far_', ''):gsub('%d+$', '')) .. ':' .. tostring(obj:getField('collisionType', 0))
        end
        R.objects[kind] = (R.objects[kind] or 0) + 1
      end
    end
  end
end
table.sort(far, function(a, b) return a[3] < b[3] end)
R.far = #far

local frame, at_tile = 0, 0
return P.task(function()
  frame = frame + 1
  if frame == 1 then
    local t = hptimer()
    be:reloadCollision()
    R.reloadMs = math.floor(t:stop())
    return
  end
  if frame < 30 then return end
  at_tile = at_tile + 1
  local tile = far[at_tile]
  if not tile or at_tile > tiles then return R end
  local before = R.hits
  sweep(tile[1], tile[2])
  R.tiles[#R.tiles + 1] = string.format('%d_%d %.0f m: %d', tile[1], tile[2], tile[3], R.hits - before)
end)
