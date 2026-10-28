-- The GE Lua collector while EarthNG is the level. BeamNG steps the collector every frame, so a
-- new cycle starts as soon as one ends: setpause changes nothing, and each KB the generator
-- allocates pays stepmul/100 KB of collector work in the same frame. With the default 200 that
-- was ~100 ms of LuaGC a second in central Kyiv, in runs of 15-50 ms frames while a cycle swept
-- (a stock map: 4 ms). LOW halves that work. A fixed LOW let the garbage pile up after the car
-- stood still: then the engine swept 100-220 MB in one 0.7-1.2 s frame every ~9 s. So the
-- default comes back while the heap is RISE_MB over its recent floor (the live heap after a
-- sweep), and LOW again under BACK_MB (out/stutter, 28.10).
local M = {LOW = 100, RISE_MB = 96, BACK_MB = 48, FLOOR_S = 20}
local saved, floor, mode

function M.count() return collectgarbage('count') end

function M.step(ours, dt)
  if not ours then
    if saved then collectgarbage('setstepmul', saved) end
    saved, floor, mode = nil, nil, nil
    return
  end
  local kb = M.count()
  if not saved then
    saved = collectgarbage('setstepmul', M.LOW)
    floor, mode = kb, M.LOW
    return
  end
  -- the floor follows a sweep down at once and creeps up with the live heap
  if kb < floor then floor = kb else floor = floor + (kb - floor) * math.min(1, (dt or 0) / M.FLOOR_S) end
  local over = (kb - floor) / 1024
  local want = mode
  if over > M.RISE_MB then want = saved elseif over < M.BACK_MB then want = M.LOW end
  if want ~= mode then
    collectgarbage('setstepmul', want)
    mode = want
  end
end

function M.lowered() return mode ~= nil and mode == M.LOW and saved ~= M.LOW end

return M
