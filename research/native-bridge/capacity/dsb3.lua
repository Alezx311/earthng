-- DynamicShapeBatch before the flow and the walkers move onto it (batch2.lua found the calls):
--   colour  which palette slot setInstance's ColorF paints on the walker shape (shirt on the R
--           mask, pants G, skin B), whether a batch takes instanceColor1/2 as fields or more
--           colours per instance; a TSStatic with instanceColor/1/2 beside, one still.
--   quat    car shapes at yaw 0/30/90/150 as instances (white) and TSStatics (red) with the same
--           quaternion (flow.quat), one still from above: the same convention or not.
--   resize  keeps or drops the instances enabled before; setInstanceEnabled(false) hides one;
--           setInstance on a hidden one shows it or not; an index past the size.
--   group   a batch outside the MissionGroup (as the flow's group) is drawn or not.
--   far     the visible count of one car at 100..2000 m, before and after setDrawDistance.
--   remap   setMaterialRemap's signature.
--   many    40 batches of 25 against 1 batch of 1000 visible walkers: the frame.
-- The scene is 120 m up in the sky, so nothing of the city is in front of the camera.
local out = {log = {}}
local cx, cy, cz = CAP.origin()
local H = cz + 120
local PED = '/levels/e2r_world/art/people/ped_stand.dae'
local CAR_W = '/levels/e2r_world/art/flow/car_sedan_white.dae'
local CAR_R = '/levels/e2r_world/art/flow/car_sedan_red.dae'
local made = {}
local function log(s) out.log[#out.log + 1] = s end

local group = createObject('SimGroup')
group:registerObject('e2rcap_dsb3')
group.canSave = false

-- flow.quat and walkers.quat, copied (the conventions under test)
local function carQuat(yaw)
  local cy2, sy = math.cos(yaw / 2), math.sin(yaw / 2)
  return 0, 0, -sy, cy2
end
local function pedQuat(hx, hy)
  local yaw = math.atan2(hy, hx)
  return 0, 0, -math.sin(yaw / 2), math.cos(yaw / 2)
end

local function newBatch(shape, n, inMission)
  local b = createObject('DynamicShapeBatch')
  b.canSave = false
  b:registerObject('')
  if inMission then scenetree.MissionGroup:addObject(b) else group:addObject(b) end
  b:setShape(shape)
  b:finalizeShape()
  b:resize(n)
  made[#made + 1] = b
  return b
end

local function put(b, i, x, y, z, qx, qy, qz, qw, col, ...)
  b:setInstance(i, vec3(x, y, z), quat(qx, qy, qz, qw), 1, col or ColorF(1, 1, 1, 1), ...)
end

local function newStatic(shape, x, y, z, qx, qy, qz, qw)
  local o = createObject('TSStatic')
  o:setField('shapeName', 0, shape)
  o:setField('collisionType', 0, 'None')
  o:setField('decalType', 0, 'None')
  o.useInstanceRenderData = true
  o.canSave = false
  o:setPosRot(x, y, z, qx, qy, qz, qw)
  o:registerObject('')
  group:addObject(o)
  made[#made + 1] = o
  return o
end

local function counts(b)
  local r = {}
  for _, m in ipairs({'getLastVisibleCount', 'getLastSubmittedCount', 'getPrepCount'}) do
    local ok, v = pcall(function() return b[m](b) end)
    r[m] = ok and v or tostring(v)
  end
  return r
end

local function camera(x, y, z, dir, up)
  commands.setFreeCamera()
  core_camera.setPosition(0, vec3(x, y, z))
  core_camera.setRotation(0, quatFromDir(dir, up or vec3(0, 0, 1)))
end

local function wait(n)
  local k = 0
  return function() k = k + 1; return k >= n end
end

local function shot(name)
  return function()
    pcall(createScreenshot2, {filename = 'e2r_probe/' .. name, writeJPG = false, superSampling = 1})
    return true
  end
end

local function clearMade()
  for _, o in ipairs(made) do pcall(function() o:delete() end) end
  made = {}
end

local steps = {CAP.waitQuiet(60, 30)}

-- colour ---------------------------------------------------------------------------------------
local red, green, blue = ColorF(1, 0, 0, 1), ColorF(0, 1, 0, 1), ColorF(0, 0, 1, 1)
steps[#steps + 1] = function()
  CAP.phase('colour')
  camera(cx, cy - 7, H + 1, vec3(0, 1, -.08))
  local qx, qy, qz, qw = pedQuat(0, -1)     -- facing the camera
  local xs = {}
  for k = 0, 7 do xs[k + 1] = cx - 5.25 + k * 1.5 end
  -- 1: TSStatic, shirt red, pants green, skin blue
  local o = newStatic(PED, xs[1], cy, H, qx, qy, qz, qw)
  o.instanceColor, o.instanceColor1, o.instanceColor2 = red, green, blue
  -- 2..5: one batch, ColorF red, green, blue, white
  local a = newBatch(PED, 4)
  for k, c in ipairs({red, green, blue, ColorF(1, 1, 1, 1)}) do
    put(a, k - 1, xs[k + 1], cy, H, qx, qy, qz, qw, c)
    a:setInstanceEnabled(k - 1, true)
  end
  -- 6: more colours per instance
  local b = newBatch(PED, 1)
  local ok7, err7 = pcall(put, b, 0, xs[6], cy, H, qx, qy, qz, qw, red, green, blue)
  out.sevenArgs = ok7 or tostring(err7)
  if not ok7 then put(b, 0, xs[6], cy, H, qx, qy, qz, qw, red) end
  b:setInstanceEnabled(0, true)
  -- 7: the batch's own instanceColor1/2 fields, ColorF red per instance
  local c = newBatch(PED, 1)
  local okF, errF = pcall(function() c.instanceColor1, c.instanceColor2 = green, blue end)
  out.batchFields = okF or tostring(errF)
  local okS, errS = pcall(function()
    c:setField('instanceColor1', 0, '0 1 0 1'); c:setField('instanceColor2', 0, '0 0 1 1')
  end)
  out.batchSetField = okS or tostring(errS)
  put(c, 0, xs[7], cy, H, qx, qy, qz, qw, red)
  c:setInstanceEnabled(0, true)
  -- 8: in the MissionGroup (the rest are outside, as the flow's group)
  local d = newBatch(PED, 1, true)
  put(d, 0, xs[8], cy, H, qx, qy, qz, qw, red)
  d:setInstanceEnabled(0, true)
  out.colourBatches = {a = a, b = b, c = c, d = d}
  return true
end
steps[#steps + 1] = wait(40)
steps[#steps + 1] = function()
  local cb = out.colourBatches
  out.colourBatches = nil
  out.colourCounts = {a = counts(cb.a), b = counts(cb.b), c = counts(cb.c), mission = counts(cb.d)}
  local okG, f1 = pcall(function() return cb.c.instanceColor1 end)
  out.batchField1 = okG and tostring(f1) or ('error ' .. tostring(f1))
  return true
end
steps[#steps + 1] = shot('dsb3_colour')
steps[#steps + 1] = function() clearMade(); return true end

-- quat -----------------------------------------------------------------------------------------
steps[#steps + 1] = function()
  CAP.phase('quat')
  local x0 = cx + 60
  camera(x0, cy, H + 40, vec3(0, 0, -1), vec3(0, 1, 0))
  local b = newBatch(CAR_W, 4)
  for k, deg in ipairs({0, 30, 90, 150}) do
    local x = x0 + (k - 2.5) * 9
    local qx, qy, qz, qw = carQuat(math.rad(deg))
    put(b, k - 1, x, cy + 4, H, qx, qy, qz, qw)
    b:setInstanceEnabled(k - 1, true)
    newStatic(CAR_R, x, cy - 4, H, qx, qy, qz, qw)
  end
  return true
end
steps[#steps + 1] = wait(40)
steps[#steps + 1] = shot('dsb3_quat')
steps[#steps + 1] = function() clearMade(); return true end

-- resize ---------------------------------------------------------------------------------------
local R
local function rput(i) put(R, i, cx - 3 + i * .8, cy, H, pedQuat(0, -1)) end
steps[#steps + 1] = function()
  CAP.phase('resize')
  camera(cx, cy - 7, H + 1, vec3(0, 1, -.08))
  R = newBatch(PED, 4)
  for i = 0, 3 do rput(i); R:setInstanceEnabled(i, true) end
  return true
end
steps[#steps + 1] = wait(8)
steps[#steps + 1] = function()
  out.r4 = counts(R)
  R:resize(8)
  return true
end
steps[#steps + 1] = wait(8)
steps[#steps + 1] = function()
  out.r8kept = counts(R)
  for i = 4, 7 do rput(i); R:setInstanceEnabled(i, true) end
  return true
end
steps[#steps + 1] = wait(8)
steps[#steps + 1] = function()
  out.r8all = counts(R)
  R:setInstanceEnabled(0, false)
  return true
end
steps[#steps + 1] = wait(8)
steps[#steps + 1] = function()
  out.r8off0 = counts(R)
  rput(0)   -- set again, not enabled again
  return true
end
steps[#steps + 1] = wait(8)
steps[#steps + 1] = function()
  out.r8set0 = counts(R)
  local okP, errP = pcall(rput, 20)
  out.pastSize = okP or tostring(errP)
  local okE, errE = pcall(function() R:setInstanceEnabled(20, true) end)
  out.pastSizeEnable = okE or tostring(errE)
  R:resize(2)
  return true
end
steps[#steps + 1] = wait(8)
steps[#steps + 1] = function()
  out.r2shrunk = counts(R)
  R:clearInstances()
  return true
end
steps[#steps + 1] = wait(8)
steps[#steps + 1] = function()
  out.cleared = counts(R)
  local okS = pcall(function() rput(0); R:setInstanceEnabled(0, true) end)
  out.afterClearSet = okS
  return true
end
steps[#steps + 1] = wait(8)
steps[#steps + 1] = function()
  out.afterClear = counts(R)
  clearMade()
  return true
end

-- far ------------------------------------------------------------------------------------------
local F
local dists = {100, 300, 600, 1000, 2000, 4000}
out.far = {}
steps[#steps + 1] = function()
  CAP.phase('far')
  camera(cx, cy, H + 1, vec3(0, 1, 0))
  F = newBatch(CAR_W, 1)
  F:setInstanceEnabled(0, true)
  return true
end
for pass = 1, 2 do
  if pass == 2 then steps[#steps + 1] = function() F:setDrawDistance(8000); return true end end
  for _, d in ipairs(dists) do
    steps[#steps + 1] = function()
      local qx, qy, qz, qw = carQuat(0)
      put(F, 0, cx, cy + d, H, qx, qy, qz, qw)
      return true
    end
    steps[#steps + 1] = wait(5)
    steps[#steps + 1] = function()
      out.far[#out.far + 1] = {pass = pass, d = d, visible = counts(F).getLastVisibleCount}
      return true
    end
  end
end
steps[#steps + 1] = function() clearMade(); return true end

-- remap ----------------------------------------------------------------------------------------
steps[#steps + 1] = function()
  CAP.phase('remap')
  local b = newBatch(PED, 1)
  local tries = {
    {'(none)', {}},
    {'(string,string)', {'e2r_ped_shirt', 'e2r_ped_pants'}},
    {'(number,string)', {0, 'e2r_ped_pants'}},
    {'(string)', {'e2r_ped_pants'}},
    {'(table)', {{e2r_ped_shirt = 'e2r_ped_pants'}}},
  }
  out.remap = {}
  for _, t in ipairs(tries) do
    local ok, err = pcall(function() return b:setMaterialRemap(unpack(t[2], 1, table.maxn(t[2]))) end)
    out.remap[#out.remap + 1] = t[1] .. ' -> ' .. (ok and 'ok' or tostring(err))
  end
  clearMade()
  return true
end

-- many -----------------------------------------------------------------------------------------
local function spread(i)
  -- 1000 places in front of the camera, 15..90 m, a fan 50 m wide
  local row, col = math.floor(i / 40), i % 40
  return cx - 30 + col * 1.5, cy + 15 + row * 3, H
end
steps[#steps + 1] = function()
  CAP.phase('many-base')
  camera(cx, cy - 10, H + 12, vec3(0, 1, -.25))
  return true
end
steps[#steps + 1] = CAP.measure(out, 'manyBase', 90, 30)
steps[#steps + 1] = function()
  local qx, qy, qz, qw = pedQuat(0, -1)
  for k = 0, 39 do
    local b = newBatch(PED, 25)
    for i = 0, 24 do
      local x, y, z = spread(k * 25 + i)
      put(b, i, x, y, z, qx, qy, qz, qw)
      b:setInstanceEnabled(i, true)
    end
  end
  return true
end
steps[#steps + 1] = CAP.measure(out, 'many40x25', 90, 30, nil, function() return counts(made[1]) end)
steps[#steps + 1] = function() clearMade(); return true end
steps[#steps + 1] = function()
  local qx, qy, qz, qw = pedQuat(0, -1)
  local b = newBatch(PED, 1000)
  for i = 0, 999 do
    local x, y, z = spread(i)
    put(b, i, x, y, z, qx, qy, qz, qw)
    b:setInstanceEnabled(i, true)
  end
  return true
end
steps[#steps + 1] = CAP.measure(out, 'many1x1000', 90, 30, nil, function() return counts(made[1]) end)
steps[#steps + 1] = shot('dsb3_many')
steps[#steps + 1] = function()
  clearMade()
  pcall(function() group:delete() end)
  pcall(commands.setGameCamera)
  return true
end
return CAP.run(steps, out)
