-- TSStatic capacity: how creating, standing, moving, hiding and deleting cost as the number of
-- static models in the scene grows (one stock shape, no collision, placed round the car).
-- Run after common.lua: python earthng/probe.py --user <user> -f research/native-bridge/capacity/static.lua --timeout 900
local LEVELS = _G.__capLevels or {2000, 10000, 30000, 60000, 100000}
local CHUNK, RADIUS, MOVE, HIDE = 2000, 600, 2000, 2000
local SHAPE = assert(CAP.ROCK, 'no stock rock shape')
local cx, cy, cz = CAP.origin()
local out = {shape = SHAPE, radius = RADIUS, levels = {}, origin = {cx, cy, cz}}
local group = createObject('SimGroup'); group:registerObject('e2rcap_static'); group.canSave = false
local objs, place = {}, {}
local timer = hptimer()

local function pos(k)
  local a, r = k * 2.399963, 8 + RADIUS * math.sqrt(k / LEVELS[#LEVELS])
  return cx + r * math.cos(a), cy + r * math.sin(a), cz
end

local function create(k)
  local o = createObject('TSStatic')
  o:setField('shapeName', 0, SHAPE)
  o:setField('collisionType', 0, 'None')
  o:setField('decalType', 0, 'None')
  o.canSave = false
  local x, y, z = pos(k)
  o:setPosRot(x, y, z, 0, 0, 0, 1)
  o:registerObject('')
  group:addObject(o)
  objs[k] = o
  place[k] = {x, y, z}
end

local steps = {CAP.waitQuiet(90, 60), CAP.measure(out, 'base', 180, 30)}

-- the first model of a shape pays for loading it
steps[#steps + 1] = function()
  timer:stopAndReset(); create(1); out.firstUs = timer:stop() * 1000
  return true
end

for li, level in ipairs(LEVELS) do
  local L = {level = level}
  out.levels[li] = L
  -- grow to the level, CHUNK a frame; the last chunk is the cost at this scene size
  steps[#steps + 1] = function()
    if out.stopped then return true end
    CAP.phase('grow-' .. level)
    local from = #objs + 1
    local to = math.min(level, from + CHUNK - 1)
    timer:stopAndReset()
    for k = from, to do create(k) end
    local ms = timer:stop()
    L.createUs = ms * 1000 / math.max(1, to - from + 1)
    L.createChunkMs = ms
    if ms > 2000 then out.stopped = 'create chunk ' .. ms .. ' ms at ' .. to end
    return #objs >= level
  end
  local key = 'stand-' .. level
  steps[#steps + 1] = CAP.measure(out, key, 150, 60, nil, function() return {count = #objs} end)
  -- move MOVE of them every frame (a crowd or traffic of static shapes)
  local moveMs, moveN, t = 0, 0, 0
  steps[#steps + 1] = CAP.measure(out, 'move' .. MOVE .. '-' .. level, 90, 20, function(dt, measured)
    t = t + dt
    local s = timer
    s:stopAndReset()
    local n = math.min(MOVE, #objs)
    for k = 1, n do
      local p = place[k]
      local a = t * 0.5 + k
      objs[k]:setPosRot(p[1] + math.cos(a), p[2] + math.sin(a), p[3], 0, 0, math.sin(a / 2), math.cos(a / 2))
    end
    if measured then moveMs = moveMs + s:stop(); moveN = moveN + n end
  end, function() return {moveUs = moveMs * 1000 / math.max(1, moveN)} end)
  -- hide and show the same MOVE every other frame (a pose swap)
  local hideMs, hideN, flip = 0, 0, false
  steps[#steps + 1] = CAP.measure(out, 'hide' .. HIDE .. '-' .. level, 60, 10, function(_, measured)
    flip = not flip
    timer:stopAndReset()
    local n = math.min(HIDE, #objs)
    for k = 1, n do objs[k]:setHidden(flip) end
    if measured then hideMs = hideMs + timer:stop(); hideN = hideN + n end
  end, function()
    for k = 1, math.min(HIDE, #objs) do objs[k]:setHidden(false) end
    return {hideUs = hideMs * 1000 / math.max(1, hideN)}
  end)
  -- at 10k: every model moves every frame
  if level == 10000 then
    local allMs, allN, ta = 0, 0, 0
    steps[#steps + 1] = CAP.measure(out, 'moveall-' .. level, 60, 10, function(dt, measured)
      ta = ta + dt
      timer:stopAndReset()
      for k = 1, #objs do
        local p = place[k]
        local a = ta * 0.5 + k
        objs[k]:setPosRot(p[1] + math.cos(a), p[2] + math.sin(a), p[3], 0, 0, 0, 1)
      end
      if measured then allMs = allMs + timer:stop(); allN = allN + #objs end
    end, function() return {moveUs = allMs * 1000 / math.max(1, allN)} end)
  end
end

-- delete, CHUNK a frame
local deleted, delMs = 0, 0
steps[#steps + 1] = function()
  CAP.phase('delete')
  timer:stopAndReset()
  local n = 0
  for k = #objs, math.max(1, #objs - CHUNK + 1), -1 do objs[k]:delete(); objs[k] = nil; n = n + 1 end
  delMs = delMs + timer:stop(); deleted = deleted + n
  if #objs == 0 then out.deleteUs = delMs * 1000 / math.max(1, deleted); group:delete(); return true end
end
steps[#steps + 1] = CAP.measure(out, 'after', 180, 60)
return CAP.run(steps, out)
