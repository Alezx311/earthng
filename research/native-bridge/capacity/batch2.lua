-- DynamicShapeBatch, second try (batch.lua found its methods: setShape, resize, setInstance,
-- setInstanceEnabled, clearInstances, finalizeShape, setDrawDistance, setMaterialRemap,
-- getLastSubmittedCount, getLastVisibleCount, getPrepCount). The binding says which argument it
-- wanted ("bad argument #k ... (T expected, got X)"), so each method's signature is learnt by
-- adding the asked type until the call goes through. Then N instances in front of the camera:
-- visible counts, setInstance cost, the frame with them standing and with all of them moving.
local SHAPE = CAP.ROCK
local out = {sigs = {}, log = {}}
local cx, cy, cz = CAP.origin()

local function value(t, slot)
  t = (t or ''):lower()
  if t == 'number' or t:find('int') or t:find('float') or t == 'f32' or t == 'u32' or t == 's32' then return slot == 'index' and 0 or 1 end
  if t:find('point3') or t == 'vec3' or t:find('vector') then return vec3(cx, cy, cz) end
  if t:find('quat') then return quat(0, 0, 0, 1) end
  if t:find('color') then return ColorF(1, 1, 1, 1) end
  if t:find('matrix') then return MatrixF(true) end
  if t:find('bool') then return true end
  if t:find('string') or t:find('char') then return SHAPE end
  return nil
end

