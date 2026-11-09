-- Our procedural walkers (research/rust-in-mod/people_art.py, copied to <user>/current/e2r_probe/people):
-- N agents x 8 static walk poses, one shown, pose from the distance walked, colours per instance.
-- Phases: base, walkers, base2; then a still of a few walkers in front of a free camera.
local N, PHASE = tonumber(_G.__pedN or 300), tonumber(_G.__pedPhase or 150)
local DIR = '/e2r_probe/people/'
loadJsonMaterialsFile(DIR .. 'people.materials.json')
local POSES = 8
local STRIDE = 1.45   -- m walked per full cycle (two steps)
local veh = be:getPlayerVehicle(0)
local c = veh:getPosition()
local cx, cy, cz = c.x, c.y, c.z
local group = createObject('SimGroup'); group:registerObject('e2rp_people'); group.canSave = false
local SHIRTS = {{.75, .1, .1}, {.1, .2, .5}, {.9, .9, .88}, {.15, .15, .17}, {.2, .45, .25}, {.85, .65, .2}, {.5, .5, .52}}
local PANTS = {{.08, .1, .2}, {.12, .12, .13}, {.35, .3, .22}, {.25, .27, .3}}
local SKIN = {{.86, .68, .55}, {.72, .53, .4}, {.55, .38, .27}, {.93, .78, .66}}
local function lin(rgb) return ColorF(rgb[1], rgb[2], rgb[3], 1):asLinear4F() end
local agents = {}
local function spawn(n, ring0, ring1)
  for k = 1, n do
    local a, r = k * 2.39996, ring0 + ring1 * math.sqrt(k / n)
    local ag = {a = a, r = r, objs = {}, pose = 0, walked = (k * 0.37) % STRIDE, speed = 1.2 + (k % 5) * 0.08}
    local shirt, pants, skin = SHIRTS[k % #SHIRTS + 1], PANTS[k % #PANTS + 1], SKIN[k % #SKIN + 1]
    for q = 0, POSES - 1 do
      local o = createObject('TSStatic')
      o:setField('shapeName', 0, DIR .. 'ped_walk' .. q .. '.dae')
      o:setField('collisionType', 0, 'None'); o:setField('decalType', 0, 'None')
      o.canSave = false
      o:setPosRot(cx + r * math.cos(a), cy + r * math.sin(a), cz, 0, 0, 0, 1)
      o:registerObject('')
      group:addObject(o)
      pcall(function() o.instanceColor = lin(shirt); o.instanceColor1 = lin(pants); o.instanceColor2 = lin(skin) end)
      if q > 0 then o:setHidden(true) end
      ag.objs[q] = o
    end
    agents[#agents + 1] = ag
  end
end
local function clear()
  for _, ag in ipairs(agents) do for q = 0, POSES - 1 do ag.objs[q]:delete() end end
  agents = {}
end
local swaps = 0
local function step(dt)
  local timer = hptimer()
  for _, ag in ipairs(agents) do
    local d = ag.speed * dt
    ag.walked = ag.walked + d
    ag.a = ag.a + d / ag.r
    local pose = math.floor((ag.walked % STRIDE) / STRIDE * POSES) % POSES
    if pose ~= ag.pose then
      ag.objs[ag.pose]:setHidden(true)
      ag.objs[pose]:setHidden(false)
      ag.pose = pose
      swaps = swaps + 1
    end
    local yaw = ag.a + math.pi / 2
    ag.objs[pose]:setPosRot(cx + ag.r * math.cos(ag.a), cy + ag.r * math.sin(ag.a), cz, 0, 0, -math.sin(yaw / 2), math.cos(yaw / 2))
  end
  return timer:stop()
end
local out = {}
local phases = {
  {'base', function() end},
  {'walkers', function() spawn(N, 8, 70) end, true},
  {'base2', function() out.swapsPerFrame = swaps / (PHASE + 30); clear() end},
  {'still', function()
    spawn(12, 6, 6)
    local p, d = veh:getPosition(), veh:getDirectionVector()
    local f = vec3(d.x, d.y, 0):normalized()
    local cam = vec3(p.x - f.x * 3, p.y - f.y * 3, p.z + 4)
    local q = quatFromDir(vec3(p.x + f.x * 6, p.y + f.y * 6, p.z) - cam, vec3(0, 0, 1))
    commands.setFreeCamera()
    core_camera.setPosRot(0, cam.x, cam.y, cam.z, q.x, q.y, q.z, q.w)
  end, true},
}
local p, frame, acc = 0, 0, nil
local function metrics()
  local m = {}
  pcall(Engine.Debug.getLastPerformanceMetrics, m)
  return m
end
local function finish()
  local l = acc.frames
  table.sort(l)
  local total = 0
  for _, ms in ipairs(l) do total = total + ms end
  local r = {objects = #agents * POSES, mean = total / #l, p99 = l[math.ceil(#l * .99)], luaMs = acc.move / #l}
  for k, v in pairs(acc.m) do r['m_' .. k] = v / #l end
  out[phases[p][1]] = r
end
local warm = 30
return P.task(function(dt, ms)
  if p == 0 or frame >= PHASE + warm then
    if p > 0 then finish() end
    p = p + 1
    if p > #phases then
      createScreenshot2({filename = 'e2r_probe/people_still', writeJPG = false, superSampling = 1})
      return out
    end
    phases[p][2]()
    frame, acc = 0, {frames = {}, move = 0, m = {}}
    return nil
  end
  frame = frame + 1
  local mv = phases[p][3] and step(dt or 0) or 0
  if frame > warm then
    acc.frames[#acc.frames + 1] = ms
    acc.move = acc.move + mv
    for k, v in pairs(metrics()) do
      if type(v) == 'number' and (k == 'Lua' or k == 'Render' or k == 'RenderShadows') then acc.m[k] = (acc.m[k] or 0) + v end
    end
  end
end)
