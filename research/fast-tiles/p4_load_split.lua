-- Fast tiles, probe 4: what the frames around a new shape are made of. For each step the engine's
-- own split (Lua, Ticking, Render, shadows, ...) of the frame the shape is made in and the four
-- after it, against the mean of the 30 quiet frames before. Only parts that moved by 0.7 ms show.
local veh = getPlayerVehicle(0)
local at = veh:getPosition()
local R = {order = {}}
local made = {}
local slot = 0
local function shape(file, hidden)
  slot = slot + 1
  local t = hptimer()
  local obj = createObject('TSStatic')
  obj:setField('shapeName', 0, file)
  obj:setField('collisionType', 0, 'None')
  obj:setField('decalType', 0, 'None')
  obj.canSave = false
  local a = t:stopAndReset()
  obj:registerObject('')
  local b = t:stopAndReset()
  obj:setPosRot(at.x + 60 + slot * 4, at.y + 60, at.z + 30, 0, 0, 0, 1)
  if hidden then obj:setHidden(true) end
  made[#made + 1] = obj
  return {fields = math.floor(a * 100) / 100, register = math.floor(b * 100) / 100, place = math.floor(t:stop() * 100) / 100}
end
local steps = P4_STEPS or {
  {'tiny_c', function() return shape('/e2r_tiles/p4/tiny_c.cdae') end},
  {'tiny_deep', function() return shape('/e2r_tiles/p4/a/b/tiny_d.cdae') end},
  {'tiny_hidden', function() return shape('/e2r_tiles/p4/tiny_e.cdae', true) end},
  {'show_hidden', function() made[#made]:setHidden(false); return {} end},
  {'tiny_cached', function() return shape('/e2r_tiles/p4/tiny_c.cdae') end},
  {'m20', function() return shape('/e2r_tiles/p4/m20.cdae') end},
  {'m20_again_new_file', function() return shape('/e2r_tiles/p4/m20_b.cdae') end},
  {'m5', function() return shape('/e2r_tiles/p4/m5.cdae') end},
  {'big_200k', function() return shape('/e2r_tiles/p4/big.cdae') end},
}
local m, base, baseN = {}, {}, 0
local phase, frame, current, rows = 0, 0, nil, nil
local function snapshot(ms)
  Engine.Debug.getLastPerformanceMetrics(m)
  local row = {frame = ms}
  for k, v in pairs(m) do if type(v) == 'number' and v < 1e6 then row[k] = v end end
  return row
end
return P.task(function(dt, ms)
  frame = frame + 1
  local row = snapshot(ms)
  if phase == 0 then
    for k, v in pairs(row) do base[k] = (base[k] or 0) + v end
    baseN = baseN + 1
    if frame < 30 then return end
    for k, v in pairs(base) do base[k] = v / baseN end
    R.base = {frame = math.floor(base.frame * 10) / 10, Lua = base.Lua, Render = base.Render, RenderShadows = base.RenderShadows, Ticking = base.Ticking}
  elseif current then
    local out = {}
    for k, v in pairs(row) do
      local d = v - (base[k] or 0)
      if math.abs(d) >= 0.7 then out[k] = math.floor(d * 10 + .5) / 10 end
    end
    rows[#rows + 1] = out
    if #rows < 5 then return end
    current.frames = rows
  end
  if phase > 0 and frame < 12 then return end
  phase, frame = phase + 1, 0
  local step = steps[phase]
  if not step then
    for _, obj in ipairs(made) do obj:delete() end
    return R
  end
  local ok, value = pcall(step[2])
  current, rows = ok and value or {error = tostring(value)}, {}
  R[step[1]] = current
  R.order[#R.order + 1] = step[1]
end)
