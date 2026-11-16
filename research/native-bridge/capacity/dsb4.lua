-- DynamicShapeBatch, second look (dsb3.lua: car shapes drew nothing, the walker shape drew; the
-- colour step stopped on the TSStatic's instanceColor, a Point4F):
--   load    a shape no TSStatic loaded yet: finalizeShape at once / 30 frames after setShape /
--           after a hidden TSStatic of it in the same frame / 30 frames after one. Visible counts
--           and one still from above.
--   colour  the walker shape: ColorF red/green/blue/white, a palette shirt as sRGB and as linear,
--           the batch's instanceColor1/2 as Point4F, setMaterialRemap before and after
--           finalizeShape; a TSStatic with the same colours beside. One still.
--   quat    the red sedan (loaded by its TSStatics) as copies beside the TSStatics, same quats.
--   far     one copy at 100..4000 m (placed before it is enabled), before and after setDrawDistance.
local out = {log = {}}
local cx, cy, cz = CAP.origin()
local H = cz + 120
local PED = '/levels/e2r_world/art/people/ped_stand.dae'
local function car(body, paint) return '/levels/e2r_world/art/flow/car_' .. body .. '_' .. paint .. '.dae' end
local made = {}

local group = createObject('SimGroup')
group:registerObject('e2rcap_dsb4')
group.canSave = false

local function carQuat(yaw) return 0, 0, -math.sin(yaw / 2), math.cos(yaw / 2) end
local function pedQuat(hx, hy)
  local yaw = math.atan2(hy, hx)
  return 0, 0, -math.sin(yaw / 2), math.cos(yaw / 2)
end

local function rawBatch()
  local b = createObject('DynamicShapeBatch')
  b.canSave = false
  b:registerObject('')
  group:addObject(b)
  made[#made + 1] = b
  return b
end
local function newBatch(shape, n, remap)
  local b = rawBatch()
  b:setShape(shape)
  if remap then b:setMaterialRemap(remap[1], remap[2]) end
  b:finalizeShape()
  b:resize(n)
  return b
end
local function put(b, i, x, y, z, qx, qy, qz, qw, col)
  b:setInstance(i, vec3(x, y, z), quat(qx, qy, qz, qw), 1, col or ColorF(1, 1, 1, 1))
end
local function show(b, i, ...) put(b, i, ...); b:setInstanceEnabled(i, true) end
local function newStatic(shape, x, y, z, qx, qy, qz, qw, hidden)
  local o = createObject('TSStatic')
  o:setField('shapeName', 0, shape)
  o:setField('collisionType', 0, 'None')
  o:setField('decalType', 0, 'None')
  o.useInstanceRenderData = true
  o.canSave = false
  o:setPosRot(x, y, z, qx, qy, qz, qw)
  o:registerObject('')
  if hidden then o:setHidden(true) end
  group:addObject(o)
  made[#made + 1] = o
  return o
end
local function visible(b)
  local ok, v = pcall(function() return b:getLastVisibleCount() end)
  return ok and v or tostring(v)
end
local function camera(x, y, z, dir, up)
  commands.setFreeCamera()
  core_camera.setPosition(0, vec3(x, y, z))
  core_camera.setRotation(0, quatFromDir(dir, up or vec3(0, 0, 1)))
end
local function wait(n)
  local k = 0
  return function() k = k + 1; if k >= n then k = 0; return true end end
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
local function try(key, fn)
  local ok, err = pcall(fn)
  if not ok then out.log[#out.log + 1] = key .. ': ' .. tostring(err) end
  return ok
end

local steps = {CAP.waitQuiet(60, 30)}

-- load -------------------------------------------------------------------------------------------
local L = {}
local X0 = cx + 60
local function lx(k) return X0 + (k - 2.5) * 9 end
steps[#steps + 1] = function()
  CAP.phase('load')
  camera(X0, cy, H + 40, vec3(0, 0, -1), vec3(0, 1, 0))
  local q = {carQuat(0)}
  -- A: at once, never loaded
  L.a = newBatch(car('sedan', 'blue'), 2)
  show(L.a, 0, lx(1), cy, H, unpack(q))
  -- B: setShape now, finalizeShape 30 frames later
  L.b = rawBatch()
  L.b:setShape(car('hatch', 'blue'))
  -- C: a hidden TSStatic of the shape in the same frame, then the batch
  newStatic(car('suv', 'blue'), lx(3), cy - 20, H, 0, 0, 0, 1, true)
  L.c = newBatch(car('suv', 'blue'), 2)
  show(L.c, 0, lx(3), cy, H, unpack(q))
  -- D: a hidden TSStatic now, the batch 30 frames later
  newStatic(car('van', 'blue'), lx(4), cy - 20, H, 0, 0, 0, 1, true)
  return true
end
steps[#steps + 1] = wait(30)
steps[#steps + 1] = function()
  local q = {carQuat(0)}
  L.b:finalizeShape()
  L.b:resize(2)
  show(L.b, 0, lx(2), cy, H, unpack(q))
  L.d = newBatch(car('van', 'blue'), 2)
  show(L.d, 0, lx(4), cy, H, unpack(q))
  -- A again: finalizeShape a second time, now that 30 frames passed
  try('refinalize', function() L.a:finalizeShape(); L.a:resize(2); show(L.a, 1, lx(1), cy + 6, H, unpack(q)) end)
  return true
end
steps[#steps + 1] = wait(30)
steps[#steps + 1] = function()
  out.load = {atOnce = visible(L.a), finalizeLater = visible(L.b), staticSameFrame = visible(L.c),
    staticBefore = visible(L.d)}
  return true
end
steps[#steps + 1] = shot('dsb4_load')
steps[#steps + 1] = function() clearMade(); L = {}; return true end

-- colour -----------------------------------------------------------------------------------------
local function lin(r, g, b) return ColorF(r, g, b, 1):asLinear4F() end
steps[#steps + 1] = function()
  CAP.phase('colour')
  camera(cx, cy - 6, H + 1, vec3(0, 1, -.1))
  local q = {pedQuat(0, -1)}
  local xs = {}
  for k = 0, 9 do xs[k + 1] = cx - 5.4 + k * 1.2 end
  local shirt = {.75, .1, .1}
  -- 1: TSStatic red / green / blue
  try('static', function()
    local o = newStatic(PED, xs[1], cy, H, unpack(q))
    o.instanceColor, o.instanceColor1, o.instanceColor2 = lin(1, 0, 0), lin(0, 1, 0), lin(0, 0, 1)
  end)
  -- 2: TSStatic, the palette shirt (sRGB -> linear, as walkers.lua)
  try('static2', function()
    local o = newStatic(PED, xs[2], cy, H, unpack(q))
    o.instanceColor = lin(shirt[1], shirt[2], shirt[3])
  end)
  try('batch', function()
    local a = newBatch(PED, 6)
    -- 3..6: ColorF red, green, blue, white; 7: shirt as sRGB; 8: shirt made linear
    local cols = {ColorF(1, 0, 0, 1), ColorF(0, 1, 0, 1), ColorF(0, 0, 1, 1), ColorF(1, 1, 1, 1),
      ColorF(shirt[1], shirt[2], shirt[3], 1)}
    local l = ColorF(shirt[1], shirt[2], shirt[3], 1):asLinear4F()
    cols[6] = ColorF(l.x, l.y, l.z, 1)
    for k, c in ipairs(cols) do show(a, k - 1, xs[k + 2], cy, H, q[1], q[2], q[3], q[4], c) end
  end)
  -- 9: the batch's fields instanceColor1/2 (Point4F), shirt ColorF red
  try('fields', function()
    local c = newBatch(PED, 1)
    c.instanceColor1, c.instanceColor2 = lin(0, 1, 0), lin(0, 0, 1)
    show(c, 0, xs[9], cy, H, q[1], q[2], q[3], q[4], ColorF(1, 0, 0, 1))
    out.fieldRead = tostring(c.instanceColor1)
  end)
  -- 10: pants remapped to the shoes' material before finalizeShape
  try('remap', function()
    local d = newBatch(PED, 1, {'e2r_ped_pants', 'e2r_ped_shoes'})
    show(d, 0, xs[10], cy, H, q[1], q[2], q[3], q[4], ColorF(1, 0, 0, 1))
  end)
  -- 11 (behind, raised): remap after finalizeShape
  try('remapAfter', function()
    local e = newBatch(PED, 1)
    e:setMaterialRemap('e2r_ped_shirt', 'e2r_ped_shoes')
    show(e, 0, cx, cy + 3, H + 1.2, q[1], q[2], q[3], q[4], ColorF(0, 1, 0, 1))
  end)
  return true
end
steps[#steps + 1] = wait(40)
steps[#steps + 1] = shot('dsb4_colour')
steps[#steps + 1] = function() clearMade(); return true end

-- quat -------------------------------------------------------------------------------------------
local QB
steps[#steps + 1] = function()
  CAP.phase('quat')
  camera(X0, cy, H + 40, vec3(0, 0, -1), vec3(0, 1, 0))
  for k, deg in ipairs({0, 30, 90, 150}) do newStatic(car('sedan', 'red'), lx(k), cy - 4, H, carQuat(math.rad(deg))) end
  return true
end
steps[#steps + 1] = wait(20)
steps[#steps + 1] = function()
  QB = newBatch(car('sedan', 'red'), 4)
  for k, deg in ipairs({0, 30, 90, 150}) do show(QB, k - 1, lx(k), cy + 4, H, carQuat(math.rad(deg))) end
  return true
end
steps[#steps + 1] = wait(30)
steps[#steps + 1] = function() out.quatVisible = visible(QB); return true end
steps[#steps + 1] = shot('dsb4_quat')
steps[#steps + 1] = function() clearMade(); return true end

-- far --------------------------------------------------------------------------------------------
local F
out.far = {}
steps[#steps + 1] = function()
  CAP.phase('far')
  camera(cx, cy, H + 1, vec3(0, 1, 0))
  newStatic(car('sedan', 'white'), cx, cy - 50, H, 0, 0, 0, 1, true)
  return true
end
steps[#steps + 1] = wait(20)
steps[#steps + 1] = function()
  F = newBatch(car('sedan', 'white'), 1)
  show(F, 0, cx, cy + 100, H, carQuat(0))
  return true
end
for pass = 1, 2 do
  if pass == 2 then steps[#steps + 1] = function() F:setDrawDistance(8000); return true end end
  for _, d in ipairs({100, 300, 600, 1000, 2000, 4000}) do
    steps[#steps + 1] = function() put(F, 0, cx, cy + d, H, carQuat(0)); return true end
    steps[#steps + 1] = wait(5)
    steps[#steps + 1] = function()
      out.far[#out.far + 1] = {pass = pass, d = d, visible = visible(F)}
      return true
    end
  end
end
steps[#steps + 1] = function()
  clearMade()
  pcall(function() group:delete() end)
  pcall(commands.setGameCamera)
  return true
end
return CAP.run(steps, out)
