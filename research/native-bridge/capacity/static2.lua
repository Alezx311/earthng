-- Why setPosRot / setHidden / delete grew with the models in the scene (static.lua: 2 us at 2k,
-- 33 us at 100k, plus the engine's Ticking): the SimGroup they sit in, or how densely they fill
-- the scene's spatial bins? 30k TSStatics in three layouts, each moved/hidden 2000 a frame:
--   one-600:   one SimGroup, disk of 600 m (as static.lua)
--   groups-600: SimGroups of 1000, disk of 600 m
--   one-3000:  one SimGroup, disk of 3000 m (25 times sparser)
local N, CHUNK, MOVE = 30000, 2000, 2000
local SHAPE = assert(CAP.ROCK)
local cx, cy, cz = CAP.origin()
local out = {n = N}
local timer = hptimer()
local layouts = {{'one-600', N, 600}, {'groups-600', 1000, 600}, {'one-3000', N, 3000}}
local steps = {CAP.waitQuiet(60, 30)}
for _, L in ipairs(layouts) do
  local name, per, radius = L[1], L[2], L[3]
  local objs, place, groups = {}, {}, {}
  local r = {}
  out[name] = r
  steps[#steps + 1] = function()
    CAP.phase('grow-' .. name)
    local from = #objs + 1
    local to = math.min(N, from + CHUNK - 1)
    timer:stopAndReset()
    for k = from, to do
      local gi = math.floor((k - 1) / per) + 1
      local g = groups[gi]
      if not g then
        g = createObject('SimGroup'); g:registerObject('e2rcap_s2_' .. name .. '_' .. gi); g.canSave = false
        groups[gi] = g
      end
      local a, d = k * 2.399963, 8 + radius * math.sqrt(k / N)
      local x, y = cx + d * math.cos(a), cy + d * math.sin(a)
      local o = createObject('TSStatic')
      o:setField('shapeName', 0, SHAPE)
      o:setField('collisionType', 0, 'None')
      o:setField('decalType', 0, 'None')
      o.canSave = false
      o:setPosRot(x, y, cz, 0, 0, 0, 1)
      o:registerObject('')
      g:addObject(o)
      objs[k], place[k] = o, {x, y, cz}
    end
    r.createUs = timer:stop() * 1000 / (to - from + 1)
    return #objs >= N
  end
  local moveMs, moveN, t = 0, 0, 0
  steps[#steps + 1] = CAP.measure(r, 'move', 60, 15, function(dt, measured)
    t = t + dt
    timer:stopAndReset()
    -- the moved ones spread over the whole disk, not the first ring
    for k = 1, MOVE do
      local i = (k * 15) % N + 1
      local p = place[i]
      local a = t + i
      objs[i]:setPosRot(p[1] + math.cos(a), p[2] + math.sin(a), p[3], 0, 0, 0, 1)
    end
    if measured then moveMs = moveMs + timer:stop(); moveN = moveN + MOVE end
  end, function() return {moveUs = moveMs * 1000 / math.max(1, moveN)} end)
  local hideMs, hideN, flip = 0, 0, false
  steps[#steps + 1] = CAP.measure(r, 'hide', 40, 10, function(_, measured)
    flip = not flip
    timer:stopAndReset()
    for k = 1, MOVE do objs[(k * 15) % N + 1]:setHidden(flip) end
    if measured then hideMs = hideMs + timer:stop(); hideN = hideN + MOVE end
  end, function()
    for k = 1, MOVE do objs[(k * 15) % N + 1]:setHidden(false) end
    return {hideUs = hideMs * 1000 / math.max(1, hideN)}
  end)
  local delMs, deleted = 0, 0
  steps[#steps + 1] = function()
    CAP.phase('delete-' .. name)
    timer:stopAndReset()
    local n = 0
    for k = #objs, math.max(1, #objs - CHUNK + 1), -1 do objs[k]:delete(); objs[k] = nil; n = n + 1 end
    delMs, deleted = delMs + timer:stop(), deleted + n
    if #objs == 0 then
      for _, g in ipairs(groups) do g:delete() end
      r.deleteUs = delMs * 1000 / deleted
      return true
    end
  end
  steps[#steps + 1] = CAP.measure(r, 'after', 30, 30)
end
return CAP.run(steps, out)
