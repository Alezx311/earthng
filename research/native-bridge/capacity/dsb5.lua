-- DynamicShapeBatch, third look. dsb4 showed setInstance's third argument is no rotation: a copy
-- given quat(0, 0, s, c) lay on its side whatever the angle. The guess: it is the direction of the
-- shape's +y axis, the frame built as Torque's createOrientFromDir (x = y cross up, z = x cross y).
--   dir     car and walker copies with dir = the shape's +y turned by yaw 0/30/90/150 (a car's
--           +x along the heading), TSStatics with setPosRot beside; a still from above and one
--           from the side; a dir with a slope (z) on a car.
--   remap   to a material that is not in the shape (another art set's), before finalizeShape.
--   final   a shape loaded long before / never: finalizeShape again 1, 3, 10 frames after
--           setShape; visible counts; the cost of finalizeShape.
--   args    seven arguments (three colours): taken or not, and what shows.
--   many    200 batches of 5 against 9 batches of ~111 visible walkers: the frame.
local out = {log = {}}
local cx, cy, cz = CAP.origin()
local H = cz + 120
local PED = '/levels/e2r_world/art/people/ped_stand.dae'
local PEDW = '/levels/e2r_world/art/people/ped_walk3.dae'
local function car(body, paint) return '/levels/e2r_world/art/flow/car_' .. body .. '_' .. paint .. '.dae' end
local made = {}
local timer = hptimer()

local group = createObject('SimGroup')
group:registerObject('e2rcap_dsb5')
group.canSave = false

local function carQuat(yaw) return 0, 0, -math.sin(yaw / 2), math.cos(yaw / 2) end
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
-- dir: the shape's +y as a unit vector
local function show(b, i, x, y, z, dx, dy, dz, col)
  b:setInstance(i, vec3(x, y, z), vec3(dx, dy, dz), 1, col or ColorF(1, 1, 1, 1))
  b:setInstanceEnabled(i, true)
end
local function yDir(yaw) return -math.sin(yaw), math.cos(yaw), 0 end
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
local X0 = cx + 60
local function lx(k) return X0 + (k - 2.5) * 9 end
local YAWS = {0, 30, 90, 150}

-- dir --------------------------------------------------------------------------------------------
steps[#steps + 1] = function()
  CAP.phase('dir')
  camera(X0, cy, H + 40, vec3(0, 0, -1), vec3(0, 1, 0))
  -- the shapes loaded by TSStatics first (finalizeShape needs them loaded, dsb4)
  for k, deg in ipairs(YAWS) do
    newStatic(car('sedan', 'red'), lx(k), cy - 4, H, carQuat(math.rad(deg)))
    newStatic(PEDW, lx(k) + 3, cy - 12, H, carQuat(math.rad(deg)))
  end
  return true
end
steps[#steps + 1] = wait(20)
local DB, DP
steps[#steps + 1] = function()
  DB = newBatch(car('sedan', 'red'), 5)
  DP = newBatch(PEDW, 4)
  for k, deg in ipairs(YAWS) do
    local dx, dy, dz = yDir(math.rad(deg))
    show(DB, k - 1, lx(k), cy + 4, H, dx, dy, dz)
    show(DP, k - 1, lx(k) + 3, cy + 12, H, dx, dy, dz, ColorF(0, .4, 1, 1))
  end
  -- a slope: +y tilted up 20 degrees (for a +x car that is a roll, the test of the guess)
  local s = math.rad(20)
  show(DB, 4, X0, cy + 20, H, 0, math.cos(s), math.sin(s))
  return true
end
steps[#steps + 1] = wait(30)
steps[#steps + 1] = function() out.dirVisible = {cars = visible(DB), walkers = visible(DP)}; return true end
steps[#steps + 1] = shot('dsb5_dir_top')
steps[#steps + 1] = function()
  camera(X0, cy - 40, H + 6, vec3(0, 1, -.12))
  return true
end
steps[#steps + 1] = wait(10)
steps[#steps + 1] = shot('dsb5_dir_side')
steps[#steps + 1] = function() clearMade(); return true end

-- remap and seven arguments ----------------------------------------------------------------------
steps[#steps + 1] = function()
  CAP.phase('remap')
  camera(cx, cy - 6, H + 1, vec3(0, 1, -.1))
  local face = yDir(math.rad(-90))
  local fx, fy, fz = yDir(math.rad(-90))
  -- 1: pants to the flow's red paint, skin to the flow's black: materials outside the shape
  try('remapOut', function()
    local b = rawBatch()
    b:setShape(PED)
    b:setMaterialRemap('e2r_ped_pants', 'e2r_flow_red')
    b:setMaterialRemap('e2r_ped_skin', 'e2r_flow_black')
    b:finalizeShape()
    b:resize(1)
    show(b, 0, cx - 3, cy, H, fx, fy, fz, ColorF(0, 1, 0, 1))
  end)
  -- 2: seven arguments
  try('seven', function()
    local b = newBatch(PED, 1)
    b:setInstance(0, vec3(cx - 1, cy, H), vec3(fx, fy, fz), 1, ColorF(1, 0, 0, 1), ColorF(0, 1, 0, 1), ColorF(0, 0, 1, 1))
    b:setInstanceEnabled(0, true)
    out.seven = 'taken'
  end)
  -- 3: remap after finalizeShape, then finalizeShape again
  try('remapAfter', function()
    local b = newBatch(PED, 1)
    b:setMaterialRemap('e2r_ped_shirt', 'e2r_ped_shoes')
    b:finalizeShape()
    show(b, 0, cx + 1, cy, H, fx, fy, fz, ColorF(0, 1, 0, 1))
  end)
  -- 4: plain, for comparison
  try('plain', function()
    local b = newBatch(PED, 1)
    show(b, 0, cx + 3, cy, H, fx, fy, fz, ColorF(1, 1, 0, 1))
  end)
  return true
end
steps[#steps + 1] = wait(40)
steps[#steps + 1] = shot('dsb5_remap')
steps[#steps + 1] = function() clearMade(); return true end

-- final ------------------------------------------------------------------------------------------
-- shapes no TSStatic loaded: the vans; loaded long ago: the red sedan (its TSStatics went, the
-- resource stays)
local FIN = {}
local finalUs = {}
local function finalCase(key, shape, after, k)
  local b = rawBatch()
  b:setShape(shape)
  timer:stopAndReset()
  b:finalizeShape()
  finalUs[#finalUs + 1] = timer:stop() * 1000
  b:resize(1)
  show(b, 0, lx(k), cy + (after > 0 and 0 or 8), H, yDir(0))
  FIN[key] = {b = b, after = after, frame = 0}
end
steps[#steps + 1] = function()
  CAP.phase('final')
  camera(X0, cy, H + 40, vec3(0, 0, -1), vec3(0, 1, 0))
  finalCase('cold1', car('van', 'white'), 1, 1)
  finalCase('cold3', car('van', 'black'), 3, 2)
  finalCase('cold10', car('van', 'silver'), 10, 3)
  finalCase('coldNever', car('van', 'grey'), 0, 4)
  finalCase('warmOnce', car('sedan', 'red'), 0, 1)
  return true
end
local fframe = 0
steps[#steps + 1] = function()
  fframe = fframe + 1
  for _, c in pairs(FIN) do
    if c.after > 0 and fframe == c.after then
      timer:stopAndReset()
      c.b:finalizeShape()
      finalUs[#finalUs + 1] = timer:stop() * 1000
    end
  end
  return fframe >= 40
end
steps[#steps + 1] = function()
  out.final = {}
  for key, c in pairs(FIN) do out.final[key] = visible(c.b) end
  out.finalUs = finalUs
  return true
end
steps[#steps + 1] = shot('dsb5_final')
steps[#steps + 1] = function() clearMade(); return true end

-- many -------------------------------------------------------------------------------------------
local function spread(i)
  local row, col = math.floor(i / 40), i % 40
  return cx - 30 + col * 1.5, cy + 15 + row * 3, H
end
local MP = {}
steps[#steps + 1] = function()
  CAP.phase('many-base')
  camera(cx, cy - 10, H + 12, vec3(0, 1, -.25))
  -- the walk poses loaded
  for k = 0, 7 do MP[k + 1] = '/levels/e2r_world/art/people/ped_walk' .. k .. '.dae' end
  MP[9] = PED
  for k, s in ipairs(MP) do newStatic(s, cx, cy - 30, H - 50, 0, 0, 0, 1, true) end
  return true
end
steps[#steps + 1] = wait(20)
steps[#steps + 1] = CAP.measure(out, 'manyBase', 120, 30)
local function fill(nb, per)
  local fx, fy, fz = yDir(math.rad(-90))
  local i = 0
  for k = 1, nb do
    local b = newBatch(MP[(k - 1) % 9 + 1], per)
    for j = 0, per - 1 do
      local x, y, z = spread(i)
      show(b, j, x, y, z, fx, fy, fz, ColorF((k % 3) / 2, (k % 5) / 4, (k % 7) / 6, 1))
      i = i + 1
    end
  end
end
steps[#steps + 1] = function() fill(9, 111); return true end
steps[#steps + 1] = wait(10)
steps[#steps + 1] = function() for _, b in ipairs(made) do pcall(function() b:finalizeShape() end) end; return true end
steps[#steps + 1] = CAP.measure(out, 'many9', 120, 30)
steps[#steps + 1] = shot('dsb5_many9')
steps[#steps + 1] = function()
  local keep = {}
  for _, o in ipairs(made) do
    if o:getClassName() == 'TSStatic' then keep[#keep + 1] = o else pcall(function() o:delete() end) end
  end
  made = keep
  fill(200, 5)
  return true
end
steps[#steps + 1] = wait(10)
steps[#steps + 1] = function()
  for _, b in ipairs(made) do if b:getClassName() ~= 'TSStatic' then pcall(function() b:finalizeShape() end) end end
  return true
end
steps[#steps + 1] = CAP.measure(out, 'many200', 120, 30)
steps[#steps + 1] = shot('dsb5_many200')
steps[#steps + 1] = function()
  clearMade()
  pcall(function() group:delete() end)
  pcall(commands.setGameCamera)
  return true
end
return CAP.run(steps, out)
