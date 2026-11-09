-- p12: walkers as static (instanced) pose shapes. Each of N agents owns POSES TSStatics (the four flow car
-- bodies stand in for walk poses), one shown, the rest hidden; a pose swap is setHidden on two objects.
-- Crowd costs in the running game (earthng/probe.py -f, --timeout 300): phases of PHASE frames each,
-- frame ms from the probe's frame timer, engine split from Engine.Debug.getLastPerformanceMetrics.
--   base            nothing added
--   ped_anim        N skinned walkers (stock snowman, 'ambient' sequence) standing, animated
--   ped_anim_move   the same, each moved every frame (setPosRot)
--   ped_still_move  the same moved, animation off
--   scare_anim_move N stock scarecrows (bigger skinned shape) animated and moved
--   cars_move       C flow car shapes moved every frame
local N, C, PHASE = tonumber(_G.__crowdN or 300), tonumber(_G.__crowdC or 1000), tonumber(_G.__crowdPhase or 150)
local SNOW, SCARE = 'art/shapes/winter/snowman.dae', 'art/shapes/halloween/scarecrow.dae'
local CAR = '/levels/e2r_world/art/flow/car_sedan_white.dae'
local veh = be:getPlayerVehicle(0)
local c = veh and veh:getPosition() or core_camera.getPosition()
local cx, cy, cz = c.x, c.y, c.z
local group = createObject('SimGroup'); group:registerObject('e2rp_crowd'); group.canSave = false
local objs = {}
local function spawn(shape, n, ambient, radius)
  for k = 1, n do
    local a, r = k * 2.39996, 8 + radius * math.sqrt(k / n)
    local o = createObject('TSStatic')
    o:setField('shapeName', 0, shape)
    o:setField('collisionType', 0, 'None')
    o:setField('decalType', 0, 'None')
    o:setField('playAmbient', 0, ambient and '1' or '0')
    o.canSave = false
    o:setPosRot(cx + r * math.cos(a), cy + r * math.sin(a), cz, 0, 0, 0, 1)
    o:registerObject('')
    group:addObject(o)
    objs[#objs + 1] = {o = o, a = a, r = r}
  end
end
local function clear()
  for _, it in ipairs(objs) do it.o:delete() end
  objs = {}
end
local t = 0
local function move(dt)
  t = t + dt
  local timer = hptimer()
  for k, it in ipairs(objs) do
    local a = it.a + t * 1.4 / it.r  -- 1.4 m/s round the circle
    local yaw = a + math.pi / 2
    it.o:setPosRot(cx + it.r * math.cos(a), cy + it.r * math.sin(a), cz, 0, 0, -math.sin(yaw / 2), math.cos(yaw / 2))
  end
  return timer:stop()
end

local POSES = {'/levels/e2r_world/art/flow/car_sedan_white.dae', '/levels/e2r_world/art/flow/car_hatch_white.dae',
  '/levels/e2r_world/art/flow/car_suv_white.dae', '/levels/e2r_world/art/flow/car_van_white.dae'}
local agents = {}
local function spawnPosed(n)
  for k = 1, n do
    local a, r = k * 2.39996, 8 + 70 * math.sqrt(k / n)
    local ag = {a = a, r = r, objs = {}, pose = 1}
    for q, shape in ipairs(POSES) do
      local o = createObject('TSStatic')
      o:setField('shapeName', 0, shape); o:setField('collisionType', 0, 'None'); o:setField('decalType', 0, 'None')
      o.canSave = false
      o:setPosRot(cx + r * math.cos(a), cy + r * math.sin(a), cz, 0, 0, 0, 1)
      o:registerObject('')
      group:addObject(o)
      if q > 1 then o:setHidden(true) end
      ag.objs[q] = o
    end
    agents[#agents + 1] = ag
  end
end
local function clearPosed()
  for _, ag in ipairs(agents) do for _, o in ipairs(ag.objs) do o:delete() end end
  agents = {}
end
local swaps, frameNo = 0, 0
local function movePosed(dt, swap)
  t = t + dt
  frameNo = frameNo + 1
  local timer = hptimer()
  for k, ag in ipairs(agents) do
    if swap and (k + frameNo) % 8 == 0 then
      ag.objs[ag.pose]:setHidden(true)
      ag.pose = ag.pose % #POSES + 1
      ag.objs[ag.pose]:setHidden(false)
      swaps = swaps + 1
    end
    local a = ag.a + t * 1.4 / ag.r
    local yaw = a + math.pi / 2
    ag.objs[ag.pose]:setPosRot(cx + ag.r * math.cos(a), cy + ag.r * math.sin(a), cz, 0, 0, -math.sin(yaw / 2), math.cos(yaw / 2))
  end
  return timer:stop()
end
local out = {}
local phases = {
  {'base', function() end},
  {'posed_still_pose', function() spawnPosed(N) end, 'move'},
  {'posed_swapping', function() swaps = 0 end, 'swap'},
  {'base2', function() out.swapsPerFrame = swaps / (PHASE + 30); clearPosed() end},
}
local p, frame, acc = 0, 0, nil
local function metrics()
  local m = {}
  pcall(Engine.Debug.getLastPerformanceMetrics, m)
  return m
end
local function finish()
  local list = acc.frames
  table.sort(list)
  local total = 0
  for _, ms in ipairs(list) do total = total + ms end
  local r = {objects = #agents * #POSES, mean = total / #list, p50 = list[math.ceil(#list * .5)], p99 = list[math.ceil(#list * .99)],
    moveMs = acc.move / #list}
  for k, v in pairs(acc.m) do r['m_' .. k] = v / #list end
  out[phases[p][1]] = r
end
local warm = 30
return P.task(function(dt, ms)
  if p == 0 or frame >= PHASE + warm then
    if p > 0 then finish() end
    p = p + 1
    if p > #phases then clearPosed(); group:delete(); return out end
    phases[p][2]()
    frame, acc = 0, {frames = {}, move = 0, m = {}}
    return nil
  end
  frame = frame + 1
  local mode = phases[p][3]
  local mv = mode and movePosed(dt or 0, mode == 'swap') or 0
  if frame > warm then
    acc.frames[#acc.frames + 1] = ms
    acc.move = acc.move + mv
    for k, v in pairs(metrics()) do
      if type(v) == 'number' and (k == 'Lua' or k == 'LuaGC' or k == 'Render' or k == 'RenderShadows' or k == 'Ticking') then
        acc.m[k] = (acc.m[k] or 0) + v
      end
    end
  end
end)
