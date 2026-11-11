-- Knock-down research (docs/KNOCKDOWN.md), part 1: can one Forest item leave the static collision
-- without be:reloadCollision, and what do removing it and putting a TSStatic in its place cost.
--   1. 40 planters (a collidable kind of our own) and 40 of a non-collidable kind on a straight road
--      edge near the player, one reloadCollision so the solid ones collide.
--   2. castRayStatic straight down onto every planter: the top of the planter or the road.
--   3. removeItem on 1 planter, then 19 in one frame; updateItem under the map on 10 more; the
--      rays again (still there = the collision outlives the item); frame times of the next frames.
--   4. a car dropped from 2.5 m onto a removed planter and onto a standing one: where it rests.
--   5. TSStatic debris: spawn cost of the first and of 50 more of the same shape, setPosRot, setHidden.
local SHAPE = '/levels/west_coast_usa/art/shapes/objects/planterbox.dae'
local up = vec3(0, 0, 1)
local R = {}
local f = scenetree.findObject('e2rForest')
if not f then return {error = 'no e2rForest'} end
local data = f:getData()

local function kind(name, collidable)
  local d = scenetree.findObject(name)
  if d then return d end
  d = worldEditorCppApi and worldEditorCppApi.createObject and worldEditorCppApi.createObject('ForestItemData') or createObject('ForestItemData')
  d:setField('shapeFile', 0, SHAPE)
  d:setField('collidable', 0, collidable and '1' or '0')
  d:setField('windScale', 0, '0')
  d:registerObject(name)
  pcall(function() scenetree.findObject('dataBlockGroup'):addObject(d) end)
  return d
end
local solid, soft = kind('e2rKnockProbeSolid', true), kind('e2rKnockProbeSoft', false)

-- a straight, flat edge of the game's road graph near the player
local player = be:getPlayerVehicle(0):getPosition()
local best, bestScore
for name, n in pairs(map.getMap().nodes) do
  if n.pos:distance(player) < 500 then
    for other in pairs(n.links or {}) do
      local m = map.getMap().nodes[other]
      if m then
        local len = n.pos:distance(m.pos)
        if len > 140 and math.abs(n.pos.z - m.pos.z) < 3 then
          local score = len - n.pos:distance(player) * .05
          if not bestScore or score > bestScore then best, bestScore = {n.pos, m.pos}, score end
        end
      end
    end
  end
end
if not best then return {error = 'no straight edge'} end
local a, b = best[1], best[2]
local len = vec3(b.x - a.x, b.y - a.y, 0):length()
local dir = vec3(b.x - a.x, b.y - a.y, 0):normalized()
local side = vec3(-dir.y, dir.x, 0)
local function ground(p)
  local z = be:getSurfaceHeightBelow(vec3(p.x, p.y, p.z + 4))
  return (z and z > -1e6) and z or p.z
end
local function at(s, off)
  local p = a + (b - a) * (s / len) + side * (off or 0)
  return vec3(p.x, p.y, ground(p))
end
R.edge = {len = len, ax = a.x, ay = a.y}

local items, softItems, spots = {}, {}, {}
local m = MatrixF(true)
local t = hptimer()
for k = 1, 40 do
  local p = at(10 + k * 3, 1.5)
  m:setPosition(p)
  items[k] = data:createNewItem(solid, m, 1)
  spots[k] = p
  local q = at(10 + k * 3, -4)
  m:setPosition(q)
  softItems[k] = data:createNewItem(soft, m, 1)
end
R.create80Ms = t:stopAndReset()
be:reloadCollision()
R.reloadMs = t:stopAndReset()

local function rays()
  local hit = {}
  for k = 1, 40 do
    local p = spots[k]
    local d = castRayStatic(p + up * 5, -up, 10)
    hit[k] = math.floor((5 - d) * 100) / 100   -- height of what the ray met over the road
  end
  return hit
end
R.raysBefore = rays()
_G.e2r_knock = {items = items, soft = softItems, spots = spots, data = data, solid = solid, soft = soft}

