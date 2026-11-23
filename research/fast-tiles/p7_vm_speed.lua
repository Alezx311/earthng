-- Fast tiles, probe 7: how fast the pieces of the shape writer run in a vehicle VM (and in GE Lua,
-- for comparison): a plain loop, FFI array writes and reads, struct reads, string building, and
-- the writer itself on 98 000 synthetic triangles.
local veh = getPlayerVehicle(0)
local at = veh:getPosition()
_G.e2rSp = {}
local BENCH = [[
local out = {}
local clock = os.clock
local function time(name, fn)
  local t = clock(); local ok, v = pcall(fn); out[#out + 1] = string.format('%s=%.1f%s', name, (clock() - t) * 1000, ok and '' or (' ERR ' .. tostring(v)))
end
local ffi = require('ffi')
time('loop3e7', function() local x = 0; for i = 1, 3e7 do x = x + i % 7 end; return x end)
time('ffiWrite1e7', function() local a = ffi.new('float[?]', 1e6); for r = 1, 10 do for i = 0, 1e6 - 1 do a[i] = i * .5 end end end)
time('ffiRead1e7', function() local a = ffi.new('float[?]', 1e6); local s = 0; for r = 1, 10 do for i = 0, 1e6 - 1 do s = s + a[i] end end end)
time('vec3Read3e6', function()
  local list = {}; for i = 1, 3e5 do list[i] = vec3(i, i, i) end
  local s = 0; for r = 1, 10 do for i = 1, 3e5 do local p = list[i]; s = s + p.x + p.y + p.z end end end)
time('tableKeys1e6', function() local seen = {}; for i = 1, 1e6 do local k = (i * 16384 + 3) * 16384 + i; if not seen[k] then seen[k] = i end end end)
time('ffiString', function() local a = ffi.new('float[?]', 3e6); local n = 0; for r = 1, 10 do n = n + #ffi.string(a, 12e6) end end)
time('concat', function() local s = string.rep('x', 4e6); local n = 0; for r = 1, 10 do n = n + #(string.char(1, 2) .. s) end end)
local writer
time('loadWriter', function() writer = require('ge/extensions/e2r/cdae') end)
if writer then
  local function mesh(n)
    local verts, normals, uvs, faces = {}, {}, {}, {}
    for j = 0, n do for i = 0, n do verts[#verts + 1] = vec3(i, j, 0); uvs[#uvs + 1] = {u = i, v = j} end end
    normals[1] = vec3(0, 0, 1)
    for j = 0, n - 1 do for i = 0, n - 1 do
      local a = j * (n + 1) + i
      for _, v in ipairs({a, a + n + 2, a + 1, a, a + n + 1, a + n + 2}) do faces[#faces + 1] = {v = v, n = 0, u = v} end
    end end
    return {verts = verts, normals = normals, uvs = uvs, faces = faces, material = 'm'}
  end
  local meshes = {}
  for k = 1, 40 do meshes[k] = mesh(35) end
  local b
  time('add98k', function() b = writer.builder(); for k = 1, 40 do b:add('solid', meshes[k], k, 0, 0) end end)
  time('encode98k', function() local data = b:encode(2); return #data end)
  time('add98k_100materials', function()
    b = writer.builder()
    for k = 1, 40 do meshes[k].material = 'm' .. k; b:add('solid', meshes[k], k, 0, 0) end
  end)
  time('encode98k_40materials', function() local data = b:encode(2); return #data end)
end
out[#out + 1] = 'jit=' .. tostring(jit and jit.status())
return table.concat(out, ' ')
]]
local ok, v = pcall(core_vehicles.spawnNewVehicle, 'ball', {
  pos = vec3(at.x + 40, at.y + 52, at.z + 1), rot = quat(0, 0, 0, 1),
  autoEnterVehicle = false, canSpawnAnotherVehicleCheck = false, vehicleName = 'e2r_worker_speed'})
if not ok or not v then return 'spawn failed ' .. tostring(v) end
local n = 0
return P.task(function()
  n = n + 1
  if n == 30 then
    v:queueLuaCommand("e2rTileWorker = assert(loadfile('/lua/ge/extensions/e2r/tileworker.lua'))()")
    v:queueLuaCommand(string.format('local f = assert(loadstring(%q)); obj:queueGameEngineLua(string.format("e2rSp.vm = %%q", f()))', BENCH))
  end
  if n == 40 then
    local f = assert(loadstring(BENCH))
    _G.e2rSp.ge = f()
  end
  if _G.e2rSp.vm and _G.e2rSp.ge then v:delete(); return _G.e2rSp end
  if n > 3000 then v:delete(); return {timeout = true, ge = _G.e2rSp.ge} end
end)
