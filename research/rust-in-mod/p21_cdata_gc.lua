-- What the game's collector pays for a million short-lived cdata against a million tables:
-- a full collection with them alive, the longest incremental step while they die, and whether
-- vec3 carries a finalizer (__gc) of its own. Answer to the ~550 ms hitches every 10-15 s once
-- the generator's mesh output was cdata (out/gc-02, gc-03, mesh-probe-01).
local ffi = require('ffi')
pcall(ffi.cdef, 'typedef struct { int32_t v, n, u; } e2r_face_t;')
local FACE = ffi.typeof('e2r_face_t')
local V3 = ffi.typeof('struct __luaVec3_t')
local r = {}
local mt = debug.getmetatable(vec3(0, 0, 0))
r.vec3gc = mt and tostring(rawget(mt, '__gc')) or 'no metatable'
local mtIndex = mt and rawget(mt, '__index')
r.vec3gcInIndex = type(mtIndex) == 'table' and tostring(rawget(mtIndex, '__gc')) or tostring(mtIndex)
local function clock() return os.clock() * 1000 end
local function run(name, make)
  collectgarbage('collect')
  local t = {}
  local a = clock()
  for i = 1, 1000000 do t[i] = make(i) end
  local built = clock() - a
  a = clock(); collectgarbage('collect'); local alive = clock() - a
  t = nil
  -- incremental death: the longest single step
  local worst, steps, total = 0, 0, 0
  repeat
    local s = clock()
    local done = collectgarbage('step', 0)
    local dt = clock() - s
    total = total + dt; steps = steps + 1
    if dt > worst then worst = dt end
  until done or steps > 2000000
  a = clock(); collectgarbage('collect'); local after = clock() - a
  r[name] = string.format('build %.0f ms, collect alive %.0f ms, worst step %.1f ms (%d steps, %.0f ms), collect after %.0f ms',
    built, alive, worst, steps, total, after)
end
run('tables', function(i) return {x = i, y = i, z = i} end)
run('vec3', function(i) return vec3(i, i, i) end)
run('v3ctype', function(i) return V3(i, i, i) end)
run('face', function(i) return FACE(i, i, i) end)
r.heapMB = math.floor(collectgarbage('count') / 1024)
return r