local frame, phase, frames = 0, 0, {}
local car
return P.task(function(dt, ms)
  frame = frame + 1
  if phase == 0 and frame > 30 then
    t:stopAndReset()
    data:removeItem(items[1])
    R.remove1Ms = t:stopAndReset()
    phase, frame = 1, 0
  elseif phase == 1 then
    frames[#frames + 1] = ms
    if frame == 20 then
      R.framesAfterRemove1 = frames; frames = {}
      t:stopAndReset()
      for k = 2, 20 do data:removeItem(items[k]) end
      R.remove19Ms = t:stopAndReset()
      for k = 21, 30 do
        local it = items[k]
        data:updateItem(it:getKey(), vec3(spots[k].x, spots[k].y, -999), it:getData(), it:getTransform(), it:getScale(), it:getUid())
      end
      R.update10Ms = t:stopAndReset()
      -- the soft kind too: a non-collidable kind's change
      t:stopAndReset()
      data:removeItem(softItems[1])
      R.removeSoft1Ms = t:stopAndReset()
      phase, frame = 2, 0
    end
  elseif phase == 2 then
    frames[#frames + 1] = ms
    if frame == 20 then
      R.framesAfterRemove29 = frames; frames = {}
      R.raysAfter = rays()
      -- drop a car on removed planter 5 and on standing planter 35
      local p5, p35 = spots[5], spots[35]
      car = {}
      for k, p in ipairs({p5, p35}) do
        local v = core_vehicles.spawnNewVehicle('covet', {pos = p + up * 2.5, rot = quatFromDir(side, up), autoEnterVehicle = false})
        car[k] = v:getID()
      end
      phase, frame = 3, 0
    end
  elseif phase == 3 and frame > 240 then
    R.dropRest = {}
    for k, id in ipairs(car) do
      local v = be:getObjectByID(id)
      local box = v:getSpawnWorldOOBB()
      local c, h = box:getCenter(), box:getHalfExtents()
      local p = k == 1 and spots[5] or spots[35]
      R.dropRest[k] = {centreOverRoad = math.floor((c.z - p.z) * 100) / 100, pos = {v:getPosition().x, v:getPosition().y}}
      v:delete()
    end
    -- TSStatic debris
    local objs = {}
    t:stopAndReset()
    local o = createObject('TSStatic')
    o:setField('shapeName', 0, SHAPE)
    o:setField('collisionType', 0, 'None')
    o:setField('decalType', 0, 'None')
    o.useInstanceRenderData = true
    o:registerObject('')
    o:setPosRot(spots[1].x, spots[1].y, spots[1].z, 0, 0, 0, 1)
    R.staticFirstUs = t:stopAndReset() * 1000
    objs[1] = o
    for k = 2, 51 do
      local s = createObject('TSStatic')
      s:setField('shapeName', 0, SHAPE)
      s:setField('collisionType', 0, 'None')
      s:setField('decalType', 0, 'None')
      s.useInstanceRenderData = true
      s:registerObject('')
      local p = spots[math.min(k, 20)]
      s:setPosRot(p.x + k * .01, p.y, p.z, 0, 0, 0, 1)
      objs[k] = s
    end
    R.static50Us = t:stopAndReset() * 1000 / 50
    for k = 1, 51 do objs[k]:setPosRot(spots[1].x, spots[1].y, spots[1].z + 1, 0, 0, .38, .92) end
    R.setPosRotUs = t:stopAndReset() * 1000 / 51
    for k = 1, 51 do objs[k]:setHidden(true) end
    for k = 1, 51 do objs[k]:setHidden(false) end
    R.setHiddenUs = t:stopAndReset() * 1000 / 102
    _G.e2r_knock.statics = objs
    phase, frame = 4, 0
  elseif phase == 4 then
    frames[#frames + 1] = ms
    if frame == 20 then
      R.framesAfterStatics = frames
      R.groundUs = (function()
        local tt = hptimer()
        for k = 1, 100 do be:getSurfaceHeightBelow(vec3(spots[1].x + k * .1, spots[1].y, spots[1].z + 3)) end
        return tt:stop() * 10
      end)()
      return R
    end
  end
end)
