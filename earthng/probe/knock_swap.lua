-- Is the swap of a knockable prop visible? (knock.lua: the Forest item leaves, a pooled TSStatic of the
-- shape stands in its place LEAD s before the touch.) For
--   test_world.py --manual --probe ... then
--   python earthng/probe.py --user <out>/user [--wait-landed] -f earthng/probe/knock_swap.lua --timeout 240
-- The nearest standing knockable props of up to five shapes round the player, each seen from 4.5 m:
-- a still before (e2r_probe/swap_<k>_a.png), the swap done as knock.lua's arm() does it, a still 2
-- frames after (_b) and 40 frames after (_c). earthng/probe/knock_swap_diff.py compares them.
local W = extensions.e2r_world
if not W or not W.knockState or not W.knock then return {error = 'no world.knockState'} end
local ks = W.knockState()
local K, api, knock = ks.K, ks.api, W.knock
local up = vec3(0, 0, 1)
local p0 = be:getPlayerVehicle(0):getPosition()
local R = {items = {}}

-- the nearest standing item of each shape, within 120 m
local best = {}
for id = 1, K.n do
  if K.STATE[id] == knock.STAND then
    local d = (K.X[id] - p0.x) ^ 2 + (K.Y[id] - p0.y) ^ 2
    local shape = K.SHAPE[id]
    if d < 120 * 120 and (not best[shape] or d < best[shape].d) then best[shape] = {id = id, d = d} end
  end
end
local list = {}
for shape, b in pairs(best) do list[#list + 1] = {id = b.id, d = b.d, shape = shape} end
table.sort(list, function(a, b) return a.d < b.d end)
while #list > 5 do table.remove(list) end
if #list == 0 then return {error = 'no standing knockable prop within 120 m', registered = K.items} end

local function shot(name)
  pcall(createScreenshot2, {filename = 'e2r_probe/swap_' .. name, writeJPG = false, superSampling = 1})
end

local k, frame, stage = 1, 0, 'aim'
return P.task(function()
  local it = list[k]
  if not it then return R end
  frame = frame + 1
  local id = it.id
  local x, y, z = K.X[id], K.Y[id], K.Z[id]
  local spec, sc = K.SPEC[id], K.SC[id]
  if stage == 'aim' then
    -- from the road side: away from the nearest building would be better, but the player's side is
    -- the street the car came along
    local away = vec3(p0.x - x, p0.y - y, 0)
    if away:length() < .1 then away = vec3(1, 0, 0) end
    away = away:normalized()
    local eye = vec3(x, y, z) + away * 4.5 + up * 1.6
    local at = vec3(x, y, z + spec.hz * sc)
    pcall(function() commands.setFreeCamera() end)
    core_camera.setPosition(0, eye)
    core_camera.setRotation(0, quatFromDir((at - eye):normalized(), up))
    stage, frame = 'settle', 0
  elseif stage == 'settle' and frame == 60 then
    shot(k .. '_a')
  elseif stage == 'settle' and frame == 70 then
    -- knock.lua arm(): hide the Forest item, take a TSStatic, place it as show() does (upright: the
    -- base's middle at the item's place, its yaw)
    local hidden = api.hide(id, it.shape, x, y, z)
    local obj = hidden and api.take(it.shape, sc)
    if obj then api.place(obj, x, y, z, 0, 0, K.QZ[id], K.QW[id]) end
    R.items[k] = {shape = it.shape, dist = math.floor(math.sqrt(it.d)), hidden = hidden, taken = obj and true or false,
      x = x, y = y, z = z, qz = K.QZ[id], qw = K.QW[id], scale = sc}
    if hidden then K.STATE[id] = knock.GONE end
    stage, frame = 'after', 0
  elseif stage == 'after' and frame == 2 then
    shot(k .. '_b')
  elseif stage == 'after' and frame == 40 then
    shot(k .. '_c')
    k, stage, frame = k + 1, 'aim', 0
  end
end)