-- learn a signature: call with the args so far, extend/replace by the type the error names
local function learn(b, name, start)
  local args, types = {}, {}
  for i, a in ipairs(start or {}) do args[i] = a; types[i] = type(a) end
  for _ = 1, 12 do
    local ok, err = pcall(function() return b[name](b, unpack(args, 1, #args)) end)
    out.log[#out.log + 1] = name .. '(' .. table.concat(types, ',') .. ') -> ' .. (ok and 'ok' or tostring(err))
    if ok then return true, types end
    local k, want = tostring(err):match('bad argument #(%d+) .-%((%S+) expected')
    k = tonumber(k)
    if not k then return false, types, tostring(err) end
    local pos = k - 1   -- #1 is the object
    local v = value(want, pos == 1 and 'index' or nil)
    if v == nil then return false, types, 'unknown type ' .. tostring(want) end
    for i = #args + 1, pos - 1 do args[i] = 0; types[i] = 'number?' end
    args[pos], types[pos] = v, want
  end
  return false, types, 'gave up'
end

local okC, b = pcall(createObject, 'DynamicShapeBatch')
if not okC then return 'create: ' .. tostring(b) end
b.canSave = false
b:registerObject('e2rcap_batch2')
pcall(function() scenetree.MissionGroup:addObject(b) end)
for _, m in ipairs({'setShape', 'resize', 'setDrawDistance', 'finalizeShape'}) do
  local start = m == 'setShape' and {SHAPE} or (m == 'resize' and {4} or (m == 'setDrawDistance' and {2000} or nil))
  local ok, types, err = learn(b, m, start)
  out.sigs[m] = {ok = ok, types = types, err = err}
end
-- setInstance: the binding checks its arguments out of order, so try whole candidate lists
-- (index 0 first); the position is the first point-like value of the winning list
local function P3(x, y, z) local ok, v = pcall(function() return Point3F(x, y, z) end); return ok and v or nil end
local function Q4() local ok, v = pcall(function() return QuatF(0, 0, 0, 1) end); return ok and v or nil end
local function CF() local ok, v = pcall(function() return ColorF(1, 1, 1, 1) end); return ok and v or nil end
local function MF() local ok, v = pcall(function() return MatrixF(true) end); return ok and v or nil end
local cands = {
  {'vec3,quat,n', function() return {vec3(cx, cy, cz), quat(0, 0, 0, 1), 1} end},
  {'P3,Q4,n', function() return {P3(cx, cy, cz), Q4(), 1} end},
  {'vec3,quat,n,colour', function() return {vec3(cx, cy, cz), quat(0, 0, 0, 1), 1, CF()} end},
  {'P3,Q4,n,colour', function() return {P3(cx, cy, cz), Q4(), 1, CF()} end},
  {'vec3,n,n', function() return {vec3(cx, cy, cz), 0, 1} end},
  {'P3,n,n', function() return {P3(cx, cy, cz), 0, 1} end},
  {'matrix,n', function() return {MF(), 1} end},
  {'matrix,vec3', function() return {MF(), vec3(1, 1, 1)} end},
  {'matrix,P3', function() return {MF(), P3(1, 1, 1)} end},
  {'vec3,quat,vec3', function() return {vec3(cx, cy, cz), quat(0, 0, 0, 1), vec3(1, 1, 1)} end},
  {'P3,Q4,P3', function() return {P3(cx, cy, cz), Q4(), P3(1, 1, 1)} end},
  {'xyz,quat4,n', function() return {cx, cy, cz, 0, 0, 0, 1, 1} end},
  {'xyz,n', function() return {cx, cy, cz, 1} end},
  {'xyz,yaw,n', function() return {cx, cy, cz, 0, 1} end},
}
local okI, win
out.cands = {}
for _, c in ipairs(cands) do
  local list = c[2]()
  local ok, err = pcall(function() return b:setInstance(0, unpack(list, 1, table.maxn(list))) end)
  out.cands[#out.cands + 1] = c[1] .. ' -> ' .. (ok and 'ok' or tostring(err))
  if ok then okI, win = true, c; break end
end
out.setInstanceSig = win and win[1]
local okE = pcall(function() b:setInstanceEnabled(0, true) end)
out.enabledTakesBool = okE
if not okI then pcall(function() b:delete() end); return out end

local cam, fwd = core_camera.getPosition(), core_camera.getForward()
local function place(i, t)
  local d = 12 + (i % 50) * 2.5
  local side = (math.floor(i / 50) - 40) * 2.5 + math.sin(t + i) * 0.5
  return cam.x + fwd.x * d - fwd.y * side, cam.y + fwd.y * d + fwd.x * side, cz
end
local timer = hptimer()
local A = win[2]()
local nA = table.maxn(A)
local sig = win[1]
local P = (sig:find('^vec3') or sig:find('^P3')) and A[1] or nil
local xyz = sig:find('^xyz') ~= nil
local mat = sig:find('^matrix') and A[1] or nil
local function fill(n, t)
  timer:stopAndReset()
  for i = 0, n - 1 do
    local x, y, z = place(i, t)
    if xyz then A[1], A[2], A[3] = x, y, z
    elseif P then P.x, P.y, P.z = x, y, z
    elseif mat then mat:setPosition(vec3(x, y, z)) end
    b:setInstance(i, unpack(A, 1, nA))
  end
  return timer:stop() * 1000 / n
end
local function counts()
  local r = {}
  for _, m in ipairs({'getLastSubmittedCount', 'getLastVisibleCount', 'getPrepCount'}) do
    local ok, v = pcall(function() return b[m](b) end)
    r[m] = ok and v or tostring(v)
  end
  return r
end

local N1, N2 = 4000, 20000
local steps = {CAP.waitQuiet(90, 60)}
steps[#steps + 1] = function()
  pcall(function() b:resize(N1) end)
  out.fillUs4k = fill(N1, 0)
  for i = 0, N1 - 1 do pcall(function() if okE then b:setInstanceEnabled(i, true) else b:setInstanceEnabled(i) end end) end
  return true
end
local wait = 0
steps[#steps + 1] = function() wait = wait + 1; return wait > 20 end
steps[#steps + 1] = function()
  out.counts4k = counts()
  pcall(createScreenshot2, {filename = 'e2r_probe/cap_batch2_on', writeJPG = false, superSampling = 1})
  return true
end
steps[#steps + 1] = CAP.measure(out, 'stand4k', 60, 10)
steps[#steps + 1] = function()
  pcall(function() b:resize(N2) end)
  out.fillUs20k = fill(N2, 0)
  for i = N1, N2 - 1 do pcall(function() if okE then b:setInstanceEnabled(i, true) else b:setInstanceEnabled(i) end end) end
  return true
end
steps[#steps + 1] = CAP.measure(out, 'stand20k', 90, 20, nil, function() return counts() end)
local t, moveMs, moved = 0, 0, 0
steps[#steps + 1] = CAP.measure(out, 'move20k', 60, 10, function(dt, measured)
  t = t + dt
  local us = fill(N2, t)
  if measured then moveMs, moved = moveMs + us * N2 / 1000, moved + N2 end
end, function() return {moveUs = moveMs * 1000 / math.max(1, moved)} end)
steps[#steps + 1] = function()
  pcall(function() b:setHidden(true) end)
  pcall(createScreenshot2, {filename = 'e2r_probe/cap_batch2_off', writeJPG = false, superSampling = 1})
  return true
end
steps[#steps + 1] = CAP.measure(out, 'hidden', 60, 10)
steps[#steps + 1] = function() pcall(function() b:delete() end); return true end
return CAP.run(steps, out)
