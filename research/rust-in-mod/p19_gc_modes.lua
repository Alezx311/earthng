-- How the engine steps the GE Lua collector while a generator fills the heap (the landing): for
-- FRAMES frames a task builds live geometry the way generator.lua does (arrays of small vertex and
-- face tables appended to a live mesh, PER_FRAME of them a frame, plus as much garbage), under MODE:
--   'default'  the engine's own stepmul (gc.lua's while driving)
--   'mul10'    setstepmul 10 every frame
--   'mul400'   setstepmul 400 every frame
--   'stop'     collectgarbage('stop') at the start of every frame's work
--   'stopEnd'  the same, and again at its end
-- Reports per frame: our Lua ms, the engine's Lua and LuaGC ms (Engine.Debug metrics), the heap.
local MODE = 'default'   -- replaced by the caller
local FRAMES, PER_FRAME = 150, 12000
local live = {}
local m, sum, n = {}, {lua = 0, gc = 0, ours = 0, frame = 0}, 0
local heap0 = collectgarbage('count')
local saved = collectgarbage('setstepmul', 100)
collectgarbage('setstepmul', saved)
local worstGc = 0
return P.task(function(dt)
  if MODE == 'mul10' then collectgarbage('setstepmul', 10)
  elseif MODE == 'mul400' then collectgarbage('setstepmul', 400)
  elseif MODE == 'stop' or MODE == 'stopEnd' then collectgarbage('stop') end
  -- last frame's engine split
  if n > 0 and pcall(Engine.Debug.getLastPerformanceMetrics, m) then
    sum.lua, sum.gc = sum.lua + (m.Lua or 0), sum.gc + (m.LuaGC or 0)
    worstGc = math.max(worstGc, m.LuaGC or 0)
  end
  n = n + 1
  local t = os.clock()
  local mesh = {verts = {}, faces = {}}
  live[#live + 1] = mesh
  local verts, faces = mesh.verts, mesh.faces
  for k = 1, PER_FRAME do
    verts[k] = {x = k * .5, y = k * .25, z = 3}
    faces[k] = {v = k, n = k, u = k}
    local junk = {k, k + 1, k + 2}   -- the generator's temporaries
    junk[1] = junk[2] + junk[3]
  end
  sum.ours = sum.ours + (os.clock() - t) * 1000
  sum.frame = sum.frame + (dt or 0) * 1000
  if MODE == 'stopEnd' then collectgarbage('stop') end
  if n > FRAMES then
    local heap1 = collectgarbage('count')
    live = nil
    collectgarbage('setstepmul', saved)
    collectgarbage('restart')
    local t2 = os.clock()
    collectgarbage('collect')
    return {mode = MODE, frames = FRAMES, oursMs = sum.ours / FRAMES, luaMs = sum.lua / FRAMES, gcMs = sum.gc / FRAMES,
      worstGc = worstGc, frameMs = sum.frame / FRAMES, heapStartMB = heap0 / 1024, heapEndMB = heap1 / 1024,
      collectMs = (os.clock() - t2) * 1000, afterMB = collectgarbage('count') / 1024, stepmul = saved}
  end
end)
