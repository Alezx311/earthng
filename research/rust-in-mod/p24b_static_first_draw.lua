-- Knock-down research part 1b (after p24): is the first-draw cost of a debris TSStatic per shape or
-- per object? 10 new TSStatic of a shape already drawn as TSStatic (planterbox, p24), then 1 and 10
-- of a shape never drawn as a TSStatic (garbage_bin_a), then pooled ones hidden and shown again.
-- Frame times (ms) of the 15 frames after each step.
local K = _G.e2r_knock
local p = K.spots[25]
local R = {}
local function make(shape, n, dx)
  local list = {}
  for k = 1, n do
    local s = createObject('TSStatic')
    s:setField('shapeName', 0, shape)
    s:setField('collisionType', 0, 'None')
    s:setField('decalType', 0, 'None')
    s.useInstanceRenderData = true
    s:registerObject('')
    s:setPosRot(p.x + dx + k * .7, p.y + 2, p.z, 0, 0, 0, 1)
    list[k] = s
  end
  return list
end
local steps = {'planter10', 'bin1', 'bin10', 'hide', 'show'}
local phase, frame, frames, t = 0, 0, {}, hptimer()
local sets = {}
return P.task(function(dt, ms)
  frame = frame + 1
  if phase > 0 then frames[#frames + 1] = math.floor(ms * 10) / 10 end
  if frame == 15 then
    if phase > 0 then R[steps[phase]] = frames end
    frames, frame = {}, 0
    local name = steps[phase + 1]
    if not name then return R end
    t:stopAndReset()
    if name == 'planter10' then sets[1] = make('/levels/west_coast_usa/art/shapes/objects/planterbox.dae', 10, 0)
    elseif name == 'bin1' then sets[2] = make('/levels/west_coast_usa/art/shapes/objects/garbage_bin_a.dae', 1, 10)
    elseif name == 'bin10' then sets[3] = make('/levels/west_coast_usa/art/shapes/objects/garbage_bin_a.dae', 10, 12)
    elseif name == 'hide' then
      for _, s in ipairs(sets[3]) do s:setHidden(true) end
      for _, s in ipairs(sets[1]) do s:setHidden(true) end
    elseif name == 'show' then
      for _, s in ipairs(sets[3]) do s:setHidden(false) end
      for _, s in ipairs(sets[1]) do s:setHidden(false) end
    end
    R[name .. 'Ms'] = t:stop()
    phase = phase + 1
  end
end)
